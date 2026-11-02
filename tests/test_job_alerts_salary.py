import pytest

from maya_sawa.services.job_alerts.salary import (
    MIN_ANNUAL_TWD, Verdict, evaluate_salary, parse_annual_range,
)


@pytest.mark.parametrize('text,expected', [
    ('月薪 60,000 ~ 80,000 TWD', (720_000, 960_000)),
    ('月薪 100,000 - 150,000 元', (1_200_000, 1_800_000)),
    ('年薪 1,300,000 ~ 2,000,000 TWD', (1_300_000, 2_000_000)),
    ('年薪 150 萬 ~ 200 萬', (1_500_000, 2_000_000)),
    ('月薪 80K-120K', (960_000, 1_440_000)),
    ('月薪 110,000 以上', (1_320_000, None)),
])
def test_parse_annual_range(text, expected):
    assert parse_annual_range(text) == expected


@pytest.mark.parametrize('text', [
    '', None, '面議', '薪資面議', '待遇優渥', '60,000 ~ 80,000',  # no unit label
    'USD 5,000 - 8,000 / month',
])
def test_unparseable_is_none(text):
    assert parse_annual_range(text) is None


def test_threshold_is_1_3m():
    assert MIN_ANNUAL_TWD == 1_300_000


@pytest.mark.parametrize('text,verdict', [
    ('月薪 60,000 ~ 80,000 TWD', Verdict.REJECTED),        # max 960k < 1.3M
    ('年薪 1,299,999 TWD', Verdict.REJECTED),
    ('月薪 110,000 ~ 150,000', Verdict.PASSED),            # min 1.32M
    ('年薪 1,300,000 以上', Verdict.PASSED),                # exactly threshold
    ('月薪 90,000 ~ 130,000', Verdict.NEEDS_REVIEW),       # straddles
    ('月薪 120,000 以上', Verdict.PASSED),
    ('月薪 80,000 以上', Verdict.NEEDS_REVIEW),            # open-ended, below
    ('面議', Verdict.NEEDS_REVIEW),
    (None, Verdict.NEEDS_REVIEW),
])
def test_evaluate(text, verdict):
    assert evaluate_salary(text).verdict is verdict


@pytest.mark.parametrize('text,expected', [
    ('1.2M ~ 2.2M TWD/年', (1_200_000, 2_200_000)),
    ('800K ~ 1.2M TWD/年', (800_000, 1_200_000)),
    ('1M ~ 2M TWD/年', (1_000_000, 2_000_000)),
    ('60K ~ 80K TWD/月', (720_000, 960_000)),
])
def test_cake_email_format(text, expected):
    assert parse_annual_range(text) == expected


def test_cake_email_verdicts():
    assert evaluate_salary('1.5M ~ 2.8M TWD/年').verdict is Verdict.PASSED
    assert evaluate_salary('1.2M ~ 2.2M TWD/年').verdict is Verdict.NEEDS_REVIEW
    assert evaluate_salary('800K ~ 1.2M TWD/年').verdict is Verdict.REJECTED
