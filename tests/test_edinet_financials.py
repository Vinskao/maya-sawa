"""Japan: five years of annual figures from EDINET securities reports (有価証券報告書), free with an owner-registered key.

2026-10-29: J-Quants Free covers two years. Every annual securities report carries a five-year table (主要な経営指標等の
推移); EDINET API v2 returns it as XBRL-to-CSV (type=5), elements ending in SummaryOfBusinessResults with contexts
CurrentYear…Prior4Year. One report per company therefore gives five fiscal years. Consolidated figures are preferred;
the parent-only columns (_NonConsolidatedMember) are used only when a company reports no consolidated figure.

Fixtures are real: Advantest's (6857) report S100YKTA filed 2026-06-26 (all 160 summary rows, the rest of the CSV dropped)
and two records of the 2026-06-26 document list. They were fetched inside the pod so the key never left it.
"""
import asyncio
import json
from pathlib import Path

import pytest

from maya_sawa.services import edinet_financials as edinet

FIX = Path(__file__).parent / "fixtures" / "edinet"
CSV = (FIX / "jpcrp030000-asr_E01950_2026-03-31_summary.tsv").read_text(encoding="utf-8")
LISTING = json.loads((FIX / "documents_2026-06-26_trimmed.json").read_text(encoding="utf-8"))
FOUND = LISTING["results"][1]


def test_annual_reports_of_holdings_are_picked_from_the_daily_list():
    found = edinet.annual_reports(LISTING, {"6857"})
    assert [doc["docID"] for doc in found] == ["S100YKTA"]
    assert edinet.annual_reports(LISTING, {"7203"}) == []               # an extraordinary report (180) is not one


def test_five_fiscal_years_of_consolidated_ifrs_figures():
    release = edinet.parse_summary_csv(CSV, FOUND)
    years = {row["end"]: row for row in release["durations"]}
    assert sorted(years) == ["2022-03-31", "2023-03-31", "2024-03-31", "2025-03-31", "2026-03-31"]
    latest, oldest = years["2026-03-31"], years["2022-03-31"]
    assert latest["start"] == "2025-04-01" and latest["durationDays"] == 365
    assert latest["revenue"] == 1_128_610_000_000                       # consolidated IFRS, not parent-only 988,232 million
    assert latest["netIncome"] == 375_353_000_000
    assert latest["epsBasic"] == 515.15 and latest["epsDiluted"] == 513.30
    assert latest["operatingCashFlow"] == 335_182_000_000 and latest["investingCashFlow"] == -34_552_000_000
    assert oldest["revenue"] == 416_901_000_000 and oldest["epsBasic"] == 449.56   # as reported (before a later split)
    sheets = {row["end"]: row for row in release["instants"]}
    assert sheets["2026-03-31"]["assets"] == 1_171_816_000_000
    assert sheets["2026-03-31"]["equity"] == 795_726_000_000
    assert sheets["2026-03-31"]["cash"] == 339_966_000_000 and sheets["2022-03-31"]["cash"] == 116_582_000_000
    assert release["standard"] == "IFRS" and release["releasedAt"] == "2026-06-26T14:05"
    assert "Subscription-Key" not in json.dumps(release) and release["zipUrl"].endswith("S100YKTA")


def test_parent_only_figures_are_used_when_no_consolidated_figure_exists():
    parent_only = "\n".join(line for line in CSV.splitlines() if "IFRS" not in line.split("\t")[0])
    latest = {row["end"]: row for row in edinet.parse_summary_csv(parent_only, FOUND)["durations"]}["2026-03-31"]
    assert latest["revenue"] == 988_232_000_000


def test_collect_scans_back_until_each_holding_has_its_latest_annual_report():
    class Db:
        def __init__(self): self.saved = []
        def market_codes(self, market): return ["6857"]
        def history(self, code, market, kind): return []
        def latest(self, code, market, kind): return {"conid": 7}
        def save(self, code, market, conid, kind, payload, period=None): self.saved.append((code, kind, period, payload))

    days = []

    async def listing(day):
        days.append(day)
        return LISTING if day == "2026-06-26" else {"results": []}

    async def document(doc_id):
        assert doc_id == "S100YKTA"
        return CSV

    db = Db()
    saved = asyncio.run(edinet.collect(db, listing, document, today=edinet.date(2026, 6, 30), max_days=10))
    assert saved == 1 and days[:5] == ["2026-06-30", "2026-06-29", "2026-06-28", "2026-06-27", "2026-06-26"]
    assert len(days) == 5                                               # stops once every holding is found
    kinds = [(kind, period) for _, kind, period, _ in db.saved]
    assert ("edinet_release", "S100YKTA") in kinds and any(kind == "financials" for kind, _ in kinds)


def test_japan_financials_merge_edinet_years_with_the_other_sources():
    from maya_sawa.services import tdnet_financials
    release = edinet.parse_summary_csv(CSV, FOUND)

    class Db:
        def history(self, code, market, kind): return [{"payload": release}] if kind == "edinet_release" else []
        def save(self, *args, **kwargs): pass

    data = tdnet_financials.rebuild_japan(Db(), "6857", 7)
    assert [row["end"] for row in data["annual"]] == ["2022-03-31", "2023-03-31", "2024-03-31", "2025-03-31", "2026-03-31"]
    assert "EDINET" in data["source"]
