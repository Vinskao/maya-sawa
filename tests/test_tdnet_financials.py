"""Japan holdings' financials from TDnet 決算短信 XBRL (free, no key).

Fixtures are real TDnet downloads from 2026-10-15..20 (TDnet keeps about a month):
- jgaap_q2_24110: Japan GAAP interim (Q2 YTD) results with P&L / balance-sheet attachments
- ifrs_annual_92520: IFRS annual results (Advantest files IFRS)
- forecast_revision_79180: 業績予想の修正 with the previous and the revised forecast
- list_001_20261016: one page of the daily disclosure list
"""
import asyncio
from pathlib import Path

import pytest

from maya_sawa.services import tdnet_financials as td

FIXTURES = Path(__file__).parent / "fixtures" / "tdnet"


def fixture(name):
    return (FIXTURES / name).read_bytes()


def test_daily_list_rows_carry_the_five_digit_code_title_and_absolute_xbrl_link():
    rows, has_next = td.parse_list_page(fixture("list_001_20261016.html").decode("utf-8"))
    row = next(row for row in rows if row["code"] == "24110")
    assert "決算短信" in row["title"]
    assert row["zipUrl"] == "https://www.release.tdnet.info/inbs/081220261016552169.zip"
    assert has_next is True
    assert td.tdnet_code("6857") == "68570"


def test_japan_gaap_interim_results_in_yen_with_attachment_gross_profit():
    release = td.parse_release(fixture("jgaap_q2_24110_20261016.zip"))
    assert release["standard"] == "JGAAP"
    current = next(row for row in release["durations"] if (row["start"], row["end"]) == ("2026-04-01", "2026-09-30"))
    assert current["revenue"] == 3_645_000_000
    assert current["operatingIncome"] == 266_000_000
    assert current["netIncome"] == 154_000_000
    assert current["epsBasic"] == 14.02
    assert current["epsDiluted"] is None  # reported blank (xsi:nil), never copied from basic
    assert current["grossProfit"] == 1_384_000_000 and current["costOfRevenue"] == 2_260_000_000
    prior = next(row for row in release["durations"] if row["end"] == "2025-09-30")
    assert prior["revenue"] == 3_921_000_000 and prior["operatingIncome"] == 398_000_000
    sheet = next(row for row in release["instants"] if row["end"] == "2026-09-30")
    assert sheet["assets"] == 5_409_000_000 and sheet["equity"] == 3_884_000_000
    forecast = next(row for row in release["forecasts"] if row["end"] == "2027-03-31")
    assert forecast["revenue"] == 8_000_000_000 and forecast["operatingIncome"] == 800_000_000 and forecast["epsBasic"] == 47.27


def test_ifrs_annual_results_use_ifrs_tags_and_keep_signed_cash_flow():
    release = td.parse_release(fixture("ifrs_annual_92520_20261015.zip"))
    assert release["standard"] == "IFRS"
    year = max((row for row in release["durations"]), key=lambda row: row["end"])
    assert year["durationDays"] > 330
    assert year["revenue"] == pytest.approx(19_789_000_000, rel=1e-3)
    assert year["epsBasic"] == 467.41
    assert year["investingCashFlow"] < 0  # sign="-" on a displayed 334
    assert year["costOfRevenue"] == 5_003_993_000  # attachment in thousands beats the summary's millions
    sheet = max(release["instants"], key=lambda row: row["end"])
    assert sheet["equity"] == 5_553_437_000


def test_attachments_give_current_ratio_inventory_and_capex():
    # Values read from the fixtures' raw XBRL. IFRS tags inventory as InventoriesCAIFRS (Advantest files IFRS), and
    # "Purchase of property, plant and equipment" carries sign="-"; capex is stored positive like SEC and OpenDART.
    ifrs = td.parse_release(fixture("ifrs_annual_92520_20261015.zip"))
    sheet = max(ifrs["instants"], key=lambda row: row["end"])
    assert sheet["currentAssets"] == 6_855_247_000 and sheet["currentLiabilities"] == 4_734_279_000
    assert sheet["inventory"] == 43_221_000
    years = sorted((row for row in ifrs["durations"] if row["durationDays"] > 330), key=lambda row: row["end"])
    assert [row["capitalExpenditure"] for row in years] == [55_788_000, 33_173_000]
    jgaap = td.parse_release(fixture("jgaap_q2_24110_20261016.zip"))
    sheet = next(row for row in jgaap["instants"] if row["end"] == "2026-09-30")
    assert sheet["currentAssets"] == 4_076_000_000 and sheet["currentLiabilities"] == 934_000_000
    half = next(row for row in jgaap["durations"] if (row["start"], row["end"]) == ("2026-04-01", "2026-09-30"))
    assert half["capitalExpenditure"] == 36_000_000


def test_forecast_revision_keeps_only_the_revised_forecast():
    release = td.parse_release(fixture("forecast_revision_79180_20261020.zip"))
    assert all(row["end"] <= "2026-03-31" for row in release["durations"])  # only last year's actuals for comparison
    year = next(row for row in release["forecasts"] if row["end"] == "2027-03-31")
    assert year["revenue"] == 17_100_000_000  # 17,400 was the previous forecast
    assert year["operatingIncome"] == 520_000_000 and year["netIncome"] == 270_000_000


