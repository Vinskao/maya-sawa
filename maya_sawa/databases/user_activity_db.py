"""Site users (by Keycloak `sub`) and an append-only log of what each one created, read, updated or deleted.

Keycloak stays the identity provider: this table only remembers a user name and when the person was first and last seen, so the
owner can read "who is this, and what did they do" without the Keycloak admin console. No email, password or token is stored.
"""
import json
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Text, func
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
ACTIONS = ("C", "R", "U", "D")  # create, read, update, delete
DETAIL_LIMIT = 1000


class SiteUser(Base):
    __tablename__ = "maya_sawa_user"
    sub = Column(Text, primary_key=True)
    username = Column(Text, nullable=False, default="")
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)


class UserActivity(Base):
    __tablename__ = "maya_sawa_user_activity"
    id = Column(Integer, primary_key=True, autoincrement=True)
    sub = Column(Text, nullable=False, index=True)
    username = Column(Text, nullable=False, default="")
    action = Column(Text, nullable=False)  # C | R | U | D
    resource_type = Column(Text, nullable=False)
    resource_id = Column(Text, nullable=False, default="")
    detail = Column(Text, nullable=False, default="")
    request_id = Column(Text, nullable=False, default="")
    at = Column(DateTime(timezone=True), nullable=False, index=True)


def _iso(value):
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).isoformat()


class UserActivityDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def _require(self):
        if not self.sessions:
            raise RuntimeError("User activity database unavailable")

    def touch_user(self, sub: str, username: str = "", now: datetime | None = None) -> None:
        self._require()
        if not sub:
            raise ValueError("A user id is required")
        now = now or datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            row = session.get(SiteUser, sub)
            if row is None:
                session.add(SiteUser(sub=sub, username=(username or "")[:120], first_seen_at=now, last_seen_at=now))
            else:
                row.last_seen_at = now
                if username:
                    row.username = username[:120]

    def record(self, sub: str, username: str, action: str, resource_type: str, resource_id: str = "",
               detail: dict | None = None, request_id: str = "", now: datetime | None = None) -> int:
        """Append one row. The log is append-only: nothing in the application updates or deletes it."""
        self._require()
        if not sub:
            raise ValueError("A user id is required")
        if action not in ACTIONS:
            raise ValueError("Action must be one of C, R, U, D")
        text = json.dumps(detail, ensure_ascii=False, default=str) if detail else ""
        if len(text) > DETAIL_LIMIT:
            text = json.dumps({"truncated": text[:DETAIL_LIMIT - 40]}, ensure_ascii=False)
        with self.sessions.begin() as session:
            row = UserActivity(sub=sub, username=(username or "")[:120], action=action, resource_type=(resource_type or "")[:60],
                               resource_id=(resource_id or "")[:200], detail=text, request_id=(request_id or "")[:80],
                               at=now or datetime.now(timezone.utc))
            session.add(row)
            session.flush()
            return row.id

    @staticmethod
    def _activity(row: UserActivity) -> dict:
        try:
            detail = json.loads(row.detail) if row.detail else None
        except ValueError:
            detail = {"raw": row.detail}
        return {"id": row.id, "sub": row.sub, "username": row.username, "action": row.action, "resourceType": row.resource_type,
                "resourceId": row.resource_id, "detail": detail, "requestId": row.request_id, "at": _iso(row.at)}

    def activity(self, sub: str | None = None, limit: int = 100, before_id: int | None = None) -> list[dict]:
        self._require()
        with self.sessions() as session:
            query = session.query(UserActivity)
            if sub:
                query = query.filter(UserActivity.sub == sub)
            if before_id:
                query = query.filter(UserActivity.id < before_id)
            rows = query.order_by(UserActivity.at.desc(), UserActivity.id.desc()).limit(max(1, min(limit, 500))).all()
            return [self._activity(row) for row in rows]

    def users(self, limit: int = 200) -> list[dict]:
        self._require()
        with self.sessions() as session:
            counts = dict(session.query(UserActivity.sub, func.count(UserActivity.id)).group_by(UserActivity.sub).all())
            rows = session.query(SiteUser).order_by(SiteUser.last_seen_at.desc()).limit(max(1, min(limit, 1000))).all()
            return [{"sub": row.sub, "username": row.username, "firstSeenAt": _iso(row.first_seen_at),
                     "lastSeenAt": _iso(row.last_seen_at), "activityCount": int(counts.get(row.sub, 0))} for row in rows]

    def usernames(self, subs: list[str]) -> dict[str, str]:
        self._require()
        if not subs:
            return {}
        with self.sessions() as session:
            return {row.sub: row.username for row in session.query(SiteUser).filter(SiteUser.sub.in_(list(set(subs)))).all()}


def _default_db():
    from .market_dashboard_db import market_dashboard_db
    return UserActivityDatabase(market_dashboard_db.engine)


user_activity_db = _default_db()
