import asyncio
from pathlib import Path
import hashlib
import hmac
import os
import time
import logging
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, field_validator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response

from ..core.public_api import public_data
from ..core.auth.keycloak import require_authenticated, require_manage_users_request
from ..core.auth.internal import require_internal_secret

from ..services.shioaji_market import (
    ShioajiCacheUnavailableError,
    ShioajiNotConfiguredError,
    shioaji_market_service,
)
from ..services.ibkr_market import (
    IbkrCacheUnavailableError,
    IbkrNotConfiguredError,
    IbkrUnavailableError,
    attach_taiwan_only_regions,
    ibkr_market_service,
    merge_ibkr_into_portfolio,
)
from ..databases.portfolio_history_db import portfolio_history_db
from ..databases.market_dashboard_db import market_dashboard_db, market_for_currency
from ..databases.market_history_db import market_history_db
from ..databases.market_ai_analysis_db import market_ai_analysis_db, AnalysisConflict
from ..databases.analysis_timestamp_db import analysis_timestamp_db
from ..databases.market_price_target_db import market_price_target_db
from ..databases.market_notification_db import market_notification_db
from ..databases.market_watch_db import market_watch_db
from ..databases.market_reports_db import market_reports_db
from ..services import market_price_targets
from ..services.market_research import validate_research_content, list_research
from ..databases.market_industry_db import market_industry_db, validate_group
from ..services.market_selection import attach_underlying
from ..services.market_history_collector import market_history_collector
from ..services.market_fundamentals import market_fundamentals_service
from ..services.market_company_events import market_company_events_service
from ..services.market_brief import brief_markdown, market_brief_service
from ..services.market_macro import market_macro_service, MACRO_ENABLED
from ..services import market_automation, market_watch, telegram_notify
from ..services.routine_cost import estimate_cost
from ..services.token_reporter import report_token_usage_async

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/market", tags=["market"])


@router.get("/dashboard/overseas/{code}", **public_data("海外標的（美、日、韓）日線、財報與資料狀態", "行情與標的"))
async def get_overseas_research(code: str, market: str):
    """Public contract/market data from PostgreSQL only; no broker or account access."""
    from ..services.ibkr_research import ibkr_research_collector
    code, market = code.strip().upper(), market.strip().upper()
    if not re.fullmatch(r'[A-Z0-9.-]{1,24}', code) or market not in {'US', 'JP', 'KR', 'HK'}:
        raise HTTPException(status_code=422, detail='Invalid overseas instrument identity')
    try:
        return await asyncio.to_thread(ibkr_research_collector.read, code, market)
    except Exception:
        logger.exception('Persisted IBKR research unavailable')
        raise HTTPException(status_code=503, detail='Persisted overseas data temporarily unavailable')


class DashboardCustomSelection(BaseModel):
    symbols: list[dict[str, str]] = Field(max_length=5)


