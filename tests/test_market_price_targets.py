"""Broker target prices: Yahoo Finance per-broker actions (US) and consensus (all markets), plus AI-routine records."""
import asyncio
import json
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from maya_sawa.databases.market_price_target_db import MarketPriceTargetDatabase
from maya_sawa.services import market_price_targets as targets


def fixture(name):
    return json.loads((Path(__file__).parent / "fixtures" / name).read_text(encoding="utf-8"))


def test_us_payload_gives_each_broker_action_and_the_consensus():
    parsed = targets.parse_yahoo_targets(fixture("yahoo_targets_LITE.json"))
    assert parsed["consensus"] == {"mean": 1165.0314, "median": 1200.0, "high": 1500.0, "low": 750.0,
                                   "analysts": 27, "currency": "USD"}
    first = parsed["actions"][0]
    # epochGradeDate 1792599480 is 2026-10-21 12:18 New York (already 10-22 in Taipei): the broker's own date.
    assert first == {"firm": "Jefferies", "date": "2026-10-21", "action": "Raises", "rating": "Buy",
                     "previousRating": "Buy", "target": 1250.0, "previousTarget": 1200.0}
    bernstein = next(row for row in parsed["actions"] if row["firm"] == "Bernstein")
    assert bernstein["previousTarget"] is None and bernstein["previousRating"] is None  # 0.0 / '' mean "none"
    wolfe = next(row for row in parsed["actions"] if row["firm"] == "Wolfe Research")
    assert wolfe["target"] is None and wolfe["rating"] == "Outperform"  # a rating without a target is still kept


def test_taiwan_payload_has_only_a_consensus():
    parsed = targets.parse_yahoo_targets(fixture("yahoo_targets_2330TW.json"))
    assert parsed["actions"] == []
    assert parsed["consensus"]["mean"] == 3390.4285 and parsed["consensus"]["currency"] == "TWD"
    assert targets.parse_yahoo_targets({}) == {"consensus": None, "actions": []}
    assert targets.parse_yahoo_targets({"quoteSummary": {"result": None, "error": {"code": "Not Found"}}})["consensus"] is None


def test_yahoo_symbols_by_market():
    assert targets.yahoo_symbols("2330", "TW") == ["2330.TW", "2330.TWO"]  # TPEx stocks use .TWO
    assert targets.yahoo_symbols("6857", "JP") == ["6857.T"]
    assert targets.yahoo_symbols("000660", "KR") == ["000660.KS", "000660.KQ"]
    assert targets.yahoo_symbols("BRK.B", "US") == ["BRK-B"]
    assert targets.yahoo_symbols("TXFK6", "TW") == []  # futures have no analyst targets


@pytest.fixture
def db(tmp_path):
    return MarketPriceTargetDatabase(create_engine(f"sqlite:///{tmp_path / 'targets.db'}"))


def test_actions_and_daily_consensus_are_stored_once_and_read_in_date_order(db):
    parsed = targets.parse_yahoo_targets(fixture("yahoo_targets_LITE.json"))
    for _ in range(2):  # the daily pass sees the same history again
        db.save_actions("LITE", "US", "USD", parsed["actions"], source="yahoo", source_url="https://finance.yahoo.com/quote/LITE")
        db.save_consensus("LITE", "US", date(2026, 10, 25), parsed["consensus"], source="yahoo")
    db.save_consensus("LITE", "US", date(2026, 10, 25), {**parsed["consensus"], "mean": 1170.0}, source="yahoo")
    data = db.read("LITE", "US")
    assert len(data["actions"]) == len(parsed["actions"])
    assert [row["date"] for row in data["actions"]] == sorted(row["date"] for row in data["actions"])
    assert data["consensus"] == [{"date": "2026-10-25", "mean": 1170.0, "median": 1200.0, "high": 1500.0, "low": 750.0,
                                  "analysts": 27, "currency": "USD", "source": "yahoo"}]
    assert data["actions"][-1]["source"] == "yahoo" and data["actions"][-1]["currency"] == "USD"
    assert db.read("2330", "TW") == {"actions": [], "consensus": []}


