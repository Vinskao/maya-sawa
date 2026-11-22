"""CSP capital spending and operating cash flow: quarters differenced from year-to-date 10-Q figures, then summed."""
from maya_sawa.services import csp_capex as csp


SPANS = {"2026-03": ("2026-01-01", "2026-03-31"), "2026-06": ("2026-04-01", "2026-06-30"), "2026-09": ("2026-07-01", "2026-09-30")}


def fact(start, end, val, form="10-Q", filed="2026-01-01"):
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed}


def test_year_to_date_figures_become_single_quarters():
    facts = [fact("2026-01-01", "2026-03-31", 10), fact("2026-01-01", "2026-06-30", 25), fact("2026-01-01", "2026-09-30", 45),
             fact("2026-01-01", "2026-12-31", 70, "10-K")]
    assert csp.quarterly_values(facts) == {"2026-03-31": 10, "2026-06-30": 15, "2026-09-30": 20, "2026-12-31": 25}


def test_a_stand_alone_quarter_is_used_as_is_and_a_restated_filing_wins():
    facts = [fact("2026-04-01", "2026-06-30", 8, filed="2026-07-01"), fact("2026-04-01", "2026-06-30", 9, filed="2026-10-01")]
    assert csp.quarterly_values(facts) == {"2026-06-30": 9}


def test_fiscal_quarter_ends_land_on_the_nearest_calendar_quarter():
    assert [csp.calendar_quarter(day) for day in ("2026-08-31", "2026-11-30", "2027-02-28", "2026-05-31", "2026-09-30", "2026-12-31")] == [
        "2026-09", "2026-12", "2027-03", "2026-06", "2026-09", "2026-12"]


def test_a_quarter_is_totalled_only_when_every_company_reported_it():
    def company(values):
        return {"PaymentsToAcquirePropertyPlantAndEquipment": {"units": {"USD": [fact(SPANS[p][0], SPANS[p][1], v * 1e9) for p, v in values.items()]}}}
    a = company({"2026-03": 10, "2026-06": 12})
    b = company({"2026-03": 20, "2026-06": 22, "2026-09": 30})
    assert csp.csp_totals({"A": a, "B": b}, csp.CAPEX_TAGS) == [{"period": "2026-03", "value": 30.0}, {"period": "2026-06", "value": 34.0}]


def test_the_tag_with_the_newest_quarter_is_used():
    old = {"units": {"USD": [fact("2017-01-01", "2017-03-31", 1)]}}
    new = {"units": {"USD": [fact("2026-07-01", "2026-09-30", 77)]}}
    assert csp.best_series({"PaymentsToAcquirePropertyPlantAndEquipment": old, "PaymentsToAcquireProductiveAssets": new}, csp.CAPEX_TAGS) == {"2026-09-30": 77.0}


def test_capex_to_cash_flow_ratio_is_a_percentage_over_quarters_both_series_have():
    from maya_sawa.services.csp_capex import capex_cash_flow_ratio
    capex = [{"period": "2026-06", "value": 150.0}, {"period": "2026-09", "value": 230.0}]
    cash = [{"period": "2026-09", "value": 200.0}, {"period": "2026-12", "value": 210.0}]
    assert capex_cash_flow_ratio(capex, cash) == [{"period": "2026-09", "value": 115.0}]


def test_ratio_skips_quarters_with_zero_or_negative_cash_flow():
    from maya_sawa.services.csp_capex import capex_cash_flow_ratio
    assert capex_cash_flow_ratio([{"period": "2026-09", "value": 5.0}], [{"period": "2026-09", "value": 0.0}]) == []


def test_ratio_and_credit_tier_spreads_are_registered():
    from maya_sawa.services import market_macro
    assert market_macro.CSP_SERIES["CSP_CAPEX_OCF_RATIO"][1] == "percent"
    assert {"BAMLH0A3HYC", "BAMLC0A4CBBB"} <= set(market_macro.FRED_SERIES)
    assert {"BAMLH0A3HYC", "BAMLC0A4CBBB", "CSP_CAPEX_OCF_RATIO"} <= market_macro.FREE_CACHE_CODES
