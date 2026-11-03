"""The AI watch list: stocks the analyst finds while reading research reports. A nomination needs support from more
than one report (or an explicit high-conviction call) to enter the custom area, stays while reports keep mentioning
it, leaves when neglected, becomes a normal holding when bought, and can come back after it is sold."""
from datetime import datetime, timedelta, timezone

from maya_sawa.services import market_watch as watch

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


def days(n):
    return (NOW - timedelta(days=n)).isoformat()


def mention(source, ago=0, conviction="normal", reason="報告指出訂單能見度提高到 2027 年"):
    return {"at": days(ago), "source": source, "conviction": conviction, "reason": reason}


def row(code, mentions, status="candidate", promoted_ago=None, name=None):
    return {"code": code, "market": "TW", "name": name or code, "status": status, "mentions": mentions,
            "promotedAt": days(promoted_ago) if promoted_ago is not None else None}


def status_of(rows, code):
    return next(item["status"] for item in rows if item["code"] == code)


def test_two_different_reports_within_three_weeks_put_a_candidate_in_the_custom_area():
    rows = watch.evaluate([row("3711", [mention("r1", 10), mention("r2", 2)])], held=set(), now=NOW)
    assert status_of(rows, "3711") == "watching" and rows[0]["promotedAt"] == NOW.isoformat()


def test_one_report_is_not_enough_and_the_same_report_mentioned_twice_still_counts_once():
    rows = watch.evaluate([row("3711", [mention("r1", 10), mention("r1", 1)])], held=set(), now=NOW)
    assert status_of(rows, "3711") == "candidate"


def test_a_second_report_older_than_the_window_does_not_count():
    rows = watch.evaluate([row("3711", [mention("r1", 40), mention("r2", 1)])], held=set(), now=NOW)
    assert status_of(rows, "3711") == "candidate"


def test_a_single_high_conviction_call_is_enough():
    rows = watch.evaluate([row("3711", [mention("r1", 3, conviction="high")])], held=set(), now=NOW)
    assert status_of(rows, "3711") == "watching"


def test_a_watched_stock_stays_while_mentioned_and_leaves_when_neglected_for_thirty_days():
    stays = row("3711", [mention("r1", 40), mention("r2", 29)], status="watching", promoted_ago=40)
    leaves = row("2330", [mention("r1", 40), mention("r2", 31)], status="watching", promoted_ago=40)
    rows = watch.evaluate([stays, leaves], held=set(), now=NOW)
    assert (status_of(rows, "3711"), status_of(rows, "2330")) == ("watching", "expired")


def test_a_new_mention_renews_a_watched_stock():
    old = row("3711", [mention("r1", 50), mention("r2", 45), mention("r3", 1)], status="watching", promoted_ago=50)
    assert status_of(watch.evaluate([old], held=set(), now=NOW), "3711") == "watching"


def test_an_expired_stock_comes_back_once_reports_mention_it_again():
    rows = watch.evaluate([row("3711", [mention("r1", 90), mention("r8", 5), mention("r9", 1)], status="expired")], held=set(), now=NOW)
    assert status_of(rows, "3711") == "watching"


def test_only_three_fit_and_the_most_recently_mentioned_win():
    candidates = [row(code, [mention("a", 20 - index), mention("b", 10 - index)]) for index, code in enumerate(["1101", "1102", "1103", "1104"])]
    rows = watch.evaluate(candidates, held=set(), now=NOW)
    assert [item["code"] for item in rows if item["status"] == "watching"] == ["1102", "1103", "1104"]
    assert status_of(rows, "1101") == "candidate"  # waits, is not discarded


def test_a_newcomer_replaces_the_most_neglected_one_only_after_the_minimum_stay():
    def full(promoted_ago):
        return [row(code, [mention("a", 25 + index), mention("b", 24 + index)], status="watching", promoted_ago=promoted_ago)
                for index, code in enumerate(["1101", "1102", "1103"])]
    newcomer = row("3711", [mention("x", 2), mention("y", 1)])
    protected = watch.evaluate([*full(promoted_ago=3), newcomer], held=set(), now=NOW)
    assert status_of(protected, "3711") == "candidate"
    swapped = watch.evaluate([*full(promoted_ago=20), newcomer], held=set(), now=NOW)
    assert status_of(swapped, "3711") == "watching" and status_of(swapped, "1103") == "candidate"  # 1103: neglected longest


def test_buying_it_makes_it_a_normal_holding_and_selling_it_lets_it_return_through_the_usual_rules():
    watched = row("3711", [mention("r1", 12), mention("r2", 3)], status="watching", promoted_ago=12)
    bought = watch.evaluate([watched], held={"3711"}, now=NOW)
    assert status_of(bought, "3711") == "held" and watch.visible(bought) == []
    sold = watch.evaluate(bought, held=set(), now=NOW)
    assert status_of(sold, "3711") == "watching"  # still supported by recent reports, so it is back in the custom area
    stale = watch.evaluate([row("2330", [mention("r1", 80)], status="held")], held=set(), now=NOW)
    assert status_of(stale, "2330") == "candidate"  # sold, but nobody mentions it any more


def test_visible_rows_carry_the_reason_the_expiry_and_how_long_they_have_stayed():
    rows = watch.evaluate([row("3711", [mention("r1", 12), mention("r2", 3, reason="CoWoS 產能 2027 年再擴")], name="日月光投控")], held=set(), now=NOW)
    shown = watch.visible(rows)
    assert shown == [{"code": "3711", "market": "TW", "name": "日月光投控", "productType": "stock", "source": "ai-watch",
                      "reason": "CoWoS 產能 2027 年再擴", "reports": 2, "since": NOW.isoformat(),
                      "expiresAt": (NOW - timedelta(days=3) + timedelta(days=30)).isoformat()}]


def test_nominate_merges_into_the_stored_mentions_and_ignores_a_repeat_of_the_same_report_on_the_same_day():
    start = []
    once = watch.nominate(start, "3711", "TW", "日月光投控", mention("r1", 0), now=NOW)
    again = watch.nominate(once, "3711", "TW", "日月光投控", mention("r1", 0), now=NOW)
    other = watch.nominate(again, "3711", "TW", "日月光投控", mention("r2", 0, reason="新理由"), now=NOW)
    assert len(once[0]["mentions"]) == 1 and len(again[0]["mentions"]) == 1 and len(other[0]["mentions"]) == 2
    assert other[0]["status"] == "watching"


def test_repeating_a_nomination_with_higher_conviction_firms_up_the_same_mention():
    once = watch.nominate([], "3711", "TW", "日月光投控", mention("r1", 0), now=NOW)
    assert once[0]["status"] == "candidate"
    firmer = watch.nominate(once, "3711", "TW", "日月光投控", mention("r1", 0, conviction="high", reason="這次報告明確給出 2027 年訂單"), now=NOW)
    assert len(firmer[0]["mentions"]) == 1 and firmer[0]["status"] == "watching"
    assert firmer[0]["mentions"][0]["reason"].startswith("這次報告")
