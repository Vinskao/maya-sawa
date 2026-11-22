"""CoreWeave and NVIDIA balance-sheet and cash-flow series from SEC companyfacts."""
from maya_sawa.services import ai_financing as fin


def instant(end, val, form="10-Q", filed="2026-01-01"):
    return {"end": end, "val": val, "form": form, "filed": filed}


def span(start, end, val, filed="2026-01-01"):
    return {"start": start, "end": end, "val": val, "form": "10-Q", "filed": filed}


def tag(*facts):
    return {"units": {"USD": list(facts)}}


def test_instant_values_use_the_newest_filing_per_date_and_ignore_other_forms():
    facts = [instant("2026-09-30", 1.0, filed="2026-10-01"), instant("2026-09-30", 2.0, filed="2026-11-01"),
             instant("2026-06-30", 9.0, form="8-K")]
    assert fin.instant_values(facts) == {"2026-09-30": 2.0}


def test_balance_sheet_series_are_in_billions_on_calendar_quarters():
    companies = {"CRWV": {"DebtInstrumentCarryingAmount": tag(instant("2026-09-30", 47.5e9))},
                 "NVDA": {"GuaranteeObligationsMaximumExposure": tag(instant("2026-07-26", 108.5e9))}}
    rows = fin.financing_rows(companies)
    assert {"code": "CRWV_DEBT", "period": "2026-09", "value": 47.5} in rows
    assert {"code": "NVDA_GUARANTEE_EXPOSURE", "period": "2026-09", "value": 108.5} in rows


def test_cash_flow_series_are_single_quarters():
    facts = {"NetCashProvidedByUsedInOperatingActivities": tag(span("2026-01-01", "2026-06-30", 3e9), span("2026-01-01", "2026-09-30", 5e9))}
    rows = [r for r in fin.financing_rows({"CRWV": facts}) if r["code"] == "CRWV_OPERATING_CASH_FLOW"]
    assert rows == [{"code": "CRWV_OPERATING_CASH_FLOW", "period": "2026-09", "value": 2.0}]


def test_cash_against_principal_due_within_a_year_is_a_multiple():
    facts = {"CashAndCashEquivalentsAtCarryingValue": tag(instant("2026-09-30", 4.0e9)),
             "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths": tag(instant("2026-09-30", 10.0e9))}
    rows = fin.financing_rows({"CRWV": facts})
    assert {"code": "CRWV_CASH_TO_DEBT_DUE_12M", "period": "2026-09", "value": 0.4} in rows


def test_operating_cash_over_capex_is_a_percentage_and_skips_zero_capex():
    facts = {"NetCashProvidedByUsedInOperatingActivities": tag(span("2026-07-01", "2026-09-30", 2e9)),
             "PaymentsToAcquirePropertyPlantAndEquipment": tag(span("2026-07-01", "2026-09-30", 8e9), span("2026-04-01", "2026-06-30", 0))}
    rows = [r for r in fin.financing_rows({"CRWV": facts}) if r["code"] == "CRWV_OCF_TO_CAPEX"]
    assert rows == [{"code": "CRWV_OCF_TO_CAPEX", "period": "2026-09", "value": 25.0}]


def test_missing_companies_or_tags_just_produce_no_rows():
    assert fin.financing_rows({}) == []
    assert fin.financing_rows({"CRWV": {}}) == []


def test_series_are_registered_for_caching():
    from maya_sawa.services import market_macro
    assert set(fin.FINANCING_SERIES) <= market_macro.FREE_CACHE_CODES
    assert fin.FINANCING_SERIES["CRWV_CASH_TO_DEBT_DUE_12M"][1] == "times"


def test_only_the_latest_twenty_quarters_are_kept():
    facts = {"CashAndCashEquivalentsAtCarryingValue": tag(*[instant(f"{2010 + n // 4}-{(n % 4 + 1) * 3:02d}-28", 1e9) for n in range(40)])}
    rows = [r for r in fin.financing_rows({"CRWV": facts}) if r["code"] == "CRWV_CASH"]
    assert len(rows) == 20
    assert rows[-1]["period"] == "2019-12"