class MarketAiAnalysisUpdate(BaseModel):
    model: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1, max_length=20000)
    expectedRevision: int = Field(ge=0)

    @field_validator("model", "content")
    @classmethod
    def nonblank(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Must not be blank")
        return value


def analysis_target(code: str, product_type: str):
    normalized = code.strip().upper()
    if product_type not in {"stock", "futures", "macro", "macro-node", "research"} or not re.fullmatch(r"[A-Z0-9-]{1,24}", normalized):
        raise HTTPException(status_code=422, detail="Invalid instrument code or productType")
    # One shared macro commentary that every instrument analysis reads instead of restating.
    if product_type == "macro" and normalized != "US":
        raise HTTPException(status_code=422, detail="Macro commentary code must be US")
    # "macro-node": one analysis per node of the macro logic chains; the code is the node id from the frontend graph.
    return product_type, normalized


@router.get("/dashboard/analysis/{code}", **public_data("AI 分析、研究圖與其歷史版本", "AI 分析與研究"))
async def get_market_ai_analysis(code: str, productType: str = "stock"):
    target = analysis_target(code, productType)
    try:
        result = await asyncio.to_thread(market_ai_analysis_db.read, *target)
    except Exception as exc:
        logger.exception("AI analysis read failed")
        raise HTTPException(status_code=503, detail="Analysis database unavailable") from exc
    return {"code": target[1], "productType": target[0], **result,
            "historyLimit": 20, "writeMethod": "PUT", "writeAccess": "authenticated",
            "instructions": "Read the current analysis, review this instrument's data, then update the same analysis. "
                "Send model, content and expectedRevision (current revision, or 0 if absent). "
                "On 409 reload and reconcile your draft. Verify the returned saved revision."}


STAMP_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


@router.get("/timestamps", **public_data("AI 分析每日時間戳記（OpenTimestamps／比特幣）", "AI 分析與研究"))
async def list_analysis_timestamps():
    """One proof per Taipei day; the manifest lists that day's analysis revisions by SHA-256. See docs/ANALYSIS_TIMESTAMPS.md."""
    try:
        records = await asyncio.to_thread(analysis_timestamp_db.recent)
    except Exception as exc:
        logger.exception("Analysis timestamps read failed")
        raise HTTPException(status_code=503, detail="Timestamp database unavailable") from exc
    return {"days": [{"day": r["day"], "digest": r["digest"], "revisionCount": r["revisionCount"], "status": r["status"],
                      "bitcoinHeight": r["bitcoinHeight"], "calendars": r["calendars"], "submittedAt": r["submittedAt"].isoformat(),
                      "manifestUrl": f"/maya-sawa/market/timestamps/{r['day']}/manifest",
                      "proofUrl": f"/maya-sawa/market/timestamps/{r['day']}/proof"} for r in records],
            "verify": "Download the manifest and its .ots proof, then drop both on https://opentimestamps.org to verify."}


async def _stamp_record(day: str) -> dict:
    if not STAMP_DAY.fullmatch(day):
        raise HTTPException(status_code=404, detail="No timestamp for that day")
    try:
        record = await asyncio.to_thread(analysis_timestamp_db.get, day)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Timestamp database unavailable") from exc
    if not record:
        raise HTTPException(status_code=404, detail="No timestamp for that day")
    return record


@router.get("/timestamps/{day}/manifest", **public_data("某日被蓋章的分析清單（原始檔）", "AI 分析與研究"))
async def get_analysis_timestamp_manifest(day: str):
    record = await _stamp_record(day)
    return Response(record["manifest"].encode(), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="ai-analysis-{day}.json"'})


@router.get("/timestamps/{day}/proof", **public_data("某日的 OpenTimestamps 證明檔（.ots）", "AI 分析與研究"))
async def get_analysis_timestamp_proof(day: str):
    record = await _stamp_record(day)
    return Response(record["proof"], media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="ai-analysis-{day}.json.ots"'})


AGENT_EDITOR = "agent:scheduled-analysis"
AGENT_PRODUCT_TYPES = {"stock", "futures", "macro", "macro-node"}


async def analysis_editor(request: Request) -> str:
    """Who is writing an AI analysis: a signed-in user, or the scheduled analysis routine.

    The routine has no Keycloak login. It sends X-Market-Agent-Key, and the server keeps only that key's SHA-256
    (MARKET_AGENT_KEY_SHA256), so the deployment config holds no usable secret. The key writes only this endpoint.
    """
    key = request.headers.get("x-market-agent-key")
    if key is None:
        claims = await require_authenticated(request)
        if not claims.get("sub"):
            raise HTTPException(status_code=401, detail="Authenticated identity required")
        return str(claims["sub"])
    expected = os.environ.get("MARKET_AGENT_KEY_SHA256", "").strip().lower()
    if not expected or not hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), expected):
        raise HTTPException(status_code=401, detail="Invalid agent key")
    return AGENT_EDITOR


@router.put("/dashboard/analysis/{code}")
async def put_market_ai_analysis(code: str, body: MarketAiAnalysisUpdate, productType: str = "stock",
                                 editor: str = Depends(analysis_editor)):
    target = analysis_target(code, productType)
    if editor == AGENT_EDITOR and target[0] not in AGENT_PRODUCT_TYPES:
        raise HTTPException(status_code=403, detail="The agent key writes daily analyses only")
    if target[0] == "research":
        try:
            validate_research_content(body.content)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        analysis = await asyncio.to_thread(market_ai_analysis_db.save, *target, body.model, body.content,
                                          body.expectedRevision, str(editor))
        return {"analysis": analysis, "saved": True}
    except AnalysisConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("AI analysis save failed")
        raise HTTPException(status_code=503, detail="Analysis database unavailable") from exc


class NotifyBody(BaseModel):
    kind: str = Field(pattern="^(update|attention)$")
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(default="", max_length=3000)


@router.post("/notify")
async def notify_owner(body: NotifyBody, request: Request):
    """A scheduled routine tells the owner something over Telegram: 'update' (work saved) or 'attention' (it needs a
    login or is stuck). Agent key only; the bot token and chat id stay in the deployment environment."""
    _verify_agent_key(request)
    try:  # keep a copy for the site's bell; a storage failure must not stop the Telegram message
        await asyncio.to_thread(market_notification_db.add, body.kind, telegram_notify.mask(body.title),
                                telegram_notify.mask(body.body))
    except Exception:
        logger.exception("Notification history save failed")
    return await asyncio.to_thread(telegram_notify.send, body.kind, body.title, body.body)


@router.get("/notifications")
async def list_notifications(limit: int = 100, _claims: dict = Depends(require_manage_users_request)):
    """The owner's notification history (newest first), shown in the site's bell."""
    try:
        return {"notifications": await asyncio.to_thread(market_notification_db.recent, max(1, min(limit, 200)))}
    except Exception as exc:
        logger.exception("Notification history read failed")
        raise HTTPException(status_code=503, detail="Notification database unavailable") from exc


class RoutineModelUsage(BaseModel):
    model: str = Field(min_length=1, max_length=80)
    input: int = Field(ge=0, le=10**10)
    output: int = Field(ge=0, le=10**10)
    cacheCreation: int = Field(default=0, ge=0, le=10**10)
    cacheRead: int = Field(default=0, ge=0, le=10**10)


class RoutineUsage(BaseModel):
    sessionId: str = Field(min_length=1, max_length=80)
    label: str = Field(default="routine", max_length=100)
    models: list[RoutineModelUsage] = Field(min_length=1, max_length=8)


@router.post("/routine-usage")
async def record_routine_usage(body: RoutineUsage, request: Request):
    """A scheduled cloud routine reports the tokens its own session used (agent key only). Recorded as provider
    claude-routine, which the portfolio chart plots as its cost line."""
    _verify_agent_key(request)
    results = {}
    for item in body.models:
        results[item.model] = await report_token_usage_async(
            ai_provider="claude-routine", model_name=item.model, input_tokens=item.input, output_tokens=item.output,
            cache_creation_input_tokens=item.cacheCreation, cache_read_input_tokens=item.cacheRead,
            estimated_cost_usd=estimate_cost(item.model, item.input, item.output, item.cacheCreation, item.cacheRead),
            session_id=body.sessionId, endpoint=f"/market/routine-usage/{body.label}")
    failed = {model: status for model, status in results.items() if status not in (200, 201)}
    return {"recorded": len(results) - len(failed), "failed": failed}


@router.get("/routine-usage.py", response_class=PlainTextResponse)
async def routine_usage_script():
    """The reporting script, so a routine without a repository checkout can run `curl … | python3 - label`."""
    # Kept inside the package: the Docker image excludes the top-level scripts/ directory.
    return PlainTextResponse((Path(__file__).resolve().parents[1] / "public_scripts" / "report_routine_usage.py").read_text(encoding="utf-8"))


def _verify_agent_key(request: Request) -> None:
    key = request.headers.get("x-market-agent-key")
    expected = os.environ.get("MARKET_AGENT_KEY_SHA256", "").strip().lower()
    if not key or not expected or not hmac.compare_digest(hashlib.sha256(key.encode()).hexdigest(), expected):
        raise HTTPException(status_code=401, detail="Invalid agent key")


class WatchNomination(BaseModel):
    code: str = Field(pattern=r"^\d{4}$")  # Taiwan stocks only: the custom area's data, history and analysis flow is Taiwan's
    name: str | None = Field(default=None, max_length=40)
    reason: str = Field(min_length=10, max_length=300)
    reportIds: list[str] = Field(min_length=1, max_length=10)
    conviction: str = Field(default="normal", pattern="^(normal|high)$")


def _held_stock_codes() -> set[str]:
    return {str(item.get("code", "")).upper() for item in market_dashboard_db.latest_auto().get("positions", [])}


@router.post("/watch")
async def nominate_watch(body: WatchNomination, request: Request):
    """The analyst, after reading research reports, nominates a stock for the custom area. Agent key only.
    Entry needs two different reports (or conviction 'high'); see services/market_watch.py for how long it stays."""
    _verify_agent_key(request)
    held = _held_stock_codes()
    if body.code in held:
        raise HTTPException(status_code=422, detail=f"{body.code} is already a holding")
    for report_id in dict.fromkeys(body.reportIds):
        found = await asyncio.to_thread(market_reports_db.get_report, report_id)
        if not found or found[0].get("visibility") != "public" or found[0].get("status") != "ready":
            raise HTTPException(status_code=422, detail=f"Report {report_id} is not a public, ready report")
    name = (body.name or "").strip()
    try:
        matches = await shioaji_market_service.search_contracts(body.code, "stock")
    except Exception:
        matches = []
    match = next((item for item in matches if item["code"].upper() == body.code), None) or await asyncio.to_thread(
        market_dashboard_db.find_candidate, "stock", body.code)
    if not match:
        raise HTTPException(status_code=422, detail=f"Unknown Taiwan stock: {body.code}")
    now = datetime.now(ZoneInfo("UTC"))
    mentions = [{"at": now.isoformat(), "source": report_id, "conviction": body.conviction, "reason": body.reason.strip()}
                for report_id in dict.fromkeys(body.reportIds)]
    try:
        rows, promoted = await asyncio.to_thread(market_watch_db.nominate, body.code, "TW", match["name"] or name, mentions, now, held)
    except Exception as exc:
        logger.exception("Watch list save failed")
        raise HTTPException(status_code=503, detail="Watch list unavailable") from exc
    if promoted:  # new in the custom area: fetch its history and write its first analysis now, not at the next scheduled run
        await market_history_collector.enqueue_codes(promoted)
        start_added_analysis([{"code": code, "name": match["name"], "productType": "stock"} for code in promoted])
    status = next(row["status"] for row in rows if row["code"] == body.code)
    return {"code": body.code, "status": status, "promoted": body.code in promoted}


@router.get("/watch", **public_data("AI 觀察名單：觀察中與候選的標的", "AI 觀察名單"))
async def get_watch():
    """Public: the stocks in the custom area because of the analyst's reading, and the candidates still waiting."""
    try:
        return {"watching": await asyncio.to_thread(market_watch_db.current, None, _held_stock_codes()),
                "candidates": await asyncio.to_thread(market_watch_db.candidates)}
    except Exception as exc:
        logger.exception("Watch list read failed")
        raise HTTPException(status_code=503, detail="Watch list unavailable") from exc


class PriceTargetUpdate(BaseModel):
    actions: list[dict] = Field(min_length=1, max_length=50)


def price_target_identity(code: str, market: str) -> tuple[str, str]:
    code, market = code.strip().upper(), market.strip().upper()
    if not re.fullmatch(r"[A-Z0-9.-]{1,24}", code) or market not in market_price_targets.MARKET_CURRENCY:
        raise HTTPException(status_code=422, detail="Invalid instrument identity")
    return code, market


@router.get("/dashboard/targets/{code}", **public_data("券商目標價、共識與相關報告觀點", "行情與標的"))
async def get_price_targets(code: str, market: str = "TW"):
    """Broker target prices (per broker and consensus) from Yahoo Finance and the AI routine's sourced news."""
    code, market = price_target_identity(code, market)
    try:
        data = await asyncio.to_thread(market_price_target_db.read, code, market)
    except Exception as exc:
        logger.exception("Price target read failed")
        raise HTTPException(status_code=503, detail="Price target database unavailable") from exc
    return {"code": code, "market": market, "currency": market_price_targets.MARKET_CURRENCY[market], **data,
            "views": await asyncio.to_thread(report_views, code, market),
            "writeMethod": "PUT", "writeAccess": "owner or X-Market-Agent-Key",
            "instructions": "Add broker targets found in news: actions[] of {firm, date YYYY-MM-DD, target, rating?, "
                "previousTarget?, sourceUrl, thesis? (the broker's reasoning, max 300 chars), reportId? (library report)}. "
                "Only targets stated in the article; same firm and date replaces."}


def report_views(code: str, market: str) -> list[dict]:
    """Public report claims about this stock, dated by the report's publication (or the claim's data date), newest first.

    Claims name Taiwan stocks by number and others as CODE-MARKET (LITE-US); some reports use the bare ticker."""
    aliases = [code] if market == "TW" else [f"{code}-{market}", code]
    views, seen = [], set()
    try:
        for alias in aliases:
            for claim in market_reports_db.list_claims(code=alias):
                key = (claim["report_id"], claim["page"], claim["claim"])
                if key in seen:
                    continue
                seen.add(key)
                # Date of the view: the publication date, else the claim's data cut-off, else the day it was recorded here.
                date, kind = next(((value, name) for value, name in ((claim["published_at"], "published"), (claim["as_of"], "data"),
                                                                     ((claim.get("received_at") or "")[:10] or None, "recorded")) if value), (None, None))
                views.append({"reportId": claim["report_id"], "title": claim["title"], "publisher": claim["publisher"],
                              "date": date, "dateKind": kind, "sourceUrl": claim.get("source_url"), "page": claim["page"],
                              "dimension": claim["dimension"], "direction": claim["direction"],
                              "claim": claim["claim"], "evidence": claim["evidence"]})
    except Exception:
        logger.exception("Report views for %s %s unavailable", code, market)
        return []
    return sorted(views, key=lambda view: view["date"] or "", reverse=True)


@router.put("/dashboard/targets/{code}")
async def put_price_targets(code: str, body: PriceTargetUpdate, market: str = "TW",
                            editor: str = Depends(analysis_editor)):
    code, market = price_target_identity(code, market)
    try:
        actions = market_price_targets.validate_routine_actions(body.actions, datetime.now(ZoneInfo("Asia/Taipei")).date())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        saved = await asyncio.to_thread(market_price_target_db.save_actions, code, market,
                                        market_price_targets.MARKET_CURRENCY[market], actions, source="ai-routine")
    except Exception as exc:
        logger.exception("Price target save failed")
        raise HTTPException(status_code=503, detail="Price target database unavailable") from exc
    logger.info("Price targets for %s %s written by %s: %d", code, market, editor, saved)
    return {"saved": saved}


@router.get("/dashboard/macro/nodes", **public_data("總經邏輯鏈各節點的判讀", "總體經濟"))
async def list_macro_node_analyses():
    """Every macro logic-chain node's current analysis, so the dashboard loads them in one request."""
    try:
        return {"analyses": await asyncio.to_thread(market_ai_analysis_db.list, "macro-node")}
    except Exception as exc:
        logger.exception("Macro node analysis list failed")
        raise HTTPException(status_code=503, detail="Analysis database unavailable") from exc


@router.get("/dashboard/research", **public_data("所有標的的研究圖紀錄", "AI 分析與研究"))
async def list_market_research():
    """All stored research maps, including instruments no longer held (records are never deleted)."""
    try:
        return {"records": await asyncio.to_thread(list_research, market_ai_analysis_db)}
    except Exception as exc:
        logger.exception("Research list failed")
        raise HTTPException(status_code=503, detail="Analysis database unavailable") from exc


@router.get("/dashboard/industries", **public_data("產業分組", "AI 分析與研究"))
async def list_market_industries(code: str | None = None):
    """Industry groups (族群) with their member stocks; with ?code= only the groups that stock belongs to."""
    if code is not None and not re.fullmatch(r"[A-Z0-9]{1,12}(-[A-Z]{2})?", code.strip().upper()):
        raise HTTPException(status_code=422, detail="Invalid record code")
    try:
        groups = await asyncio.to_thread(market_industry_db.groups_for, code.strip().upper()) if code else             await asyncio.to_thread(market_industry_db.list_groups)
    except Exception as exc:
        logger.exception("Industry groups unavailable")
        raise HTTPException(status_code=503, detail="Industry database unavailable") from exc
    return {"groups": groups}


@router.put("/dashboard/industries/{group_id}")
async def put_market_industry(group_id: str, body: dict, claims: dict = Depends(require_authenticated)):
    if body.get("id") != group_id:
        raise HTTPException(status_code=422, detail="Group id in the body must match the URL")
    try:
        validate_group(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        return {"group": await asyncio.to_thread(market_industry_db.save_group, body), "saved": True}
    except Exception as exc:
        logger.exception("Industry group save failed")
        raise HTTPException(status_code=503, detail="Industry database unavailable") from exc


@router.get("/dashboard", **public_data("儀表板標的清單與即時報價（固定、自動、自訂、AI 觀察）", "行情與標的"))
async def get_market_dashboard():
    """Public, privacy-safe selection and live quotes; never returns account values."""
    auto = market_dashboard_db.latest_auto()
    custom = market_dashboard_db.custom_symbols()
    seen: set[tuple[str, ...]] = set()
    # The cached IBKR snapshot (read-only, refreshed by its own loop) tells which codes are overseas holdings,
    # including selections stored before rows carried a market.
    try:
        ibkr_snapshot = await ibkr_market_service.get_snapshot()
    except Exception as exc:
        ibkr_snapshot = {}
        logger.info("IBKR cached market quotes unavailable: %s", exc)
    ibkr_stocks = [position for position in ibkr_snapshot.get("positions", [])
                   if str(position.get("assetClass") or "").upper() == "STK" and position.get("code")]
    ibkr_markets = {str(position["code"]).upper(): market_for_currency(position.get("currency")) for position in ibkr_stocks}
    auto_rows = []
    for item in auto["positions"]:
        item = {**item, "market": item.get("market") or ibkr_markets.get(item["code"].upper(), "TW")}
        key = (item["code"].upper(), item["market"])
        if key not in seen:
            seen.add(key)
            auto_rows.append(item)
    custom_rows = []
    for item in custom:
        item = {**item, "market": item.get("market") or "TW"}  # custom picks come from the Taiwan contract search
        key = (item["productType"], item["code"].upper())
        if key not in seen:
            seen.add(key)
            custom_rows.append(item)
    # Stocks the analyst found in research reports sit in the custom area until the reports move on (see market_watch).
    watched = await asyncio.to_thread(market_dashboard_db.watch_symbols)
    custom_rows = market_watch.merge_into_custom(custom_rows, watched, taken={("stock", item["code"].upper()) for item in auto_rows})
    # Quotes are keyed by (productType, code, market): Shioaji only quotes Taiwan instruments.
    quotes: dict[tuple[str, str, str], dict] = {}
    try:
        rows = await shioaji_market_service.get_dashboard_quotes([item for item in auto_rows + custom_rows if item["market"] == "TW"])
        quotes = {(item["productType"], item["symbol"].upper(), "TW"): item for item in rows}
    except Exception as exc:
        logger.info("Market selection quotes unavailable: %s", exc)
    # The authenticated IBKR gateway refresh loop owns upstream calls. Public
    # dashboard reads only the cached snapshot and expose quote fields, never
    # account quantities, market values, or account identifiers.
    # IBKR quotes its own holdings under their own market, so they never replace a Taiwan quote.
    for position in ibkr_stocks:
        code = str(position.get("code") or "").upper()
        key = ("stock", code, market_for_currency(position.get("currency")))
        if key in quotes or not code or not position.get("lastPrice"):
            continue
        from ..services.ibkr_research import dashboard_quote, ibkr_research_collector
        persisted = None
        if position.get('conid'):
            try:
                persisted = await asyncio.to_thread(ibkr_research_collector.db.latest, code, key[2], 'quote')
            except Exception:
                logger.warning('Persisted IBKR quote unavailable; using position valuation')
        quotes[key] = dashboard_quote(position, ibkr_snapshot.get('fetchedAt'), persisted)
    try:
        txf = await shioaji_market_service.get_taiex_futures_quote()
    except Exception:
        txf = None
    # Stock futures must always resolve to their underlying stock (charts, chips, fundamentals all use it).
    # A live quote carries underlyingCode; when Shioaji is unavailable fall back to the persisted snapshots.
    await asyncio.to_thread(attach_underlying, auto_rows + custom_rows, list(quotes.values()))

    def expose(item: dict) -> dict:
        return {**item, "quote": quotes.get((item["productType"], item["code"].upper(), item["market"]))}
    return {
        "fixed": {"code": "TXF", "name": "TAIEX Futures · front month", "productType": "futures", "quote": txf},
        "automatic": {"snapshotAt": auto["snapshotAt"], "positions": [expose(item) for item in auto_rows]},
        "custom": [expose(item) for item in custom_rows],
        "customLimit": 5,
    }


@router.get("/dashboard/events", **public_data("近期營收／財報發布與法說會", "行情與標的"))
async def get_market_dashboard_events():
    """Recent revenue/report releases and upcoming investor conferences for selected stock targets."""
    auto = market_dashboard_db.latest_auto()
    symbols = [*auto.get("positions", []), *market_dashboard_db.custom_symbols(), *market_dashboard_db.watch_symbols()]
    try:
        quote_rows = await shioaji_market_service.get_dashboard_quotes(symbols)
        await asyncio.to_thread(attach_underlying, symbols, quote_rows)
    except Exception as exc:
        logger.info("Unable to resolve company underlyings for event targets: %s", exc)
    codes: set[str] = set()
    for item in symbols:
        if item.get("productType") == "stock":
            codes.add(str(item.get("code", "")).strip())
        elif item.get("underlyingCode"):
            codes.add(str(item["underlyingCode"]).strip())
    try:
        return await market_company_events_service.get(sorted(codes))
    except Exception as exc:
        logger.exception("Market company events request failed")
        raise HTTPException(status_code=502, detail="Company events are temporarily unavailable") from exc


@router.get("/dashboard/macro", **public_data("總體經濟指標序列", "總體經濟"))
async def get_market_macro_dashboard(historyMonths: int = 24):
    """Persisted macro indicators and release calendar. GET never calls upstream providers."""
    if not MACRO_ENABLED:
        return {"status": "disabled", "enabled": False, "displayTimezone": "Asia/Taipei",
                "indicators": [], "events": [], "sources": [], "configuration": {"feature": "disabled"}}
    if historyMonths < 12 or historyMonths > 60:
        raise HTTPException(status_code=422, detail="historyMonths must be between 12 and 60")
    try:
        return await market_macro_service.get(historyMonths)
    except Exception as exc:
        logger.exception("Market macro snapshot failed")
        raise HTTPException(status_code=503, detail="Macroeconomic data is temporarily unavailable") from exc


@router.get("/dashboard/brief", **public_data("持股籌碼摘要", "AI 分析與研究"))
async def get_market_brief(format: str = "json", lang: str = "zh"):
    """Public agent-readable chip summary of the selected holdings; codes only, never account values."""
    brief = await market_brief_service.get()
    if format == "md":
        return PlainTextResponse(brief_markdown(brief, "en" if lang == "en" else "zh"), media_type="text/markdown; charset=utf-8")
    return brief


@router.get("/dashboard/search")
async def search_market_contracts(q: str, productType: str | None = None,
                                 _claims: dict = Depends(require_manage_users_request)):
    if productType not in (None, "stock", "futures"):
        raise HTTPException(status_code=422, detail="productType must be stock or futures")
    try:
        results = await shioaji_market_service.search_contracts(q[:40], productType)
        # Searchable Shioaji contracts form the candidate universe until
        # external source-list ingestion is configured and verified.
        market_dashboard_db.record_candidates("shioaji-search", results)
        return {"results": results}
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail={"code": "not_configured", "message": str(exc)}) from exc
    except Exception as exc:
        logger.exception("Market contract search failed")
        raise HTTPException(status_code=502, detail="Market contract search unavailable") from exc


@router.get("/dashboard/custom")
async def get_market_dashboard_custom(_claims: dict = Depends(require_manage_users_request)):
    return {"symbols": market_dashboard_db.custom_symbols(), "limit": 5}


@router.get("/dashboard/candidates")
async def get_market_dashboard_candidates(q: str = "", limit: int = 100,
                                         _claims: dict = Depends(require_manage_users_request)):
    return {"results": market_dashboard_db.list_candidates(q[:40], min(max(limit, 1), 200))}


@router.get("/dashboard/history/{code}", **public_data("個股日線與籌碼歷史（最多五年）", "行情與標的"))
async def get_market_dashboard_history(code: str, start: date | None = None, end: date | None = None,
                                      view: str = "daily"):
    """Public daily price and chip history; no account or portfolio fields are exposed."""
    normalized = code.strip().upper()
    if not normalized or len(normalized) > 24 or not normalized.replace("-", "").isalnum():
        raise HTTPException(status_code=422, detail="Invalid instrument code")
    end_date = end or datetime.now(ZoneInfo("Asia/Taipei")).date()
    start_date = start or (end_date - timedelta(days=92))
    if start_date > end_date or (end_date - start_date).days > 5 * 366:
        raise HTTPException(status_code=422, detail="History range must be within five years (1830 days)")
    sources = ["tdcc:distribution-history", "twse:foreign-holding", "tpex:foreign-holding"] if view == "ownership" else None
    if view not in {"daily", "ownership"}:
        raise HTTPException(status_code=422, detail="view must be daily or ownership")
    result = market_history_db.history(normalized, start_date, end_date, sources=sources)
    # A stock nobody selected before has no stored rows; start its backfill instead of leaving the charts empty.
    collecting = False
    if not result["points"] and normalized.isdigit() and len(normalized) == 4:
        collecting = True
        last = _history_backfill_requested.get(normalized, 0.0)
        if time.monotonic() - last > HISTORY_BACKFILL_COOLDOWN_SECONDS:
            _history_backfill_requested[normalized] = time.monotonic()
            await market_history_collector.enqueue_codes([normalized])
    return {"code": normalized, "view": view, "start": start_date.isoformat(), "end": end_date.isoformat(),
            "collecting": collecting, **result}


HISTORY_BACKFILL_COOLDOWN_SECONDS = 600
_history_backfill_requested: dict[str, float] = {}


@router.get("/dashboard/fundamentals/{code}", **public_data("個股月營收與季度財報（官方資料）", "行情與標的"))
async def get_market_fundamentals(code: str):
    """On-demand official TWSE/MOPS current revenue and quarterly statements."""
    try:
        return await market_fundamentals_service.get(code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Market fundamentals request failed")
        raise HTTPException(status_code=502, detail="Official fundamentals are temporarily unavailable") from exc


@router.put("/dashboard/custom")
async def put_market_dashboard_custom(body: DashboardCustomSelection,
                                      _claims: dict = Depends(require_manage_users_request)):
    seen: set[str] = set()
    normalized = []
    automatic = {item["code"].upper() for item in market_dashboard_db.latest_auto()["positions"]}
    for item in body.symbols:
        code, name, kind = (str(item.get(key, "")).strip() for key in ("code", "name", "productType"))
        key = code.upper()
        if kind not in ("stock", "futures") or not code or not name:
            raise HTTPException(status_code=422, detail="Each selection requires a valid code, name and productType")
        if key not in seen:
            if key in automatic or (kind == "futures" and code.upper() == "TXF"):
                raise HTTPException(status_code=422, detail=f"{code} is already in the fixed or automatic selection")
            search_error = None
            try:
                matches = await shioaji_market_service.search_contracts(code, kind)
            except Exception as exc:
                logger.exception("Unable to validate dashboard custom instrument")
                matches = []
                search_error = exc
            match = next((result for result in matches if result["code"].upper() == code.upper()), None)
            if (not match and kind == "futures" and code.upper().endswith(("R1", "R2"))
                    and matches):
                # Resolve legacy/custom rolling aliases to the current listed
                # month returned by the contract directory.
                match = matches[0]
            if not match:
                # Historical candidates remain selectable after a contract
                # leaves the current directory; live quotes may be absent.
                match = market_dashboard_db.find_candidate(kind, code)
            if not match:
                if search_error:
                    raise HTTPException(status_code=503, detail="Instrument validation is temporarily unavailable") from search_error
                raise HTTPException(status_code=422, detail=f"Unknown {kind} contract: {code}")
            seen.add(key)
            normalized.append({"code": code.upper(), "name": match["name"], "productType": kind,
                               **({"deliveryMonth": match["deliveryMonth"]} if match.get("deliveryMonth") else {})})
    if len(normalized) > 5:
        raise HTTPException(status_code=422, detail="At most five custom instruments are allowed")
    try:
        previous = {(item["code"].upper(), item.get("productType")) for item in market_dashboard_db.custom_symbols()}
        added = [item for item in normalized if (item["code"], item["productType"]) not in previous]
        market_dashboard_db.save_custom_symbols(normalized)
        await market_history_collector.enqueue_codes(
            [item["code"] for item in normalized if item["productType"] == "stock"]
        )
        await market_history_collector.enqueue_futures(
            [item for item in normalized if item["productType"] == "futures"]
        )
    except Exception as exc:
        logger.exception("Failed to save market dashboard settings")
        raise HTTPException(status_code=503, detail="Market dashboard settings unavailable") from exc
    if added:
        start_added_analysis(added)
    return {"symbols": market_dashboard_db.custom_symbols(), "limit": 5, "added": [item["code"] for item in added]}


_added_tasks: set[asyncio.Task] = set()


def start_added_analysis(items: list[dict]) -> None:
    """Fill a new pick's data and start its first AI analysis now, instead of at the next scheduled run."""
    async def run():
        result = await market_automation.analyze_added(market_automation.automation_store(), items, _collect_added)
        logger.info("Added instruments %s: analysis %s", result["codes"], result["state"])

    task = asyncio.create_task(run())
    _added_tasks.add(task)  # keep a reference until it finishes
    task.add_done_callback(_added_tasks.discard)


async def _collect_added(items: list[dict]) -> None:
    stocks = [item["code"] for item in items if item["productType"] == "stock"]
    futures = [item for item in items if item["productType"] == "futures"]
    if stocks:
        market_fundamentals_service.request_history(stocks)  # FinMind statements, queued ahead of the daily pass
        await market_history_collector.collect_codes(stocks)
        from ..services.market_price_targets import price_target_collector
        await price_target_collector.collect_now([{**item, "market": "TW"} for item in items if item["productType"] == "stock"])
    if futures:
        await asyncio.to_thread(market_history_collector.collect_futures_codes, futures)


async def _portfolio_with_ibkr() -> dict:
    """Shioaji portfolio with IBKR folded in when enabled and reachable.

    Read policy: Redis cache first (via the Shioaji service); if the cache is
    empty, fall back to the latest Postgres history snapshot. IBKR failures never
    break the base portfolio. A throttled history snapshot is recorded on the way
    out so the DB accrues a time series.
    """
    try:
        portfolio = await shioaji_market_service.get_portfolio()
    except ShioajiCacheUnavailableError:
        snapshot = await asyncio.to_thread(portfolio_history_db.latest_snapshot)
        if snapshot is not None:
            logger.info("Serving portfolio from Postgres history (Redis cache empty)")
            return snapshot
        raise

    try:
        fixed_quote = await shioaji_market_service.get_taiex_futures_quote()
    except Exception:
        fixed_quote = None
        logger.info("Fixed TXF quote unavailable while refreshing public automatic selection")
    if not ibkr_market_service.enabled:
        merged = attach_taiwan_only_regions(portfolio)
    else:
        try:
            ibkr_snapshot = await ibkr_market_service.get_snapshot()
            merged = merge_ibkr_into_portfolio(portfolio, ibkr_snapshot)
        except (IbkrNotConfiguredError, IbkrUnavailableError, IbkrCacheUnavailableError) as exc:
            logger.warning("Skipping IBKR merge: %s", exc)
            merged = attach_taiwan_only_regions(portfolio)
        except Exception:
            logger.exception("Unexpected error merging IBKR portfolio")
            merged = attach_taiwan_only_regions(portfolio)

    try:
        await asyncio.to_thread(market_dashboard_db.record_portfolio, merged,
                                 fixed_quote.get("symbol") if fixed_quote else None)
    except Exception:
        logger.exception("Failed to update public automatic market selection")

    try:
        # A dashboard read can be the first successful access after the market
        # close. Persist the valid Taiwan source snapshot before returning it,
        # so the following history request can include today's daily point.
        await asyncio.to_thread(portfolio_history_db.record_taiwan, portfolio)
    except Exception:
        logger.exception("Failed to record Taiwan portfolio daily point (non-fatal)")

    try:
        await asyncio.to_thread(portfolio_history_db.record_if_due, merged)
    except Exception:
        logger.exception("Failed to record portfolio history (non-fatal)")
    return merged


@router.get("/auth-status")
async def get_market_auth_status(
    claims: dict = Depends(require_manage_users_request),
):
    return {
        "authenticated": True,
        "subject": claims.get("preferred_username") or claims.get("sub"),
        "roles": claims.get("_roles", []),
        "clientId": claims.get("azp"),
        "audience": claims.get("aud"),
    }


@router.get("/taiex-futures", **public_data("台指期近月報價", "行情與標的"))
async def get_taiex_futures_quote():
    try:
        return await shioaji_market_service.get_taiex_futures_quote()
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except ShioajiCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch TXF quote")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "quote_unavailable",
                "message": "Taiex futures quote is temporarily unavailable",
            },
        ) from exc


