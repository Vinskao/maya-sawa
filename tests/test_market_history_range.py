import asyncio
from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from maya_sawa.api import market


def test_history_accepts_five_years_and_preserves_public_response(monkeypatch):
    calls = []
    def history(code, start, end, **kwargs):
        calls.append((code, start, end))
        return {'points': [{'date': '2021-10-23', 'sources': {}}]}
    monkeypatch.setattr(market.market_history_db, 'history', history)
    result = asyncio.run(market.get_market_dashboard_history('2330', date(2021, 10, 23), date(2026, 10, 23)))
    assert result['start'] == '2021-10-23'
    assert result['end'] == '2026-10-23'
    assert result['collecting'] is False
    assert calls == [('2330', date(2021, 10, 23), date(2026, 10, 23))]


@pytest.mark.parametrize('start,end', [(date(2026, 1, 2), date(2026, 1, 1)),
                                      (date(2020, 1, 1), date(2026, 1, 1))])
def test_history_rejects_reversed_or_excessive_range(start, end):
    with pytest.raises(HTTPException) as error:
        asyncio.run(market.get_market_dashboard_history('2330', start, end))
    assert error.value.status_code == 422
