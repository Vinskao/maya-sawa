"""Korea holdings' financials from OpenDART (金融監督院; free key in OPENDART_API_KEY).

Fixtures are real OpenDART responses for SK hynix (000660, corp_code 00164779) fetched 2026-10-20 inside the
production pod, trimmed to the accounts used: 2025 Q3 (11014) and annual (11011), 2026 Q1 (11013) and half-year
(11012), plus the periodic-filing list. No response contains the key.
"""
import asyncio
import io
import json
import zipfile
from datetime import date
from pathlib import Path

from maya_sawa.services import dart_financials as dart

FIXTURES = Path(__file__).parent / "fixtures" / "opendart"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_corp_code_comes_from_the_stock_code_in_the_corp_code_archive():
    xml = (FIXTURES / "corp_code_000660.xml").read_bytes()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("CORPCODE.xml", xml)
    assert dart.corp_codes(archive.getvalue()) == {"000660": "00164779"}


def test_filing_list_maps_report_names_to_periods_and_report_codes():
    filings = dart.periodic_filings(load("sk_hynix_list.json"))
    by_end = {item["periodEnd"]: item for item in filings}
    assert by_end["2026-06"]["reprtCode"] == "11012" and by_end["2026-06"]["filedOn"] == "2026-08-14"
    assert by_end["2026-03"]["reprtCode"] == "11013"
    assert by_end["2025-12"]["reprtCode"] == "11011" and by_end["2025-12"]["bsnsYear"] == "2025"
    assert by_end["2025-09"]["reprtCode"] == "11014"


def test_half_year_report_gives_the_single_quarter_the_year_to_date_and_last_year():
    release = dart.parse_statement(load("sk_hynix_2026_11012.json"), period_end="2026-06", fiscal_year_end_month=12)
    by_period = {(row["start"], row["end"]): row for row in release["durations"]}
    q2 = by_period[("2026-04-01", "2026-06-30")]
    assert q2["revenue"] == 79_318_746_000_000 and q2["operatingIncome"] == 60_542_608_000_000
    assert q2["grossProfit"] == 65_991_356_000_000 and q2["costOfRevenue"] == 13_327_390_000_000
    assert q2["netIncome"] == 93_820_236_000_000
    assert q2["epsBasic"] == 132_126 and q2["epsDiluted"] == 131_478
    assert by_period[("2026-01-01", "2026-06-30")]["revenue"] == 131_895_033_000_000
    assert by_period[("2025-04-01", "2025-06-30")]["revenue"] == 22_231_952_000_000
    assert by_period[("2025-01-01", "2025-06-30")]["revenue"] == 39_871_093_000_000
    ytd = by_period[("2026-01-01", "2026-06-30")]
    assert ytd["operatingCashFlow"] == 91_742_501_000_000 and ytd["investingCashFlow"] == -73_023_629_000_000
    assert ytd["capitalExpenditure"] == 18_328_836_000_000
    sheet = {row["end"]: row for row in release["instants"]}
    assert sheet["2026-06-30"]["inventory"] == 17_985_706_000_000
    assert sheet["2026-06-30"]["equity"] == 262_380_610_000_000
    assert sheet["2026-06-30"]["currentAssets"] == 156_155_954_000_000
    assert sheet["2025-12-31"]["assets"] == 176_107_659_000_000


def test_annual_report_is_a_full_year_and_the_fourth_quarter_is_derived_from_the_third_quarter_ytd():
    q3 = dart.parse_statement(load("sk_hynix_2025_11014.json"), period_end="2025-09", fiscal_year_end_month=12)
    year = dart.parse_statement(load("sk_hynix_2025_11011.json"), period_end="2025-12", fiscal_year_end_month=12)
    full = next(row for row in year["durations"] if (row["start"], row["end"]) == ("2025-01-01", "2025-12-31"))
    assert full["revenue"] == 97_146_675_000_000 and full["epsBasic"] == 62_044
    data = dart.build_financials([{**q3, "releasedAt": "2025-11-14"}, {**year, "releasedAt": "2026-03-17"}])
    q4 = next(row for row in data["quarterly"] if row["end"] == "2025-12-31")
    assert q4["revenue"] == 97_146_675_000_000 - 64_320_022_000_000 and q4["derivedFromYtd"] is True
    assert data["source"].startswith("OpenDART") and data["quarterly"][0]["currency"] == "KRW"


def test_a_reported_quarter_wins_over_the_same_quarter_derived_from_ytd():
    q1 = dart.parse_statement(load("sk_hynix_2026_11013.json"), period_end="2026-03", fiscal_year_end_month=12)
    h1 = dart.parse_statement(load("sk_hynix_2026_11012.json"), period_end="2026-06", fiscal_year_end_month=12)
    data = dart.build_financials([{**q1, "releasedAt": "2026-05-15"}, {**h1, "releasedAt": "2026-08-14"}])
    q2 = [row for row in data["quarterly"] if row["end"] == "2026-06-30"]
    assert len(q2) == 1 and not q2[0].get("derivedFromYtd")
    assert q2[0]["epsBasic"] == 132_126  # reported quarters keep EPS


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


def test_collector_stores_each_filing_once_and_never_puts_the_key_in_what_it_saves():
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("CORPCODE.xml", (FIXTURES / "corp_code_000660.xml").read_bytes())
    statements = {("2026", "11012"): "sk_hynix_2026_11012.json", ("2026", "11013"): "sk_hynix_2026_11013.json",
                  ("2025", "11011"): "sk_hynix_2025_11011.json", ("2025", "11014"): "sk_hynix_2025_11014.json"}
    calls = []

    async def fetch(path, params):
        calls.append((path, dict(params)))
        if path == "corpCode.xml":
            return archive.getvalue()
        if path == "list.json":
            return (FIXTURES / "sk_hynix_list.json").read_bytes()
        name = statements.get((params["bsns_year"], params["reprt_code"]))
        return (FIXTURES / name).read_bytes() if name else json.dumps({"status": "013", "message": "no data"}).encode()

    db = FakeDb(["000660"])
    saved = asyncio.run(dart.collect(db, fetch, today=date(2026, 10, 20)))
    assert saved == 4
    data = db.latest("000660", "KR", "financials")["payload"]
    ends = [row["end"] for row in data["quarterly"]]
    assert {"2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"} <= set(ends)
    assert "crtfc_key" not in json.dumps(list(db.rows.values()), ensure_ascii=False)
    statement_calls = [c for c in calls if c[0] == "fnlttSinglAcntAll.json"]
    calls.clear()
    assert asyncio.run(dart.collect(db, fetch, today=date(2026, 10, 20))) == 0
    assert not [c for c in calls if c[0] in ("fnlttSinglAcntAll.json", "corpCode.xml")]
    assert len(statement_calls) >= 4