def test_collector_falls_back_to_tpex_symbol_and_one_failure_does_not_stop_the_rest(db):
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        if symbol == "3081.TW":
            return {"quoteSummary": {"result": None, "error": {"code": "Not Found"}}}
        if symbol == "6857.T":
            raise TimeoutError("yahoo slow")
        return fixture("yahoo_targets_2330TW.json") if symbol == "3081.TWO" else fixture("yahoo_targets_LITE.json")

    instruments = [{"code": "3081", "market": "TW", "productType": "stock"}, {"code": "6857", "market": "JP", "productType": "stock"},
                   {"code": "LITE", "market": "US", "productType": "stock"}, {"code": "TXFK6", "market": "TW", "productType": "futures"}]
    result = targets.collect(db, instruments, fetch, date(2026, 10, 25))
    assert calls == ["3081.TW", "3081.TWO", "6857.T", "LITE"]
    assert result == {"3081": "ok", "6857": "error", "LITE": "ok"}
    assert db.read("3081", "TW")["consensus"][0]["mean"] == 3390.4285
    assert len(db.read("LITE", "US")["actions"]) == 7


def test_ai_routine_records_need_a_source_and_a_real_target(db):
    row = {"firm": "凱基投顧", "date": "2026-10-20", "rating": "買進", "target": 3600, "sourceUrl": "https://news.cnyes.com/x"}
    assert targets.validate_routine_actions([row], today=date(2026, 10, 25)) == [
        {"firm": "凱基投顧", "date": "2026-10-20", "action": None, "rating": "買進", "previousRating": None,
         "target": 3600.0, "previousTarget": None, "sourceUrl": "https://news.cnyes.com/x", "thesis": None, "reportId": None}]
    for bad in [{**row, "sourceUrl": ""}, {**row, "sourceUrl": "ftp://x"}, {**row, "target": 0}, {**row, "target": "高"},
                {**row, "date": "2026-10-26"}, {**row, "date": "20261020"}, {**row, "firm": " "}]:
        with pytest.raises(ValueError):
            targets.validate_routine_actions([bad], today=date(2026, 10, 25))


def test_api_reads_targets_and_only_the_owner_or_agent_key_writes(db, monkeypatch):
    from maya_sawa.api import market
    monkeypatch.setattr(market, "market_price_target_db", db)
    monkeypatch.setenv("MARKET_AGENT_KEY_SHA256", __import__("hashlib").sha256(b"agent-key").hexdigest())
    app = FastAPI()
    app.include_router(market.router)
    client = TestClient(app)
    body = {"actions": [{"firm": "元大投顧", "date": "2026-10-21", "rating": "買進", "target": 3500,
                         "sourceUrl": "https://money.udn.com/x"}]}
    assert client.put("/market/dashboard/targets/2330?market=TW", json=body).status_code == 401
    saved = client.put("/market/dashboard/targets/2330?market=TW", json=body, headers={"X-Market-Agent-Key": "agent-key"})
    assert saved.status_code == 200 and saved.json()["saved"] == 1
    bad = {"actions": [{**body["actions"][0], "sourceUrl": ""}]}
    assert client.put("/market/dashboard/targets/2330?market=TW", json=bad, headers={"X-Market-Agent-Key": "agent-key"}).status_code == 422
    data = client.get("/market/dashboard/targets/2330?market=TW").json()
    assert data["actions"][0]["firm"] == "元大投顧" and data["actions"][0]["source"] == "ai-routine"
    assert data["actions"][0]["currency"] == "TWD" and data["actions"][0]["sourceUrl"] == "https://money.udn.com/x"
    assert client.get("/market/dashboard/targets/2330?market=XX").status_code == 422


# 2026-10-27: views linked to the target timeline. A target row can carry the broker's reasoning (thesis) and the
# report it came from (reportId); GET adds the public report claims for the stock as dated "views".
REPORT_ID = "83c3ca86-f9c7-49f3-bd30-81060c4c24a0"


def test_routine_targets_may_carry_the_reasoning_and_the_source_report(db):
    row = {"firm": "凱基投顧", "date": "2026-10-20", "target": 3600, "sourceUrl": "https://news.cnyes.com/x",
           "thesis": "  800G 光收發訂單能見度到 2027 年上半，上修 2026 年 EPS。 ", "reportId": REPORT_ID}
    clean = targets.validate_routine_actions([row], today=date(2026, 10, 25))[0]
    assert clean["thesis"] == "800G 光收發訂單能見度到 2027 年上半，上修 2026 年 EPS。" and clean["reportId"] == REPORT_ID
    assert targets.validate_routine_actions([{**row, "thesis": " ", "reportId": None}], today=date(2026, 10, 25))[0]["thesis"] is None
    for bad in [{**row, "thesis": "x" * 301}, {**row, "reportId": "../etc/passwd"}]:
        with pytest.raises(ValueError):
            targets.validate_routine_actions([bad], today=date(2026, 10, 25))
    db.save_actions("3081", "TW", "TWD", [clean], source="ai-routine")
    stored = db.read("3081", "TW")["actions"][0]
    assert stored["thesis"].startswith("800G") and stored["reportId"] == REPORT_ID


