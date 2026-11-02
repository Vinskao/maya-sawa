"""Salary gate for job alerts: annual TWD >= 1,300,000 or it never reaches applying."""
import re
from dataclasses import dataclass
from enum import Enum

MIN_ANNUAL_TWD = 1_300_000


class Verdict(str, Enum):
    PASSED = 'passed'
    REJECTED = 'rejected'
    NEEDS_REVIEW = 'needs_review'


@dataclass(frozen=True)
class SalaryDecision:
    verdict: Verdict
    annual_min: int | None
    annual_max: int | None
    reason: str


_NUM = re.compile(r'(\d[\d,]*(?:\.\d+)?)\s*(萬|[KkMm])?')
_FOREIGN = re.compile(r'USD|US\$|\$|JPY|EUR|SGD|RMB|CNY|美金|美元|日圓|人民幣')


def parse_annual_range(text):
    """Return (annual_min, annual_max|None) in TWD, or None when it cannot be converted safely."""
    if not text:
        return None
    if _FOREIGN.search(text):
        return None
    if '年薪' in text or re.search(r'/\s*年', text):
        months = 1
    elif '月薪' in text or re.search(r'/\s*月', text):
        months = 12
    else:
        return None  # no unit label: guessing monthly vs annual is how bad data gets in
    values = []
    for raw, suffix in _NUM.findall(text):
        value = float(raw.replace(',', ''))
        if suffix == '萬':
            value *= 10_000
        elif suffix in ('K', 'k'):
            value *= 1_000
        elif suffix in ('M', 'm'):
            value *= 1_000_000
        values.append(int(round(value * months)))
    if not values:
        return None
    if len(values) == 1:
        return (values[0], None) if re.search(r'以上|\+|起', text) else (values[0], values[0])
    return values[0], values[1]


def evaluate_salary(text):
    parsed = parse_annual_range(text)
    if parsed is None:
        return SalaryDecision(Verdict.NEEDS_REVIEW, None, None, 'salary undisclosed or not convertible to annual TWD')
    low, high = parsed
    if high is not None and high < MIN_ANNUAL_TWD:
        return SalaryDecision(Verdict.REJECTED, low, high, f'max annual {high} < {MIN_ANNUAL_TWD}')
    if low >= MIN_ANNUAL_TWD:
        return SalaryDecision(Verdict.PASSED, low, high, 'min annual meets threshold')
    return SalaryDecision(Verdict.NEEDS_REVIEW, low, high, 'range straddles or is open-ended below threshold')