def _release(released, durations, instants=(), forecasts=()):
    return {"releasedAt": released, "standard": "IFRS", "durations": list(durations),
            "instants": list(instants), "forecasts": list(forecasts), "zipUrl": f"https://x/{released}.zip", "title": "t"}


def test_quarters_come_from_reported_three_months_or_the_difference_of_consecutive_ytd():
    q1 = {"start": "2026-04-01", "end": "2026-06-30", "durationDays": 90, "revenue": 100.0, "operatingIncome": 20.0,
          "grossProfit": 50.0, "netIncome": 10.0, "epsBasic": 5.0, "epsDiluted": None}
    h1 = {"start": "2026-04-01", "end": "2026-09-30", "durationDays": 182, "revenue": 260.0, "operatingIncome": 50.0,
          "grossProfit": 120.0, "netIncome": 30.0, "epsBasic": 14.0, "epsDiluted": None}
    data = td.build_financials([_release("2026-07-28", [q1]), _release("2026-10-28", [h1])])
    by_end = {row["end"]: row for row in data["quarterly"]}
    assert by_end["2026-06-30"]["revenue"] == 100.0 and not by_end["2026-06-30"].get("derivedFromYtd")
    q2 = by_end["2026-09-30"]
    assert q2["revenue"] == 160.0 and q2["operatingIncome"] == 30.0 and q2["derivedFromYtd"] is True
    assert q2["grossMarginPercent"] == 43.75 and q2["operatingMarginPercent"] == 18.75
    assert q2["epsBasic"] is None  # EPS is not additive across share-count changes
    assert [row["end"] for row in data["cumulative"]] == ["2026-09-30"]
    assert "TDnet" in data["source"]


def test_a_later_release_for_the_same_period_replaces_the_earlier_figures():
    first = {"start": "2026-04-01", "end": "2026-06-30", "durationDays": 90, "revenue": 100.0}
    corrected = {**first, "revenue": 101.0}
    data = td.build_financials([_release("2026-07-28", [first]), _release("2026-08-05", [corrected])])
    assert [row["revenue"] for row in data["quarterly"]] == [101.0]


class FakeDb:
    def __init__(self, codes):
        self.codes = codes
        self.rows = {}

    def market_codes(self, market, kind="profile"):
        return list(self.codes)

    def latest(self, code, market, kind, *, successful=True):
        return self.rows.get((code, market, kind, "latest"))

    def history(self, code, market, kind, limit=1000):
        return [row for (c, m, k, p), row in sorted(self.rows.items()) if (c, m, k) == (code, market, kind) and p != "latest"]

    def save(self, code, market, conid, kind, payload, *, period=None, status="ok"):
        row = {"payload": payload, "status": status, "period": period, "fetchedAt": "2026-10-20T00:00:00+00:00"}
        self.rows[(code, market, kind, "latest")] = row
        if period:
            self.rows[(code, market, kind, period)] = row


def test_collector_keeps_only_holdings_and_does_not_download_a_release_twice():
    list_html = fixture("list_001_20261016.html").decode("utf-8")
    zip_bytes = fixture("jgaap_q2_24110_20261016.zip")
    calls = []

    async def fetch(url):
        calls.append(url)
        if url.endswith("I_list_001_20261016.html"):
            return list_html.replace("I_list_002_20261016.html", "none.html").encode("utf-8")
        if url.endswith(".zip"):
            return zip_bytes
        raise RuntimeError("upstream_http_404")

    db = FakeDb(["2411"])
    saved = asyncio.run(td.collect(db, fetch, days=["2026-10-16"]))
    assert saved == 1
    cumulative = {row["end"]: row for row in db.latest("2411", "JP", "financials")["payload"]["cumulative"]}
    assert cumulative["2026-09-30"]["revenue"] == 3_645_000_000 and cumulative["2025-09-30"]["revenue"] == 3_921_000_000
    zip_calls = [url for url in calls if url.endswith(".zip")]
    assert zip_calls == ["https://www.release.tdnet.info/inbs/081220261016552169.zip"]
    calls.clear()
    assert asyncio.run(td.collect(db, fetch, days=["2026-10-16"])) == 0
    assert not [url for url in calls if url.endswith(".zip")]


def test_scan_days_backfill_a_month_once_then_only_recent_days():
    from datetime import date
    today = date(2026, 10, 20)
    first = td.scan_days(None, today)
    assert len(first) == 31 and first[0] == "2026-10-20" and first[-1] == "2026-09-20"
    # A restart soon after a scan revisits the last scanned day and two days before, not the whole month.
    assert td.scan_days("2026-10-20", today) == ["2026-10-20", "2026-10-19", "2026-10-18"]
    # After a week offline, catch up from the day before the last scan.
    assert td.scan_days("2026-10-10", today) == [f"2026-10-{d:02d}" for d in range(20, 8, -1)]


def test_japan_codes_are_the_holdings_ever_profiled_even_while_ib_is_logged_out():
    from sqlalchemy import create_engine
    from maya_sawa.databases.ibkr_research_db import IbkrResearchDatabase
    db = IbkrResearchDatabase(engine=create_engine("sqlite://"))
    db.save("6857", "JP", 1, "profile", {"con_id": 1})
    db.save("6524", "JP", 2, "profile", {"con_id": 2})
    db.save("9999", "JP", 3, "profile", {"reason": "x"}, status="unavailable")
    db.save("META", "US", 4, "profile", {"con_id": 4})
    assert db.market_codes("JP") == ["6524", "6857"]