@router.get("/mini-tsmc-futures", **public_data("小型台積電期貨報價", "行情與標的"))
async def get_mini_tsmc_futures_quote():
    try:
        return await shioaji_market_service.get_mini_tsmc_futures_quote()
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except ShioajiCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch QFFR1 quote")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "quote_unavailable",
                "message": "Mini TSMC futures quote is temporarily unavailable",
            },
        ) from exc


@router.get("/portfolio")
async def get_portfolio(_claims: dict = Depends(require_manage_users_request)):
    if not shioaji_market_service.portfolio_enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "portfolio_disabled",
                "message": "Portfolio dashboard is disabled",
            },
        )
    try:
        return await _portfolio_with_ibkr()
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except ShioajiCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch portfolio")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "portfolio_unavailable",
                "message": "Portfolio data is temporarily unavailable",
            },
        ) from exc


@router.post("/automation/check")
async def check_market_automation(_claims: dict = Depends(require_manage_users_request)):
    """Owner opened the site: report the IBKR session and fire analysis routines that are due."""
    return await market_automation.check(market_automation.automation_store(), market_automation.IbkrSource())


@router.get("/ibkr")
async def get_ibkr_snapshot(_claims: dict = Depends(require_manage_users_request)):
    return await _ibkr_snapshot_or_503()