class StubReports:
    def __init__(self, claims, fail=False):
        self.claims, self.fail, self.asked = claims, fail, []

    def list_claims(self, code=None, segment=None, since=None):
        self.asked.append(code)
        if self.fail:
            raise RuntimeError("Market reports database unavailable")
        return [claim for claim in self.claims if code in claim["codes"]]


def claim(codes, page, published_at=None, as_of=None, direction="tailwind"):
    return {"report_id": REPORT_ID, "title": "光通訊產業報告", "publisher": "凱基投顧", "published_at": published_at,
            "page": page, "segment": "optics", "codes": codes, "dimension": "delivery", "direction": direction,
            "claim": f"第 {page} 頁主張", "evidence": "出貨季增 30%", "as_of": as_of, "received_at": "2026-10-20T05:35:13.559+00:00", "source_url": f"https://t.me/chan/{page}"}


def test_get_targets_adds_public_report_views_dated_and_deduplicated(db, monkeypatch):
    from maya_sawa.api import market
    monkeypatch.setattr(market, "market_price_target_db", db)
    reports = StubReports([claim(["LITE-US"], 3, published_at="2026-10-21"), claim(["LITE", "LITE-US"], 5, as_of="2026-10-15"),
                           claim(["3081"], 7, published_at="2026-10-01")])
    monkeypatch.setattr(market, "market_reports_db", reports)
    app = FastAPI()
    app.include_router(market.router)
    client = TestClient(app)
    views = client.get("/market/dashboard/targets/lite?market=US").json()["views"]
    assert reports.asked == ["LITE-US", "LITE"]  # overseas claims use CODE-MARKET, some reports use the bare ticker
    assert [(view["page"], view["date"]) for view in views] == [(3, "2026-10-21"), (5, "2026-10-15")]  # newest first, once each
    assert views[0] == {"reportId": REPORT_ID, "title": "光通訊產業報告", "publisher": "凱基投顧", "date": "2026-10-21", "dateKind": "published", "sourceUrl": "https://t.me/chan/3",
                        "page": 3, "dimension": "delivery", "direction": "tailwind", "claim": "第 3 頁主張", "evidence": "出貨季增 30%"}
    assert views[1]["dateKind"] == "data"  # no publication date: the claim's data cut-off date
    reports.asked.clear()
    assert [view["page"] for view in client.get("/market/dashboard/targets/3081?market=TW").json()["views"]] == [7]
    assert reports.asked == ["3081"]
    monkeypatch.setattr(market, "market_reports_db", StubReports([], fail=True))
    response = client.get("/market/dashboard/targets/3081?market=TW")
    assert response.status_code == 200 and response.json()["views"] == []  # targets still load without the report library


def test_stock_futures_are_collected_through_their_underlying_stock_once(db):
    # 2026-10-27: 2330, 3008, 3017, 3105 and 3324 are held as stock futures (QFFK6, OLFK6, ...), whose rows carry
    # underlyingCode; the collector skipped every futures row, so those stocks had no consensus at all.
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return fixture("yahoo_targets_2330TW.json")

    instruments = [{"code": "QFFK6", "market": "TW", "productType": "futures", "underlyingCode": "2330"},
                   {"code": "2330", "market": "TW", "productType": "stock"},  # also held directly: fetched once
                   {"code": "OLFK6", "market": "TW", "productType": "futures", "underlyingCode": "3008"},
                   {"code": "TXFK6", "market": "TW", "productType": "futures"}]  # index futures: no stock, skipped
    result = targets.collect(db, instruments, fetch, date(2026, 10, 27))
    assert calls == ["2330.TW", "3008.TW"]
    assert result == {"2330": "ok", "3008": "ok"}
    assert db.read("2330", "TW")["consensus"] and db.read("3008", "TW")["consensus"]
    assert db.read("QFFK6", "TW")["consensus"] == []


def test_a_report_without_dates_is_dated_by_when_it_was_recorded(monkeypatch):
    # 2026-10-27: the one library report has neither a publication date nor claim data dates, so its views never reached
    # the timeline. They now carry the day the report was saved to the database, marked as such.
    from maya_sawa.api import market
    monkeypatch.setattr(market, "market_reports_db", StubReports([claim(["3081"], 7)]))
    views = market.report_views("3081", "TW")
    assert [(view["date"], view["dateKind"]) for view in views] == [("2026-10-20", "recorded")]
