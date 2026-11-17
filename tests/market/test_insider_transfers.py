"""2026-11-17: insiders' pre-filed share transfers (TWSE t187ap12_L / TPEx mopsfin_t187ap12_O), so a stock shows "insider selling"."""
import json
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine

from maya_sawa.databases.insider_transfer_db import InsiderTransferDatabase
from maya_sawa.services import market_insider_transfers as it

FIXTURES = Path(__file__).parents[1] / "fixtures/market"
TWSE = json.loads((FIXTURES / "insider_transfer_twse.json").read_text(encoding="utf-8"))
TPEX = json.loads((FIXTURES / "insider_transfer_tpex.json").read_text(encoding="utf-8"))


def filings():
    return it.parse_filings(TWSE, "TWSE") + it.parse_filings(TPEX, "TPEx")


def test_roc_dates_and_the_transfer_window_become_iso_dates():
    assert it.roc_date("1151116") == date(2026, 11, 16)
    assert it.transfer_window("1151119~1151218") == (date(2026, 11, 19), date(2026, 12, 18))
    assert it.roc_date("") is None and it.transfer_window("bad") == (None, None)


def test_both_markets_parse_to_one_shape_with_planned_shares_and_holder():
    rows = {(row["code"], row["holder"]): row for row in filings()}
    row = rows[("1734", "郭修吉")]
    assert row["market"] == "TWSE" and row["name"] == "杏輝" and row["role"] == "法人董事代表人本人"
    assert row["method"] == "盤後定價交易" and row["shares"] == 173000 and row["held"] == 767681
    assert (row["filed"], row["start"], row["end"]) == (date(2026, 11, 16), date(2026, 11, 19), date(2026, 12, 18))
    otc = rows[("2743", "富仲投資有限公司")]
    assert otc["market"] == "TPEx" and otc["role"] == "大股東本人" and otc["shares"] == 1500000


def test_only_market_transfers_count_as_selling_gifts_and_trusts_do_not():
    sale = {row["code"]: row["sale"] for row in filings()}
    assert sale["1734"] and sale["2883"] and sale["2743"]     # 盤後定價、一般交易、鉅額逐筆
    assert not sale["1711"] and not sale["4114"]              # 贈與、信託


def test_a_stock_is_flagged_while_a_sale_window_is_open_or_about_to_open():
    events = it.insider_events(filings(), {"1734", "2883", "1711", "9999"}, today=date(2026, 11, 20))
    by_code = {event["code"]: event for event in events}
    assert set(by_code) == {"1734", "2883"}                   # the gift window closed on 11/18; 9999 has no filing
    event = by_code["1734"]
    assert event["type"] == "insider_transfer" and event["status"] == "active" and event["highlight"]
    assert event["date"] == "2026-11-19" and "173,000" in event["period"] and "盤後定價交易" in event["period"]
    early = it.insider_events(filings(), {"1734"}, today=date(2026, 11, 17))
    assert early[0]["status"] == "upcoming"
    assert it.insider_events(filings(), {"1734"}, today=date(2026, 12, 19)) == []


def test_several_filers_of_one_stock_become_one_event_with_the_total():
    rows = it.parse_filings(TWSE, "TWSE")
    twin = dict(rows[1], holder="另一位董事", shares=27000)
    events = it.insider_events([rows[1], twin], {"1734"}, today=date(2026, 11, 20))
    assert len(events) == 1 and "200,000" in events[0]["period"] and "2 位" in events[0]["period"]


def test_filings_are_kept_across_days_and_reading_again_does_not_duplicate():
    db = InsiderTransferDatabase(create_engine("sqlite://"))
    db.save(filings())
    db.save(filings())
    stored = db.open_on(date(2026, 11, 20))
    assert len(stored) == len([row for row in filings() if row["end"] >= date(2026, 11, 20)])
    assert db.open_on(date(2026, 12, 19)) == []


def test_collector_reads_both_markets_once_and_stores_them(monkeypatch):
    payloads = {it.TWSE_URL: TWSE, it.TPEX_URL: TPEX}
    monkeypatch.setattr(it, "fetch_json", lambda url: payloads[url])
    saved = []
    assert it.collect(saved.extend) == len(filings())
    assert {row["market"] for row in saved} == {"TWSE", "TPEx"}


def test_company_events_include_open_insider_sales_for_the_selected_stocks(monkeypatch):
    import asyncio
    from maya_sawa.services import market_company_events as mce

    service = mce.MarketCompanyEventsService()
    async def none(*a, **k): return []
    monkeypatch.setattr(mce.market_fundamentals_service, "published_events", none)
    monkeypatch.setattr(service, "_conferences", none)
    service.insider_source = lambda day: filings()
    monkeypatch.setattr(mce, "_today", lambda: date(2026, 11, 20))
    result = asyncio.run(service.get(["1734", "2330"]))
    assert [(event["code"], event["type"]) for event in result["events"]] == [("1734", "insider_transfer")]
    assert result["sources"]["insiderTransfers"].startswith("TWSE")


# --- 2026-11-17: untransferred filings (t187ap13) and month-over-month insider holdings (t187ap11) ----------------------
UNTRANSFERRED = json.loads((FIXTURES / "insider_untransferred_twse.json").read_text(encoding="utf-8"))
UNTRANSFERRED_OTC = json.loads((FIXTURES / "insider_untransferred_tpex.json").read_text(encoding="utf-8"))
HOLDINGS = json.loads((FIXTURES / "insider_holdings_twse.json").read_text(encoding="utf-8"))


