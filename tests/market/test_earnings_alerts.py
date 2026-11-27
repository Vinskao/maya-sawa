from maya_sawa.services.earnings_alerts import GROSS_MARGIN_DROP_PP, margin_alert


def q(period, margin, qoq=None):
    # Same shape as build_fundamental_metrics()["quarterly"]: margins and their change are in percent points.
    return {"period": period, "grossMargin": margin, "grossMarginQoQ": qoq}


def test_drop_of_two_points_or_more_alerts():
    alert = margin_alert("4979", [q("2026Q1", 58.6), q("2026Q2", 55.0, -3.6)])
    assert alert["period"] == "2026Q2"
    assert "58.6%" in alert["body"] and "55.0%" in alert["body"] and "3.6" in alert["body"]


def test_small_drop_is_quiet():
    assert margin_alert("4979", [q("2026Q1", 58.6), q("2026Q2", 57.0, -1.6)]) is None


def test_two_consecutive_declines_alert_even_when_each_is_small():
    quarterly = [q("2026Q1", 60.0), q("2026Q2", 59.0, -1.0), q("2026Q3", 58.0, -1.0)]
    alert = margin_alert("4979", quarterly)
    assert alert is not None and alert["period"] == "2026Q3"


def test_rise_or_missing_data_is_quiet():
    assert margin_alert("4979", [q("2026Q1", 50.0), q("2026Q2", 60.0, 10.0)]) is None
    assert margin_alert("4979", [q("2026Q2", None, None)]) is None
    assert margin_alert("4979", []) is None


def test_only_the_latest_quarter_is_judged():
    quarterly = [q("2026Q1", 60.0), q("2026Q2", 50.0, -10.0), q("2026Q3", 52.0, 2.0)]
    assert margin_alert("4979", quarterly) is None


def test_threshold_is_two_points():
    assert GROSS_MARGIN_DROP_PP == 2.0


class FakeStore:
    def __init__(self):
        self.claimed = set()

    def record(self, run, day, url):
        if (run, day) in self.claimed:
            return False
        self.claimed.add((run, day))
        return True

    def release(self, run, day):
        self.claimed.discard((run, day))


def test_each_report_is_announced_once_and_named():
    from maya_sawa.services.earnings_alerts import notify_margin_drops
    store, sent = FakeStore(), []
    metrics = {"4979": [q("2026Q1", 58.6), q("2026Q2", 55.0, -3.6)], "2330": [q("2026Q1", 50.0), q("2026Q2", 51.0, 1.0)]}

    def send(kind, title, body):
        sent.append((kind, title))
        return {"sent": True}

    assert notify_margin_drops(store, metrics, send, {"4979": "聯亞"}) == ["4979"]
    assert notify_margin_drops(store, metrics, send, {"4979": "聯亞"}) == []
    assert sent == [("attention", "4979 聯亞 毛利率下滑（2026Q2）")]


def test_failed_send_is_retried_next_pass():
    from maya_sawa.services.earnings_alerts import notify_margin_drops
    store = FakeStore()
    metrics = {"4979": [q("2026Q1", 58.6), q("2026Q2", 55.0, -3.6)]}
    assert notify_margin_drops(store, metrics, lambda *a: {"sent": False}) == []
    assert notify_margin_drops(store, metrics, lambda *a: {"sent": True}) == ["4979"]
