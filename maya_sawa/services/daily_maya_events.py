"""No invented investor conferences in the daily reading (docs/DAILY_MAYA_BRIEF.md, 2026-11-16).

On 2026-11-16 the reading said "台積電今天早上九點法說，週三還有一場" although the event list (TDCC IR platform) only had 欣興 that
day. A sentence that says a tracked company holds a conference today, tomorrow or later this week must match the event list;
past conferences ("上週五的法說") are not checked because finished events leave the list.
"""
import re
from datetime import date, timedelta

CONFERENCE = "法說"
PRESENT_OR_FUTURE = re.compile(r"今天|今日|今早|明天|明日|後天|本週|這週|週[一二三四五六日]還有|將於|即將|稍後|預計")
PAST = re.compile(r"上週|上周|昨天|昨日|前天|日前|已於|先前")
NOISE = re.compile(r"小型|期貨|選擇權|\d+|\s")
WINDOW_DAYS = 7


def company_names(symbols: list[dict]) -> set[str]:
    """Plain company names of the tracked instruments ("小型創意期貨11" -> "創意")."""
    names = {NOISE.sub("", str(item.get("name") or "")) for item in symbols}
    return {name for name in names if len(name) >= 2}


def unlisted_conferences(content: str, day: str, names: set[str], events: list[dict]) -> list[str]:
    """Companies the text says hold a conference now or soon, with no investor conference in the event list within a week of `day`."""
    today = date.fromisoformat(day)
    listed = set()
    for event in events:
        if event.get("type") != "investor_conference":
            continue
        try:
            when = date.fromisoformat(str(event.get("date"))[:10])
        except ValueError:
            continue
        if abs((when - today).days) <= WINDOW_DAYS:
            listed.add(NOISE.sub("", str(event.get("name") or "")))
    missing = []
    for sentence in re.split(r"[。\n]", content):
        if CONFERENCE not in sentence:
            continue
        for name in sorted(names):
            if name not in sentence or name in listed or name in missing:
                continue
            # the claim is about now / the near future, and is tied to this company rather than to a past event
            segment = sentence[sentence.index(name):]
            head = segment.split(CONFERENCE)[0]
            if CONFERENCE in segment and PRESENT_OR_FUTURE.search(head) and not PAST.search(head):
                missing.append(name)
    return missing


def message(missing: list[str]) -> str:
    return ("事件清單（GET /market/dashboard/events）裡沒有這些公司近期的法說：" + "、".join(missing)
            + "。法說、財報等事件只能引用清單裡有的，不得憑印象或推測寫入；請刪除或改成清單上的事件後重新提交。")
