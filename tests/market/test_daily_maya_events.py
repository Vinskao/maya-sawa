"""2026-11-16: the reading may only mention investor conferences that are in the event list (no invented events)."""
from maya_sawa.services import daily_maya_events as ev

NAMES = ev.company_names([{"name": "小型創意期貨11"}, {"name": "台積電期貨12"}, {"name": "聯發科"}, {"name": "欣興"}, {"name": "聯亞"}, {"name": ""}])
EVENTS = [{"code": "3037", "name": "欣興", "type": "investor_conference", "date": "2026-11-16"},
          {"code": "2454", "name": "聯發科", "type": "financial_release", "date": "2026-11-16"}]
DAY = "2026-11-16"


def test_instrument_names_are_reduced_to_company_names():
    assert NAMES == {"創意", "台積電", "聯發科", "欣興", "聯亞"}


def test_the_invented_tsmc_conference_of_1116_is_caught_and_the_real_one_is_not():
    text = "欣興今天早上八點十五分召開法說，內容我們還沒有取得。台積電今天早上九點法說，週三還有一場，內容尚未取得，盤中二千三百元。"
    assert ev.unlisted_conferences(text, DAY, NAMES, EVENTS) == ["台積電"]


def test_a_past_conference_is_not_checked_because_finished_events_leave_the_list():
    assert ev.unlisted_conferences("聯亞上週五的法說內容我們還沒有取得，今天盤中跌停。", DAY, NAMES, EVENTS) == []


def test_a_release_is_not_a_conference_and_a_far_away_event_does_not_count():
    assert ev.unlisted_conferences("聯發科明天召開法說。", DAY, NAMES, EVENTS) == ["聯發科"]
    far = [{"name": "創意", "type": "investor_conference", "date": "2026-12-20"}]
    assert ev.unlisted_conferences("創意今天下午法說。", DAY, NAMES, far) == ["創意"]


def test_talking_about_what_to_watch_in_a_listed_conference_is_fine_and_untracked_text_is_ignored():
    assert ev.unlisted_conferences("下一個驗證點，是欣興今天法說中載板良率的說法。", DAY, NAMES, EVENTS) == []
    assert ev.unlisted_conferences("市場本週關注多場法說。", DAY, NAMES, EVENTS) == []


def test_the_message_names_the_companies_and_the_rule():
    assert "台積電" in ev.message(["台積電"]) and "事件清單" in ev.message(["台積電"])
