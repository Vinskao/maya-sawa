"""Follower and reach numbers of every social channel, snapshotted daily for the /palais dashboard (docs/AI_VISIBILITY.md, 2026-11-16).

Only what each platform's API returns with the tokens the publisher already holds (probed 2026-11-16): Facebook Page fans and
followers, Instagram followers and posts, Threads followers / views / likes / replies / reposts, and the number of episodes this
service uploaded to YouTube. LinkedIn's personal-profile follower count needs a scope the posting token does not have, so it is
reported as unavailable instead of guessed. One snapshot per Taipei day; the dashboard compares the latest with about a week before.
"""
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Column, Float, Text, select
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger(__name__)
TAIPEI = ZoneInfo("Asia/Taipei")
Base = declarative_base()
LABELS = {
    ("facebook", "followers"): "Facebook 粉專追蹤", ("facebook", "fans"): "Facebook 粉專按讚",
    ("instagram", "followers"): "Instagram 追蹤", ("instagram", "posts"): "Instagram 貼文數",
    ("threads", "followers"): "Threads 追蹤", ("threads", "views"): "Threads 瀏覽", ("threads", "likes"): "Threads 按讚",
    ("threads", "replies"): "Threads 回覆", ("threads", "reposts"): "Threads 轉發",
    ("youtube", "uploads"): "YouTube 已上傳集數",
}
UNAVAILABLE = {"linkedin": "LinkedIn 個人檔案的追蹤數需要額外的 API 權限，目前的發文權限讀不到",
               "youtube_stats": "YouTube 觀看與訂閱數需要 youtube.readonly 權限，目前只有上傳權限"}


class SocialMetric(Base):
    __tablename__ = "maya_sawa_social_metric"
    day = Column(Text, primary_key=True)
    platform = Column(Text, primary_key=True)
    metric = Column(Text, primary_key=True)
    value = Column(Float, nullable=False)


class SocialMetricsDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)

    def save(self, day: str, rows: list[dict]) -> None:
        with self.sessions.begin() as session:
            for row in rows:
                session.merge(SocialMetric(day=day, platform=row["platform"], metric=row["metric"], value=float(row["value"])))

    def since(self, day: str) -> list[dict]:
        with self.sessions() as session:
            rows = session.execute(select(SocialMetric).where(SocialMetric.day >= day)).scalars()
            return [{"day": r.day, "platform": r.platform, "metric": r.metric, "value": r.value} for r in rows]


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def collect(outbox, youtube_uploads=None, client=None, env=os.environ) -> list[dict]:
    """Today's numbers. A platform that fails is logged and skipped: one bad token must not blank the others."""
    import httpx
    from .social import meta
    from .social.runner import threads_token
    client = client or httpx.Client(timeout=30)
    rows = []

    def add(platform, metric, value):
        number = _number(value)
        if number is not None:
            rows.append({"platform": platform, "metric": metric, "value": number})

    page_token = (env.get("META_PAGE_ACCESS_TOKEN") or "").strip()
    if page_token:
        try:
            found = meta.discover_page(page_token, client)
            page = meta._call(client, "GET", f"{meta.GRAPH}/{found['page_id']}", found["page_token"], fields="fan_count,followers_count")
            add("facebook", "followers", page.get("followers_count"))
            add("facebook", "fans", page.get("fan_count"))
            if found.get("instagram_id"):
                ig = meta._call(client, "GET", f"{meta.GRAPH}/{found['instagram_id']}", found["page_token"], fields="followers_count,media_count")
                add("instagram", "followers", ig.get("followers_count"))
                add("instagram", "posts", ig.get("media_count"))
        except Exception as exc:
            logger.warning("Facebook / Instagram metrics unavailable: %s", type(exc).__name__)
    try:
        token = threads_token(outbox)
        if token:
            user = meta.discover_threads_user(token, client)
            data = meta._call(client, "GET", f"{meta.THREADS}/{user}/threads_insights", token,
                              metric="followers_count,views,likes,replies,reposts")["data"]
            for item in data:
                name = {"followers_count": "followers"}.get(item["name"], item["name"])
                total = (item.get("total_value") or {}).get("value")
                if total is None and item.get("values"):
                    total = sum(v.get("value") or 0 for v in item["values"])
                add("threads", name, total)
    except Exception as exc:
        logger.warning("Threads metrics unavailable: %s", type(exc).__name__)
    if youtube_uploads is not None:
        try:
            add("youtube", "uploads", len(youtube_uploads()))
        except Exception as exc:
            logger.warning("YouTube upload count unavailable: %s", type(exc).__name__)
    return rows


def summarize(snapshots: list[dict], today: date) -> dict:
    """Latest value of each metric with its change against the closest snapshot at least 7 days older (None until one exists)."""
    series: dict = {}
    for row in snapshots:
        series.setdefault((row["platform"], row["metric"]), {})[row["day"]] = row["value"]
    items = []
    for (platform, metric), days in sorted(series.items()):
        latest_day = max(days)
        cutoff = (date.fromisoformat(latest_day) - timedelta(days=7)).isoformat()
        earlier = [d for d in days if d <= cutoff]
        base_day = max(earlier) if earlier else None
        first_day = min(days)
        items.append({"platform": platform, "metric": metric, "label": LABELS.get((platform, metric), f"{platform} {metric}"),
                      "value": days[latest_day], "asOf": latest_day,
                      "weekChange": days[latest_day] - days[base_day] if base_day else None, "comparedWith": base_day,
                      "sinceFirst": days[latest_day] - days[first_day] if first_day != latest_day else None, "firstDay": first_day})
    return {"items": items, "unavailable": [{"platform": k, "reason": v} for k, v in UNAVAILABLE.items()], "today": today.isoformat()}


def snapshot_today(database, outbox, youtube_uploads=None, now=None) -> int:
    day = (now or datetime.now(TAIPEI)).astimezone(TAIPEI).date().isoformat()
    rows = collect(outbox, youtube_uploads)
    if rows:
        database.save(day, rows)
    return len(rows)
