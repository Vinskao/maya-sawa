"""AI build-out financing: CoreWeave's balance sheet and cash flow, and NVIDIA's investments and guarantees (SEC companyfacts, 2026-11-22).

CoreWeave is the neocloud whose ability to keep borrowing decides whether GPU capacity gets paid for; NVIDIA is the vendor that
funds and backstops such customers. Both report in USD; balance-sheet figures are quarter-end levels, cash flows are single
quarters (year-to-date 10-Q figures differenced, as for the cloud providers). Fiscal quarter ends land on calendar quarters.
"""
from .csp_capex import calendar_quarter, quarterly_values

COMPANIES = {"CRWV": "0001769628", "NVDA": "0001045810"}
QUARTERS = 20
FORMS = ("10-Q", "10-K", "10-Q/A", "10-K/A")
# code -> (company, us-gaap tag, "instant" balance or "flow" per quarter)
SPECS = {
    "CRWV_DEBT": ("CRWV", "DebtInstrumentCarryingAmount", "instant"),
    "CRWV_CASH": ("CRWV", "CashAndCashEquivalentsAtCarryingValue", "instant"),
    "CRWV_DEBT_DUE_12M": ("CRWV", "LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths", "instant"),
    "CRWV_RPO": ("CRWV", "RevenueRemainingPerformanceObligation", "instant"),
    "CRWV_OPERATING_CASH_FLOW": ("CRWV", "NetCashProvidedByUsedInOperatingActivities", "flow"),
    "CRWV_CAPEX": ("CRWV", "PaymentsToAcquirePropertyPlantAndEquipment", "flow"),
    "CRWV_INTEREST_EXPENSE": ("CRWV", "InterestExpenseDebt", "flow"),
    "NVDA_NON_MARKETABLE_EQUITY": ("NVDA", "EquitySecuritiesWithoutReadilyDeterminableFairValueAmount", "instant"),
    "NVDA_GUARANTEE_EXPOSURE": ("NVDA", "GuaranteeObligationsMaximumExposure", "instant"),
    "NVDA_OPERATING_CASH_FLOW": ("NVDA", "NetCashProvidedByUsedInOperatingActivities", "flow"),
}
_DESCRIPTIONS = {
    "CRWV_DEBT": "CoreWeave debt carrying amount", "CRWV_CASH": "CoreWeave cash and cash equivalents",
    "CRWV_DEBT_DUE_12M": "CoreWeave debt principal due within 12 months",
    "CRWV_RPO": "CoreWeave remaining performance obligations (contract backlog)",
    "CRWV_OPERATING_CASH_FLOW": "CoreWeave operating cash flow", "CRWV_CAPEX": "CoreWeave capital spending (property and equipment)",
    "CRWV_INTEREST_EXPENSE": "CoreWeave interest expense on debt",
    "NVDA_NON_MARKETABLE_EQUITY": "NVIDIA non-marketable equity investments (strategic stakes in customers and partners)",
    "NVDA_GUARANTEE_EXPOSURE": "NVIDIA maximum exposure under guarantees (backstops of customers' obligations)",
    "NVDA_OPERATING_CASH_FLOW": "NVIDIA operating cash flow",
}
FINANCING_SERIES = {code: (f"{_DESCRIPTIONS[code]} (SEC filings, quarterly)", "USD billion", "quarterly") for code in SPECS}
FINANCING_SERIES.update({
    "CRWV_CASH_TO_DEBT_DUE_12M": ("CoreWeave cash divided by debt principal due within 12 months (derived; below 1 means it must raise or roll over money)", "times", "quarterly"),
    "CRWV_OCF_TO_CAPEX": ("CoreWeave operating cash flow as a percentage of capital spending (derived; the rest is financed externally)", "percent", "quarterly"),
})


def instant_values(facts: list[dict]) -> dict[str, float]:
    """{period end: balance} from 10-Q/10-K point-in-time facts; the newest filing wins for a date."""
    latest: dict[str, dict] = {}
    for fact in facts:
        if "start" in fact or fact.get("form") not in FORMS or not isinstance(fact.get("val"), (int, float)) or "end" not in fact:
            continue
        end = fact["end"]
        if end not in latest or str(fact.get("filed", "")) >= str(latest[end].get("filed", "")):
            latest[end] = fact
    return {end: float(fact["val"]) for end, fact in latest.items()}


def _by_quarter(values: dict[str, float]) -> dict[str, float]:
    return {calendar_quarter(end): value for end, value in sorted(values.items())}


def _ratio(top: dict[str, float], bottom: dict[str, float], scale: float) -> dict[str, float]:
    digits = 2 if scale == 1 else 1
    return {period: round(top[period] / bottom[period] * scale, digits) for period in sorted(top) if bottom.get(period, 0) > 0}


def financing_rows(companies: dict[str, dict]) -> list[dict]:
    """[{code, period, value}] in USD billions (plus two derived ratios) from {ticker: {tag: companyfacts tag}}."""
    levels: dict[str, dict[str, float]] = {}
    for code, (ticker, tag, kind) in SPECS.items():
        units = companies.get(ticker, {}).get(tag, {}).get("units", {}).get("USD", [])
        values = instant_values(units) if kind == "instant" else quarterly_values(units)
        if values:
            levels[code] = {period: round(value / 1e9, 2) for period, value in sorted(_by_quarter(values).items())[-QUARTERS:]}
    rows = [{"code": code, "period": period, "value": value} for code, series in levels.items() for period, value in sorted(series.items())]
    derived = {"CRWV_CASH_TO_DEBT_DUE_12M": (levels.get("CRWV_CASH", {}), levels.get("CRWV_DEBT_DUE_12M", {}), 1),
               "CRWV_OCF_TO_CAPEX": (levels.get("CRWV_OPERATING_CASH_FLOW", {}), levels.get("CRWV_CAPEX", {}), 100)}
    for code, (top, bottom, scale) in derived.items():
        rows += [{"code": code, "period": period, "value": value} for period, value in _ratio(top, bottom, scale).items()]
    return rows
