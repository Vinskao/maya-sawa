"""2026-11-12: TGA and net liquidity were weekly (FRED Wednesday levels) although the Treasury publishes the TGA every
business day; KRW and WTI charts read FRED copies that trail by a week while daily closes were available."""
from maya_sawa.services import market_macro
from maya_sawa.services.market_macro import daily_net_liquidity_rows, parse_dts_tga, DTS_TGA_ACCOUNT


def test_dts_keeps_only_the_tga_closing_balance_in_usd_billion():
    payload = {'data': [
        {'record_date': '2026-11-09', 'account_type': 'Treasury General Account (TGA) Opening Balance', 'open_today_bal': '910313'},
        {'record_date': '2026-11-09', 'account_type': DTS_TGA_ACCOUNT, 'open_today_bal': '922633'},
        {'record_date': '2026-11-06', 'account_type': DTS_TGA_ACCOUNT, 'open_today_bal': '900000'},
        {'record_date': '2026-11-05', 'account_type': DTS_TGA_ACCOUNT, 'open_today_bal': 'null'},
    ]}
    assert parse_dts_tga(payload) == [{'code': 'TGA_DAILY', 'period': '2026-11-06', 'value': '900.0'},
                                      {'code': 'TGA_DAILY', 'period': '2026-11-09', 'value': '922.6'}]


def test_daily_net_liquidity_carries_weekly_assets_forward_and_skips_days_without_inputs():
    walcl = [{'period': '2026-11-04', 'value': '6600.0'}]
    rrp = [{'period': '2026-11-06', 'value': '20.0'}, {'period': '2026-11-09', 'value': '30.0'}]
    tga = [{'period': '2026-10-20', 'value': '800.0'}, {'period': '2026-11-06', 'value': '900.0'},
           {'period': '2026-11-10', 'value': '922.6'}]
    rows = daily_net_liquidity_rows(walcl, tga, rrp)
    # 10-20 has no total assets within 8 days; 11-10 uses the 11-09 RRP (one day earlier)
    assert rows == [{'code': 'US_NET_LIQUIDITY_DAILY', 'period': '2026-11-06', 'value': '5680.0'},
                    {'code': 'US_NET_LIQUIDITY_DAILY', 'period': '2026-11-10', 'value': '5647.4'}]


def test_new_daily_series_are_registered_for_the_cache_and_long_history():
    for code in ('TGA_DAILY', 'US_NET_LIQUIDITY_DAILY', 'USD_KRW'):
        assert code in market_macro.FREE_CACHE_CODES
    assert {'TGA_DAILY', 'US_NET_LIQUIDITY_DAILY'} <= market_macro.LONG_HISTORY_CODES
    assert market_macro.YAHOO_SYMBOLS['USD_KRW'] == 'KRW=X'