@router.get("/internal/ibkr")
async def get_ibkr_snapshot_internal(_=Depends(require_internal_secret)):
    return await _ibkr_snapshot_or_503()


async def _ibkr_snapshot_or_503() -> dict:
    try:
        return await ibkr_market_service.get_snapshot()
    except IbkrNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except IbkrUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "gateway_unavailable", "message": str(exc)},
        ) from exc
    except IbkrCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch IBKR snapshot")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "ibkr_unavailable",
                "message": "IBKR data is temporarily unavailable",
            },
        ) from exc


@router.get("/portfolio/history")
async def get_portfolio_history(
    limit: int = 90, _claims: dict = Depends(require_manage_users_request)
):
    return await _portfolio_history(limit)


@router.get("/internal/portfolio/history")
async def get_portfolio_history_internal(limit: int = 90, _=Depends(require_internal_secret)):
    return await _portfolio_history(limit)


async def _portfolio_history(limit: int) -> dict:
    try:
        rows = await asyncio.to_thread(portfolio_history_db.history, limit)
    except Exception as exc:
        logger.exception("Failed to read portfolio history")
        raise HTTPException(
            status_code=503,
            detail={"code": "history_unavailable", "message": "Portfolio history unavailable"},
        ) from exc
    return {"count": len(rows), "history": rows}


