"""Cloud service providers' capital spending and operating cash flow, quarterly, from SEC EDGAR companyfacts (2026-11-18).

Five companies: Microsoft, Alphabet, Amazon, Meta, Oracle. A 10-Q reports cash flow year to date, so a quarter is the
difference between two consecutive cumulative figures of the same fiscal year. Fiscal quarters are placed on the nearest
calendar quarter end (Oracle's August quarter is the September one; Microsoft's September quarter is its fiscal Q1).
A quarter is totalled only when all five companies have reported it, so the total never mixes four and five companies.
"""
from datetime import date

CSP_COMPANIES = {"MSFT": "0000789019", "GOOGL": "0001652044", "AMZN": "0001018724", "META": "0001326801", "ORCL": "0001341439"}
CAPEX_TAGS = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")
OPERATING_CASH_TAG = "NetCashProvidedByUsedInOperatingActivities"


def _span(fact: dict) -> tuple[date, date] | None:
    try:
        return date.fromisoformat(fact["start"]), date.fromisoformat(fact["end"])
    except (KeyError, TypeError, ValueError):
        return None


def quarterly_values(facts: list[dict]) -> dict[str, float]:
    """{period end: that quarter's amount} from 10-Q/10-K duration facts. Cumulative facts are differenced within a fiscal year."""
    latest: dict[tuple[str, str], dict] = {}
    for fact in facts:
        if fact.get("form") not in ("10-Q", "10-K", "10-Q/A", "10-K/A") or not isinstance(fact.get("val"), (int, float)):
            continue
        span = _span(fact)
        if span is None or (span[1] - span[0]).days < 60:
            continue
        key = (fact["start"], fact["end"])
        if key not in latest or str(fact.get("filed", "")) >= str(latest[key].get("filed", "")):
            latest[key] = fact
    result: dict[str, float] = {}
    chains: dict[str, list[tuple[date, float]]] = {}
    for (start, end), fact in latest.items():
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
        if days <= 120:
            result[end] = float(fact["val"])                       # a stand-alone quarter
        chains.setdefault(start, []).append((date.fromisoformat(end), float(fact["val"])))
    for chain in chains.values():
        chain.sort()
        previous_end, previous_value = None, 0.0
        for end, value in chain:
            gap = (end - previous_end).days if previous_end else 0
            if previous_end is None:
                pass                                                # the first span is handled as a stand-alone quarter above
            elif 60 <= gap <= 120 and end.isoformat() not in result:
                result[end.isoformat()] = value - previous_value
            previous_end, previous_value = end, value
    return result


def calendar_quarter(end: str) -> str:
    """The calendar quarter end (YYYY-MM) nearest to a fiscal quarter end: Aug 31 -> 09, Nov 30 -> 12, Feb 28 -> 03, May 31 -> 06."""
    day = date.fromisoformat(end)
    month = {1: 3, 2: 3, 3: 3, 4: 6, 5: 6, 6: 6, 7: 9, 8: 9, 9: 9, 10: 12, 11: 12, 12: 12}[day.month]
    return f"{day.year}-{month:02d}"


def best_series(facts_by_tag: dict, tags: tuple[str, ...]) -> dict[str, float]:
    """Quarterly values from the tag that reports the newest quarter (companies switch tags over the years)."""
    best: dict[str, float] = {}
    for tag in tags:
        values = quarterly_values(facts_by_tag.get(tag, {}).get("units", {}).get("USD", []))
        if values and (not best or max(values) > max(best)):
            best = values
    return best


def csp_totals(companies: dict[str, dict], tags: tuple[str, ...], quarters: int = 20) -> list[dict]:
    """[{period, value}] in USD billions: the sum over all companies for each calendar quarter every one of them reported."""
    per_company = []
    for facts in companies.values():
        series: dict[str, float] = {}
        for end, value in best_series(facts, tags).items():
            series[calendar_quarter(end)] = value
        per_company.append(series)
    if not per_company:
        return []
    common = sorted(set.intersection(*(set(series) for series in per_company)))[-quarters:]
    return [{"period": period, "value": round(sum(series[period] for series in per_company) / 1e9, 2)} for period in common]
