from datetime import date, datetime, timedelta, timezone

from maya_sawa.databases.market_macro_db import MacroEvent, _highlight

NOW = datetime(2026, 10, 16, 4, 0, tzinfo=timezone.utc)


def _event(scheduled_date: date, scheduled_at: datetime | None) -> MacroEvent:
    return MacroEvent(id="e", group_id="cpi", status="scheduled", scheduled_date=scheduled_date, scheduled_at=scheduled_at)


def test_past_release_waits_until_its_period_is_stored():
    event = _event(date(2026, 10, 14), datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc))
    assert _highlight(event, NOW, "2026-08") == "waiting"
    assert _highlight(event, NOW, None) == "waiting"


def test_past_release_with_stored_period_is_settled():
    event = _event(date(2026, 10, 14), datetime(2026, 10, 14, 12, 30, tzinfo=timezone.utc))
    assert _highlight(event, NOW, "2026-09") == "none"
    recent = _event(date(2026, 10, 15), NOW - timedelta(hours=3))
    assert _highlight(recent, NOW, "2026-09") == "published"


def test_fed_decision_needs_a_later_daily_observation():
    event = _event(date(2026, 10, 14), None)
    assert _highlight(event, NOW, "2026-10-14") == "waiting"
    assert _highlight(event, NOW, "2026-10-15") == "none"


def test_future_release_is_unaffected():
    event = _event(date(2026, 11, 10), datetime(2026, 11, 10, 13, 30, tzinfo=timezone.utc))
    assert _highlight(event, NOW, "2026-09") == "none"