@router.get("/usage")
async def get_market_usage(_claims: dict = Depends(require_manage_users_request)):
    try:
        return await shioaji_market_service.get_usage()
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except ShioajiCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch Shioaji usage")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "usage_unavailable",
                "message": "Shioaji usage is temporarily unavailable",
            },
        ) from exc


@router.get("/internal/usage")
async def get_market_usage_internal(_=Depends(require_internal_secret)):
    try:
        return await shioaji_market_service.get_usage()
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except ShioajiCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch Shioaji usage (internal)")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "usage_unavailable",
                "message": "Shioaji usage is temporarily unavailable",
            },
        ) from exc


@router.get("/internal/portfolio")
async def get_portfolio_internal(_=Depends(require_internal_secret)):
    if not shioaji_market_service.portfolio_enabled:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "portfolio_disabled",
                "message": "Portfolio dashboard is disabled",
            },
        )
    try:
        return await _portfolio_with_ibkr()
    except ShioajiNotConfiguredError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "not_configured", "message": str(exc)},
        ) from exc
    except ShioajiCacheUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "cache_unavailable", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Failed to fetch portfolio (internal)")
        raise HTTPException(
            status_code=502,
            detail={
                "code": "portfolio_unavailable",
                "message": "Portfolio data is temporarily unavailable",
            },
        ) from exc
