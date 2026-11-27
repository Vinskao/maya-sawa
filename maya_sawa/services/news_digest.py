"""Twice-daily company announcement + news digest for holdings and watch lists, summarized by Gemini (docs/NEWS_DIGEST.md).

Taiwan pre-open (08:00 Taipei) covers Taiwan stocks; US pre-open (08:00 New York) covers overseas stocks. Each digest
looks back 24 hours, so the two never repeat each other. Sources:
  Taiwan: TWSE / TPEx daily material announcements (OpenAPI), cnyes stock-tagged news.
  Overseas: SEC EDGAR 8-K filings (data.sec.gov), Google News RSS per ticker.
Gemini only summarizes the items given to it; without a key or on failure the digest lists the headlines instead.
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .macro_releases import parse_feed

logger = logging.getLogger(__name__)

TPE = ZoneInfo("Asia/Taipei")
NY = ZoneInfo("America/New_York")
LOOKBACK = timedelta(hours=24)
SESSIONS = {"tw": (TPE, time(8, 0)), "us": (NY, time(8, 0))}
SESSION_LABEL = {"tw": "台股盤前摘要", "us": "美股盤前摘要"}
GEMINI_MODEL = os.getenv("NEWS_DIGEST_GEMINI_MODEL", "gemini-2.5-flash")
MAX_ITEMS_PER_CODE = 8
SEC_ITEMS = {"1.01": "重大合約", "1.02": "合約終止", "2.01": "併購／處分資產", "2.02": "財報", "2.03": "新增負債",
             "2.05": "重組費用", "2.06": "資產減損", "3.01": "下市通知", "5.02": "高層異動", "7.01": "公開說明",
             "8.01": "其他重大事件"}
TWSE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
TPEX_URL = "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap04_O"
CNYES_URL = "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock?limit=100"
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "maya-sawa research bot")


# ---------- parsers (pure) ----------

def _roc(day: str, clock: str) -> datetime | None:
    day, clock = str(day or "").strip(), str(clock or "").strip().zfill(6)
    if not re.fullmatch(r"\d{7}", day) or not re.fullmatch(r"\d{6}", clock):
        return None
    try:
        return datetime(int(day[:3]) + 1911, int(day[3:5]), int(day[5:7]),
                        int(clock[:2]), int(clock[2:4]), int(clock[4:6]), tzinfo=TPE)
    except ValueError:
        return None


def _clean(text: Any) -> str:
    return re.sub(r"\s+", "", html.unescape(str(text or ""))) if re.search(r"[一-鿿]", str(text or "")) \
        else re.sub(r"\s+", " ", html.unescape(str(text or ""))).strip()


def _field(row: dict, *names: str) -> str:
    for name in names:
        for key, value in row.items():
            if key.strip() == name:
                return str(value or "")
    return ""


def _announcements(rows: list[dict], codes: set[str], since: datetime, code_keys: tuple[str, ...],
                   name_keys: tuple[str, ...]) -> list[dict]:
    items = []
    for row in rows if isinstance(rows, list) else []:
        code = _field(row, *code_keys).strip()
        published = _roc(_field(row, "發言日期"), _field(row, "發言時間"))
        if code not in codes or published is None or published < since:
            continue
        items.append({"code": code, "name": _field(row, *name_keys).strip(), "kind": "公告",
                      "title": _clean(_field(row, "主旨")), "detail": _clean(_field(row, "說明"))[:300],
                      "published": published, "link": "https://mops.twse.com.tw/mops/#/web/t05sr01_1"})
    return items


def twse_announcements(rows: list[dict], codes: set[str], since: datetime) -> list[dict]:
    return _announcements(rows, codes, since, ("公司代號",), ("公司名稱",))


def tpex_announcements(rows: list[dict], codes: set[str], since: datetime) -> list[dict]:
    return _announcements(rows, codes, since, ("SecuritiesCompanyCode", "公司代號"), ("CompanyName", "公司名稱"))


def cnyes_news(payload: dict, codes: set[str], since: datetime) -> list[dict]:
    items = []
    for row in ((payload or {}).get("items") or {}).get("data", []):
        try:
            published = datetime.fromtimestamp(int(row.get("publishAt")), tz=timezone.utc)
        except (TypeError, ValueError):
            continue
        if published < since:
            continue
        for code in [str(c) for c in row.get("stock") or [] if str(c) in codes]:
            items.append({"code": code, "name": "", "kind": "新聞", "title": _clean(row.get("title")),
                          "detail": _clean(row.get("summary"))[:300], "published": published,
                          "link": f"https://news.cnyes.com/news/id/{row.get('newsId')}"})
    return items


# Fund-holding filings rewritten as headlines ("$NVDA Shares Sold by X LLC") and similar filler.
_NOISE = re.compile(
    r"-\s*MarketBeat\s*$|\b(shares?|stock|stake|position|holdings?)\s+(sold|bought|purchased|acquired|raised|lowered|"
    r"trimmed|increased|decreased|cut|boosted|reduced)\s+by\b|\b(acquires|purchases|sells|buys|trims|boosts|lifts|"
    r"cuts|raises|lowers)\s+(new\s+)?(\d[\d,]*\s+)?(shares?|stake|position|holdings?)\b", re.I)


def google_news(xml_text: str, code: str, since: datetime) -> list[dict]:
    return [{"code": code, "name": "", "kind": "新聞", "title": item["title"], "detail": "",
             "published": item["published"], "link": item["link"]}
            for item in parse_feed(xml_text)
            if item["published"] and item["published"] >= since and not _NOISE.search(item["title"])]


def sec_8k(submissions: dict, code: str, since: datetime) -> list[dict]:
    recent = ((submissions or {}).get("filings") or {}).get("recent") or {}
    cik = str(int(str(submissions.get("cik") or "0")))
    items = []
    for index, form in enumerate(recent.get("form", [])):
        if form not in ("8-K", "8-K/A"):
            continue
        try:
            accepted = datetime.fromisoformat(recent["acceptanceDateTime"][index].replace("Z", "+00:00"))
        except (KeyError, IndexError, ValueError):
            continue
        if accepted < since:
            continue
        codes = [c.strip() for c in str((recent.get("items") or [""] * (index + 1))[index]).split(",") if c.strip()]
        meaning = "、".join(SEC_ITEMS[c] for c in codes if c in SEC_ITEMS) or "公告"
        accession = recent["accessionNumber"][index].replace("-", "")
        items.append({"code": code, "name": "", "kind": "公告", "title": f"SEC {form}：{meaning}",
                      "detail": f"items {', '.join(codes)}" if codes else "", "published": accepted,
                      "link": f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{recent['primaryDocument'][index]}"})
    return items


# ---------- schedule ----------

def due_session(now: datetime) -> tuple[str, date] | None:
    """('tw'|'us', local date) during the first 15 minutes after that market's 08:00 pre-open, weekdays only."""
    for session, (tz, start) in SESSIONS.items():
        local = now.astimezone(tz)
        begin = datetime.combine(local.date(), start, tz)
        if local.weekday() < 5 and begin <= local < begin + timedelta(minutes=15):
            return session, local.date()
    return None


