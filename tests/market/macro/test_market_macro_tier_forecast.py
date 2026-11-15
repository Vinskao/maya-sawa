"""2026-11-15: 台經院（TIER）總體經濟預測 — GDP and CPI forecasts for this year (revised) and next year.

TIER publishes the forecast table only as an image, so the numbers come from the press-release text on
https://www.tier.org.tw/forecast/macro_trends_annual.aspx (fixture copied from the 2026-11-09 release).
"""
import pytest

from maya_sawa.services import market_macro
from maya_sawa.services.market_macro import parse_tier_forecast

RELEASE = """
<p>「2027台灣總體經濟預測」新聞稿</p><p>2026年11月9日</p>
<p>整體而言，根據台經院於2026年11月公布之最新預測，2027年經濟成長率為6.45%，較2026年修正後的12.34%下降5.89個百分點。</p>
<p>綜合考量地緣政治與極端天候等風險，預測2027年CPI年增率為1.94%，較2026年修正後的2.05%下降0.11個百分點，整體通膨維持溫和。</p>
"""


def test_reads_gdp_and_cpi_for_both_years_and_the_release_date():
    rows, released = parse_tier_forecast(RELEASE)
    assert released == "2026-11-09"
    assert sorted((r["code"], r["period"], r["value"]) for r in rows) == [
        ("TIER_TW_CPI_FORECAST", "2026", "2.05"),
        ("TIER_TW_CPI_FORECAST", "2027", "1.94"),
        ("TIER_TW_GDP_FORECAST", "2026", "12.34"),
        ("TIER_TW_GDP_FORECAST", "2027", "6.45"),
    ]


def test_handles_wording_without_the_revised_clause():
    rows, _ = parse_tier_forecast("2026年1月20日 預測2026年經濟成長率為3.12%。預測2026年CPI年增率為1.80%。")
    assert ("TIER_TW_GDP_FORECAST", "2026", "3.12") in [(r["code"], r["period"], r["value"]) for r in rows]
    assert ("TIER_TW_CPI_FORECAST", "2026", "1.80") in [(r["code"], r["period"], r["value"]) for r in rows]


def test_refuses_a_page_without_the_forecast_rather_than_guessing():
    with pytest.raises(ValueError):
        parse_tier_forecast("<p>網站維護中</p>")


def test_forecast_codes_are_served_from_the_free_series_cache():
    assert {"TIER_TW_GDP_FORECAST", "TIER_TW_CPI_FORECAST"} <= market_macro.FREE_CACHE_CODES
