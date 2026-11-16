"""2026-11-16: daily social follower / reach snapshots, summarized with the weekly change for /palais."""
from datetime import date

from sqlalchemy import create_engine

from maya_sawa.services import social_metrics as sm


def rows(day, **values):
    return [{"day": day, "platform": k.split("_")[0], "metric": k.split("_")[1], "value": v} for k, v in values.items()]


def test_summary_shows_the_latest_value_and_the_change_against_a_week_earlier():
    data = rows("2026-11-09", instagram_followers=10) + rows("2026-11-12", instagram_followers=11) + rows("2026-11-16", instagram_followers=13)
    item = sm.summarize(data, date(2026, 11, 16))["items"][0]
    assert (item["label"], item["value"], item["weekChange"], item["comparedWith"]) == ("Instagram 追蹤", 13, 3, "2026-11-09")
    assert item["sinceFirst"] == 3


def test_without_a_week_of_history_the_change_is_unknown_not_zero():
    item = sm.summarize(rows("2026-11-16", threads_followers=3), date(2026, 11, 16))["items"][0]
    assert item["weekChange"] is None and item["sinceFirst"] is None


def test_platforms_whose_api_gives_no_numbers_are_listed_as_unavailable_not_guessed():
    reasons = {u["platform"] for u in sm.summarize([], date(2026, 11, 16))["unavailable"]}
    assert "linkedin" in reasons and "youtube_stats" in reasons


def test_database_keeps_one_value_per_day_platform_and_metric():
    db = sm.SocialMetricsDatabase(create_engine("sqlite://"))
    db.save("2026-11-16", [{"platform": "facebook", "metric": "followers", "value": 3}])
    db.save("2026-11-16", [{"platform": "facebook", "metric": "followers", "value": 4}])
    assert db.since("2026-11-01") == [{"day": "2026-11-16", "platform": "facebook", "metric": "followers", "value": 4.0}]


def test_collect_reads_each_platform_and_one_failure_does_not_blank_the_others(monkeypatch):
    from maya_sawa.services.social import meta, runner

    def call(client, method, endpoint, token, final=False, **fields):
        if "threads_insights" in endpoint:
            return {"data": [{"name": "followers_count", "total_value": {"value": 3}}, {"name": "views", "values": [{"value": 2}, {"value": 5}]}]}
        if endpoint.endswith("/ig1"):
            raise meta.Rejected("boom")
        return {"followers_count": 3, "fan_count": 2}
    monkeypatch.setattr(meta, "_call", call)
    monkeypatch.setattr(meta, "discover_page", lambda token, client=None: {"page_id": "p1", "instagram_id": "ig1", "page_token": "t"})
    monkeypatch.setattr(meta, "discover_threads_user", lambda token, client=None: "u1")
    monkeypatch.setattr(runner, "threads_token", lambda outbox: "tt")
    got = {(r["platform"], r["metric"]): r["value"] for r in sm.collect(object(), youtube_uploads=lambda: {"a": 1, "b": 2}, client=object(),
                                                                         env={"META_PAGE_ACCESS_TOKEN": "x"})}
    assert got == {("facebook", "followers"): 3, ("facebook", "fans"): 2, ("threads", "followers"): 3, ("threads", "views"): 7, ("youtube", "uploads"): 2}