# ---------- economic calendar preview ----------

EVENT_LABEL = {"cpi": "美國 CPI", "ppi": "美國 PPI", "employment": "美國非農就業", "claims": "美國初領失業金",
               "retail_sales": "零售銷售", "fed": "美國 FOMC 利率決策"}


def upcoming_events(events: list[dict], now: datetime, hours: int = 24) -> list[dict]:
    """Calendar rows (market_macro_db events) due within `hours`; one row per release even when two sources list it.
    Date-only rows count when their New York date falls in the window."""
    end = now + timedelta(hours=hours)
    chosen: dict[tuple, dict] = {}
    for event in events:
        at = event.get("scheduledAt")
        if at is not None:
            if not now <= at < end:
                continue
            identity = (event["groupId"], at) if event["groupId"] != "other" else (event["title"], at)
        else:
            day = event.get("scheduledDate")
            if not day or not now.astimezone(NY).date() <= day <= end.astimezone(NY).date():
                continue
            identity = (event["groupId"] if event["groupId"] != "other" else event["title"], day)
        current = chosen.get(identity)
        if current is None or (not current.get("consensusValue") and event.get("consensusValue")):
            chosen[identity] = event
    return sorted(chosen.values(), key=lambda e: (e.get("scheduledAt") or datetime.combine(e["scheduledDate"], time(23, 59), NY)))


def calendar_section(events: list[dict]) -> str:
    if not events:
        return "📅 未來 24 小時沒有排定的重大經濟數據。"
    lines = ["📅 未來 24 小時經濟數據（台北時間）："]
    for event in events:
        at = event.get("scheduledAt")
        when = at.astimezone(TPE).strftime("%m/%d %H:%M") if at else event["scheduledDate"].strftime("%m/%d") + " 時間未定"
        label = EVENT_LABEL.get(event["groupId"]) or event["title"]
        lines.append(f"・{when} {label}" + (f"（預期 {event['consensusValue']}）" if event.get("consensusValue") else ""))
    return "\n".join(lines)


