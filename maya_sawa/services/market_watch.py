"""The AI watch list: Taiwan stocks the analyst finds while reading research reports, shown in the dashboard's custom area.

A nomination is one dated mention (which report, why, how sure). The lifecycle is pure so it can be tested:

  candidate -> watching   two different reports within PROMOTE_WINDOW_DAYS, or one high-conviction call
  watching  -> expired    nothing has mentioned it for TTL_DAYS (the reports moved on)
  watching/candidate -> held   the owner bought it (it is now a normal automatic position)
  held -> candidate       the owner sold it; it returns through the usual rules if reports still support it
  expired   -> watching   reports mention it again

Only SLOTS stocks are shown at a time. A newcomer replaces the most neglected one, but not before it has stayed MIN_STAY_DAYS.
"""
from datetime import datetime, timedelta, timezone

PROMOTE_SOURCES = 2
PROMOTE_WINDOW_DAYS = 21
TTL_DAYS = 30
MIN_STAY_DAYS = 7
SLOTS = 3


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def last_mentioned(row: dict) -> datetime:
    return max(_time(item["at"]) for item in row["mentions"])


def _supported(row: dict, now: datetime) -> bool:
    recent = [item for item in row["mentions"] if _time(item["at"]) >= now - timedelta(days=PROMOTE_WINDOW_DAYS)]
    return len({item["source"] for item in recent}) >= PROMOTE_SOURCES or any(item.get("conviction") == "high" for item in recent)


def _rank(row: dict):
    return (-last_mentioned(row).timestamp(), -len({item["source"] for item in row["mentions"]}), row["code"])


def evaluate(rows: list[dict], held: set[str], now: datetime) -> list[dict]:
    rows = [{**row, "mentions": list(row["mentions"])} for row in rows]
    for row in rows:
        if row["code"] in held:
            row["status"], row["promotedAt"] = "held", None
        elif row["status"] == "held":  # sold: it is a candidate again and returns if reports still support it
            row["status"], row["promotedAt"] = "candidate", None
        elif row["status"] == "watching" and now - last_mentioned(row) > timedelta(days=TTL_DAYS):
            row["status"], row["promotedAt"] = "expired", None
    watching = [row for row in rows if row["status"] == "watching"]
    waiting = sorted((row for row in rows if row["status"] in ("candidate", "expired") and _supported(row, now)), key=_rank)
    for newcomer in waiting:
        if len(watching) < SLOTS:
            slot = None
        else:
            settled = [row for row in watching if now - _time(row["promotedAt"]) >= timedelta(days=MIN_STAY_DAYS)]
            slot = min(settled, key=last_mentioned, default=None)
            if slot is None or last_mentioned(newcomer) <= last_mentioned(slot):
                continue
            slot["status"], slot["promotedAt"] = "candidate", None
            watching.remove(slot)
        newcomer["status"], newcomer["promotedAt"] = "watching", now.isoformat()
        watching.append(newcomer)
    return rows


def visible(rows: list[dict]) -> list[dict]:
    """What the dashboard's custom area shows: the watched stocks, with why they are there and when they would leave."""
    shown = []
    for row in rows:
        if row["status"] != "watching":
            continue
        latest = max(row["mentions"], key=lambda item: _time(item["at"]))
        shown.append({"code": row["code"], "market": row["market"], "name": row.get("name") or row["code"], "productType": "stock",
                      "source": "ai-watch", "reason": latest["reason"], "reports": len({item["source"] for item in row["mentions"]}),
                      "since": row["promotedAt"], "expiresAt": (last_mentioned(row) + timedelta(days=TTL_DAYS)).isoformat()})
    return shown


def nominate(rows: list[dict], code: str, market: str, name: str, mention: dict, now: datetime, held: set[str] = frozenset()) -> list[dict]:
    """Record one mention (the same report on the same day counts once), then re-evaluate the whole list."""
    rows = [{**row, "mentions": list(row["mentions"])} for row in rows]
    row = next((item for item in rows if item["code"] == code and item["market"] == market), None)
    if row is None:
        row = {"code": code, "market": market, "name": name, "status": "candidate", "mentions": [], "promotedAt": None}
        rows.append(row)
    if name:
        row["name"] = name
    same = next((item for item in row["mentions"] if item["source"] == mention["source"] and item["at"][:10] == mention["at"][:10]), None)
    if same is None:
        row["mentions"].append(mention)
    elif mention.get("conviction") == "high" and same.get("conviction") != "high":
        same["conviction"], same["reason"] = "high", mention["reason"]  # the analyst firmed up the same call
    return evaluate(rows, set(held), now)


def merge_into_custom(custom_rows: list[dict], watched: list[dict], taken: set[tuple[str, str]]) -> list[dict]:
    """The owner's own picks come first; a watched stock already shown (or already a holding) is not added twice."""
    shown = {(row.get("productType"), str(row["code"]).upper()) for row in custom_rows} | set(taken)
    merged = list(custom_rows)
    for row in watched:
        key = (row.get("productType"), str(row["code"]).upper())
        if key not in shown:
            shown.add(key)
            merged.append(row)
    return merged