def test_untransferred_filings_keep_shares_reason_and_skip_the_blank_otc_row():
    rows = it.parse_untransferred(UNTRANSFERRED, "TWSE") + it.parse_untransferred(UNTRANSFERRED_OTC, "TPEx")
    assert rows == [{"market": "TWSE", "code": "2313", "name": "華通", "role": "經理人本人", "holder": "吳柏毅",
                     "shares": 600000, "planned": 600000, "reason": "股價不理想", "filed": date(2026, 11, 16)}]


def test_an_untransferred_filing_is_shown_for_two_weeks():
    rows = it.parse_untransferred(UNTRANSFERRED, "TWSE")
    event = it.untransferred_events(rows, {"2313"}, today=date(2026, 11, 20))[0]
    assert event["type"] == "insider_untransferred" and event["status"] == "recent"
    assert "未轉讓 600,000 股" in event["period"] and "股價不理想" in event["period"]
    assert it.untransferred_events(rows, {"2313"}, today=date(2026, 12, 1)) == []


def test_holdings_are_summed_per_person_once_even_with_several_titles():
    month, snapshot = it.parse_holdings(HOLDINGS)
    assert month == "2026-10"
    people = snapshot["1101"]["persons"]
    assert people["張安平"] == 4624351                        # 法人代表人 and 總經理: one person, counted once
    assert people["嘉新水泥股份有限公司"] == 279426776        # two board seats, one holder
    assert snapshot["1101"]["name"] == "台泥" and "2330" in snapshot


def _with(snapshot, code, changes):
    copy = json.loads(json.dumps(snapshot))
    for person, shares in changes.items():
        copy[code]["persons"][person] = shares
    return copy


def test_a_rise_by_some_insiders_is_a_buy_and_new_or_departed_insiders_do_not_count():
    _, previous = it.parse_holdings(HOLDINGS)
    current = _with(previous, "1101", {"張安平": 4624351 + 300000, "新任董事": 9_000_000})
    del current["1101"]["persons"]["陳振源"]
    change = it.holding_changes(previous, current)["1101"]
    assert change["net"] == 300000 and change["increased"] == 1 and not change["uniform"]
    assert "2330" not in it.holding_changes(previous, previous)   # nothing moved, nothing recorded


def test_a_uniform_rise_for_every_holder_looks_like_a_stock_dividend_not_a_buy():
    _, previous = it.parse_holdings(HOLDINGS)
    current = json.loads(json.dumps(previous))
    for person, shares in current["1101"]["persons"].items():
        current["1101"]["persons"][person] = round(shares * 1.05)
    change = it.holding_changes(previous, current)["1101"]
    assert change["uniform"]
    assert it.holding_events([{"market": "TWSE", "code": "1101", "month": "2026-10", **change}], {"1101"}) == []


def test_a_net_buy_of_ten_lots_or_more_is_marked_with_the_month():
    change = {"market": "TWSE", "code": "1101", "name": "台泥", "month": "2026-10", "net": 300000, "increased": 1,
              "compared": 40, "uniform": False}
    event = it.holding_events([change], {"1101", "2330"})[0]
    assert event["type"] == "insider_buy" and event["highlight"] and "增加 300,000 股" in event["period"]
    assert "2026-10" in event["period"]
    assert it.holding_events([dict(change, net=9000)], {"1101"}) == []        # under ten lots
    assert it.holding_events([dict(change, net=-500000)], {"1101"}) == []     # a net sale is not a buy


def test_holdings_are_compared_only_when_a_new_month_arrives():
    db = InsiderTransferDatabase(create_engine("sqlite://"))
    month, snapshot = it.parse_holdings(HOLDINGS)
    assert it.store_holdings(db, "TWSE", "2026-09", snapshot) == 0          # first month: nothing to compare with
    bought = _with(snapshot, "1101", {"張安平": 4624351 + 300000})
    assert it.store_holdings(db, "TWSE", "2026-10", bought) == 1
    assert it.store_holdings(db, "TWSE", "2026-10", bought) == 0            # same month again: skipped
    assert [(row["code"], row["net"]) for row in db.latest_changes()] == [("1101", 300000)]


def test_company_events_add_untransferred_filings_and_insider_buys(monkeypatch):
    import asyncio
    from maya_sawa.services import market_company_events as mce

    service = mce.MarketCompanyEventsService()
    async def none(*a, **k): return []
    monkeypatch.setattr(mce.market_fundamentals_service, "published_events", none)
    monkeypatch.setattr(service, "_conferences", none)
    monkeypatch.setattr(mce, "_today", lambda: date(2026, 11, 20))
    service.insider_source = lambda day: []
    buy = {"market": "TWSE", "code": "1101", "name": "台泥", "month": "2026-10", "net": 300000, "increased": 1, "compared": 40, "uniform": False}
    service.insider_extra_source = lambda day: (it.parse_untransferred(UNTRANSFERRED, "TWSE"), [buy])
    result = asyncio.run(service.get(["2313", "1101"]))
    assert sorted((event["code"], event["type"]) for event in result["events"]) == [("1101", "insider_buy"), ("2313", "insider_untransferred")]