def load_events(now: datetime) -> list[dict]:
    from ..databases.market_macro_db import MacroEvent, market_macro_db
    if not market_macro_db.sessions:
        return []
    today = now.astimezone(NY).date()
    with market_macro_db.sessions() as session:
        rows = session.query(MacroEvent).filter(MacroEvent.scheduled_date >= today - timedelta(days=1),
                                                MacroEvent.scheduled_date <= today + timedelta(days=2)).all()
        return [{"groupId": r.group_id, "title": r.title, "scheduledDate": r.scheduled_date,
                 "scheduledAt": r.scheduled_at, "consensusValue": r.consensus_value} for r in rows]


# ---------- summary ----------

def _limited(items: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for item in sorted(items, key=lambda i: (i["kind"] != "公告", -i["published"].timestamp())):
        bucket = grouped.setdefault(item["code"], [])
        if len(bucket) < MAX_ITEMS_PER_CODE and item["title"] not in {i["title"] for i in bucket}:
            bucket.append(item)
    return grouped


def _label(code: str, names: dict[str, str]) -> str:
    return f"{code} {names[code]}" if names.get(code) else code


def build_prompt(items: list[dict], names: dict[str, str]) -> str:
    lines = []
    for code, bucket in sorted(_limited(items).items()):
        lines.append(f"## {_label(code, names)}")
        for item in bucket:
            lines.append(f"- [{item['kind']}] {item['title']}" + (f"｜{item['detail']}" if item["detail"] else ""))
    return (
        "你是投資組合助理。只根據下面列出的公告與新聞，替每一檔寫一行繁體中文摘要。\n"
        "格式：「代碼 名稱：［利多／利空／中性］一到兩句重點」，每檔一行，依重要性排序，最重要的放最前面。\n"
        "只寫資料裡有的事實與數字，不要推測股價、不要給買賣建議、不要加入資料以外的知識。"
        "同一件事多則報導合併成一句。沒有實質內容的（例如股價漲跌評論、廣告）可以略過整檔。\n\n" + "\n".join(lines)
    )


def fallback_summary(items: list[dict], names: dict[str, str]) -> str:
    lines = []
    for code, bucket in sorted(_limited(items).items()):
        lines.append(f"{_label(code, names)}：" + "；".join(i["title"] for i in bucket[:3]))
    return "\n".join(lines)


def gemini_summary(prompt: str, key: str, client=None) -> str | None:
    import httpx
    own = client is None
    client = client or httpx.Client(timeout=60)
    try:
        response = client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": 0.2}})
        if response.status_code != 200:
            logger.warning("Gemini digest returned %s", response.status_code)
            return None
        parts = response.json()["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts).strip() or None
    except Exception as exc:
        logger.warning("Gemini digest failed: %s", type(exc).__name__)
        return None
    finally:
        if own:
            client.close()


def digest_title(session: str, count: int) -> str:
    return f"{SESSION_LABEL[session]}（{count} 則）"


def deliver(store, session: str, day: date, title: str, body: str, send: Callable | None = None,
            history: Callable | None = None) -> bool:
    key = f"news-digest:{session}"
    if not store.record(key, day, ""):
        return False
    if send is None:
        from . import telegram_notify
        send = telegram_notify.send
    if not send("news", title, body).get("sent"):
        store.release(key, day)
        return False
    try:
        if history is None:
            from ..databases.market_notification_db import market_notification_db
            history = lambda t, b: market_notification_db.add("update", t, b)
        history(title, body)
    except Exception:
        logger.exception("News digest bell copy failed")
    return True


# ---------- collection + loop ----------

def targets() -> tuple[set[str], set[str], dict[str, str]]:
    """(Taiwan codes, overseas US tickers, code -> name) from holdings, custom picks and the AI watch list."""
    from ..databases.market_dashboard_db import market_dashboard_db
    rows = market_dashboard_db.latest_auto()["positions"] + market_dashboard_db.custom_symbols() + market_dashboard_db.watch_symbols()
    taiwan, us, names = set(), set(), {}
    for row in rows:
        code = str(row.get("code") or "").strip().upper()
        market = str(row.get("market") or "TW").upper()
        if market == "TW" and re.fullmatch(r"\d{4}", code):
            taiwan.add(code)
        elif market == "US" and re.fullmatch(r"[A-Z][A-Z.]{0,5}", code):
            us.add(code)
        elif market not in ("TW", "", "UNKNOWN") and re.fullmatch(r"[A-Z0-9.]{1,8}", code):
            code = f"{code}-{market}"  # e.g. 6857-JP: same label the routines use, never mixed up with Taiwan 6857
            us.add(code)
        else:
            continue
        if row.get("name") and str(row["name"]).strip().upper() != code:
            names.setdefault(code, str(row["name"]).strip())
    return taiwan, us, names


async def collect(client, session: str, now: datetime) -> tuple[list[dict], dict[str, str]]:
    taiwan, us, names = await asyncio.to_thread(targets)
    since = now - LOOKBACK
    items: list[dict] = []

    async def safe(label, coro):
        try:
            return await coro
        except Exception as exc:
            logger.warning("News digest source %s failed: %s", label, type(exc).__name__)
            return []

    async def get_json(url, **kw):
        response = await client.get(url, **kw)
        response.raise_for_status()
        return response.json()

    if session == "tw" and taiwan:
        items += await safe("twse", _then(get_json(TWSE_URL), lambda rows: twse_announcements(rows, taiwan, since)))
        items += await safe("tpex", _then(get_json(TPEX_URL), lambda rows: tpex_announcements(rows, taiwan, since)))
        for page in (1, 2):
            items += await safe("cnyes", _then(get_json(f"{CNYES_URL}&page={page}"), lambda p: cnyes_news(p, taiwan, since)))
    if session == "us" and us:
        sec = {"headers": {"User-Agent": SEC_USER_AGENT}}  # SEC refuses browser-like agents
        ciks = await safe("sec-tickers", get_json(SEC_TICKERS_URL, **sec))
        cik_by_ticker = {str(v.get("ticker", "")).upper(): int(v["cik_str"]) for v in (ciks or {}).values()} if isinstance(ciks, dict) else {}
        for ticker in sorted(us):
            if ticker in cik_by_ticker:
                url = f"https://data.sec.gov/submissions/CIK{cik_by_ticker[ticker]:010d}.json"
                items += await safe("sec", _then(get_json(url, **sec), lambda s, t=ticker: sec_8k(s, t, since)))
            # Non-US listings (6857-JP) are found by company name; a bare number would match unrelated stories.
            query = quote(f"\"{names[ticker]}\"" if "-" in ticker and names.get(ticker)
                          else f"{ticker} {names.get(ticker, '')} stock".strip())
            url = f"https://news.google.com/rss/search?q={query}+when:1d&hl=en-US&gl=US&ceid=US:en"
            items += await safe("google", _then(client.get(url), lambda r, t=ticker: google_news(r.text, t, since)))
            await asyncio.sleep(0.2)  # SEC asks for at most 10 requests a second
    for item in items:
        if item.get("name"):
            names.setdefault(item["code"], item["name"])
    return items, names


async def _then(coro, fn):
    return fn(await coro)


async def run_session(store, session: str, day: date, now: datetime, client) -> bool:
    items, names = await collect(client, session, now)
    if not items:
        body = "過去 24 小時持股與觀察清單沒有新公告或新聞。"
    else:
        key = os.getenv("GEMINI_API_KEY", "").strip()
        summary = await asyncio.to_thread(gemini_summary, build_prompt(items, names), key) if key else None
        body = summary or ("（AI 摘要暫時無法使用，以下為標題）\n" + fallback_summary(items, names))
    try:
        calendar = calendar_section(upcoming_events(await asyncio.to_thread(load_events, now), now))
    except Exception:
        logger.exception("Economic calendar preview unavailable")
        calendar = "📅 經濟數據行事曆暫時讀不到。"
    body = f"{calendar}\n\n{body}"
    return await asyncio.to_thread(deliver, store, session, day, digest_title(session, len(items)), body)


class NewsDigestScheduler:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._attempted: set[tuple[str, date]] = set()

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        import httpx
        from .market_automation import automation_store
        store = await asyncio.to_thread(automation_store)
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 (maya-sawa news digest)"}) as client:
            while True:
                now = datetime.now(timezone.utc)
                due = due_session(now)
                if due and due not in self._attempted:  # one collection + Gemini call per session per pod
                    self._attempted.add(due)
                    try:
                        await run_session(store, due[0], due[1], now, client)
                    except Exception:
                        logger.exception("News digest %s failed", due[0])
                await asyncio.sleep(60)


news_digest_scheduler = NewsDigestScheduler()
