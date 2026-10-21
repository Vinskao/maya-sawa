"""Japan holdings' financial history from J-Quants /v2/fins/summary (JPX; key JQUANTS_API_KEY).

Fixtures are real responses fetched inside the pod on 2026-10-21 (free plan: two years, ending 12 weeks back):
Advantest 6857 (IFRS, March year end) and Kohoku Kogyo 6524 (Japan GAAP, December year end, with
EarnForecastRevision rows). Every field is a string and "" means no value.
"""
import asyncio
import json
from pathlib import Path

from maya_sawa.services import jquants_financials as jq
from maya_sawa.services import tdnet_financials as td

FIXTURES = Path(__file__).parent / "fixtures" / "jquants"


def records(code):
    return json.loads((FIXTURES / f"summary_{code}.json").read_text(encoding="utf-8"))["data"]


def test_a_first_quarter_summary_is_a_three_month_result_with_balance_sheet_and_guidance():
    q1 = next(r for r in records("6857") if r["DiscNo"] == "20260728500866")
    release = jq.parse_summary(q1)
    assert release["standard"] == "IFRS" and release["consolidated"] is True
    assert release["releasedAt"] == "2026-07-29T15:30" and release["releaseId"] == "20260728500866"
    (result,) = release["durations"]
    assert (result["start"], result["end"], result["durationDays"]) == ("2026-04-01", "2026-06-30", 90)
    assert result["revenue"] == 367_473_000_000 and result["operatingIncome"] == 189_990_000_000
    assert result["netIncome"] == 174_780_000_000 and result["epsBasic"] == 241.27 and result["epsDiluted"] == 239.89
    assert result["operatingCashFlow"] == 137_155_000_000 and result["investingCashFlow"] == -102_548_000_000
    assert result["grossProfit"] is None  # the summary has no gross profit; TDnet attachments do
    (sheet,) = release["instants"]
    assert sheet["end"] == "2026-06-30" and sheet["assets"] == 1_514_652_000_000 and sheet["cash"] == 413_124_000_000
    assert sheet["equity"] == 1_042_642_000_000  # Eq matches assets x equity ratio, so it is owners' equity
    year = next(f for f in release["forecasts"] if f["end"] == "2027-03-31")
    assert year["start"] == "2026-04-01" and year["revenue"] == 1_714_000_000_000 and year["epsBasic"] == 911.64


def test_japan_gaap_net_assets_with_minority_interests_fall_back_to_owners_equity_from_the_ratio():
    fy = next(r for r in records("6524") if r["DocType"].startswith("FY") and r["CurPerEn"] == "2025-12-31")
    release = jq.parse_summary(fy)
    assert release["standard"] == "JGAAP"
    (sheet,) = release["instants"]
    total, ratio, net_assets = float(fy["TA"]), float(fy["EqAR"]), float(fy["Eq"])
    expected = net_assets if abs(net_assets - total * ratio) <= total * 0.0005 else round(total * ratio)
    assert sheet["equity"] == expected
    (result,) = release["durations"]
    assert result["durationDays"] >= 330 and result["revenue"] == 17_454_000_000


def test_an_annual_summary_carries_next_years_guidance_not_this_years():
    fy = next(r for r in records("6857") if r["DiscNo"] == "20260427511547")
    release = jq.parse_summary(fy)
    (forecast,) = [f for f in release["forecasts"] if f["revenue"] is not None]
    assert (forecast["start"], forecast["end"]) == ("2026-04-01", "2027-03-31")
    assert forecast["revenue"] == 1_420_000_000_000 and forecast["netIncome"] == 465_500_000_000


def test_a_forecast_revision_has_only_forecasts():
    revision = [r for r in records("6524") if r["DocType"] == "EarnForecastRevision"][-1]
    release = jq.parse_summary(revision)
    assert release["durations"] == [] and release["instants"] == []
    half = next(f for f in release["forecasts"] if f["end"] == "2026-06-30")
    assert half["start"] == "2026-01-01" and half["revenue"] == 10_023_000_000 and half["epsBasic"] == 81.96


def test_dividend_only_and_reit_documents_are_skipped():
    assert jq.parse_summary({"DocType": "DividendForecastRevision"}) is None
    assert jq.parse_summary({"DocType": "REITEarnForecastRevision"}) is None


def test_two_years_of_summaries_give_quarters_from_reported_q1_and_ytd_differences():
    releases = [jq.parse_summary(r) for r in records("6857")]
    data = td.build_financials([r for r in releases if r])
    by_end = {row["end"]: row for row in data["quarterly"]}
    assert by_end["2026-06-30"]["revenue"] == 367_473_000_000 and not by_end["2026-06-30"].get("derivedFromYtd")
    q4 = by_end["2026-03-31"]  # FY 1,128,610 minus 9M 800,537 (millions of yen)
    assert q4["derivedFromYtd"] and q4["revenue"] == 328_073_000_000
    assert len(data["quarterly"]) == 9  # 2024Q1 (Apr-Jun 2024) .. 2026Q1


def test_tdnet_fills_metrics_the_summary_lacks_and_the_summary_keeps_what_tdnet_left_blank():
    summary = {"releasedAt": "2026-07-29T15:30", "precedence": 0, "durations": [
        {"start": "2026-04-01", "end": "2026-06-30", "durationDays": 90, "revenue": 100.0, "grossProfit": None, "operatingCashFlow": 7.0}]}
    tdnet = {"releasedAt": "2026-07-29T15:30", "precedence": 1, "durations": [
        {"start": "2026-04-01", "end": "2026-06-30", "durationDays": 90, "revenue": 100.5, "grossProfit": 40.0, "operatingCashFlow": None}]}
    for order in ([summary, tdnet], [tdnet, summary]):
        (quarter,) = td.build_financials(order)["quarterly"]
        assert quarter["revenue"] == 100.5 and quarter["grossProfit"] == 40.0 and quarter["operatingCashFlow"] == 7.0


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
        row = {"payload": payload, "status": status, "period": period, "fetchedAt": "2026-10-21T00:00:00+00:00"}
        self.rows[(code, market, kind, "latest")] = row
        if period:
            self.rows[(code, market, kind, period)] = row


def test_a_new_japan_holding_gets_its_history_on_the_first_pass_and_nothing_twice():
    pages = {"6857": [{"data": records("6857")[:5], "pagination_key": "p2"}, {"data": records("6857")[5:]}]}
    calls = []

    async def fetch(params):
        calls.append(dict(params))
        return pages[params["code"]][1 if params.get("pagination_key") else 0]

    db = FakeDb(["6857"])
    assert asyncio.run(jq.collect(db, fetch)) == 9
    assert calls == [{"code": "6857"}, {"code": "6857", "pagination_key": "p2"}]
    financials = db.latest("6857", "JP", "financials")["payload"]
    assert len(financials["quarterly"]) == 9 and "J-Quants" in financials["source"]
    calls.clear()
    assert asyncio.run(jq.collect(db, fetch)) == 0


def test_tdnet_rebuild_keeps_the_j_quants_history():
    db = FakeDb(["6857"])
    for record in records("6857"):
        db.save("6857", "JP", 0, "jquants_release", jq.parse_summary(record), period=record["DiscNo"])
    td.rebuild_japan(db, "6857", 0)
    assert len(db.latest("6857", "JP", "financials")["payload"]["quarterly"]) == 9
