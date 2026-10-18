"""Industry groups (族群) and stock entities for the Research tab, stored in Postgres.

A stock is an entity keyed by its record code (2330, 6857-JP, META-US) and is never deleted, so research and group
history survive it leaving the holdings. A group links stocks that share a supply chain, each with its role, and may
name an industry diagram (e.g. "power-rack") that the Research tab shows only for that group's members.
"""
import re
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Text, delete
from sqlalchemy.orm import declarative_base, sessionmaker

from .market_dashboard_db import market_dashboard_db

Base = declarative_base()
GROUP_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,47}$")
RECORD_CODE = re.compile(r"^[A-Z0-9]{1,12}(-[A-Z]{2})?$")
MARKETS = {"TW", "US", "JP", "KR", "HK"}


class MarketInstrument(Base):
    __tablename__ = "maya_sawa_market_instrument"
    record_code = Column(Text, primary_key=True)
    code = Column(Text, nullable=False)
    market = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MarketIndustryGroup(Base):
    __tablename__ = "maya_sawa_market_industry_group"
    id = Column(Text, primary_key=True)
    name_zh = Column(Text, nullable=False)
    name_en = Column(Text, nullable=False)
    diagram = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class MarketIndustryMember(Base):
    __tablename__ = "maya_sawa_market_industry_member"
    group_id = Column(Text, primary_key=True)
    record_code = Column(Text, primary_key=True)
    role = Column(Text, nullable=False, default="")
    position = Column(Integer, nullable=False, default=0)  # order within the group, as saved


def validate_group(group: dict) -> dict:
    """Check a group payload; raises ValueError with the first problem found."""
    if not isinstance(group, dict) or not GROUP_ID.match(str(group.get("id", ""))):
        raise ValueError("Group id must be a lowercase slug")
    name = group.get("name") or {}
    if not str(name.get("zh", "")).strip() or not str(name.get("en", "")).strip():
        raise ValueError("Group needs a zh and en name")
    if group.get("diagram") is not None and not GROUP_ID.match(str(group["diagram"])):
        raise ValueError("Diagram must be a slug")
    members = group.get("members")
    if not isinstance(members, list) or not members:
        raise ValueError("Group needs at least one member")
    for member in members:
        code = str(member.get("recordCode", ""))
        if not RECORD_CODE.match(code) or member.get("market") not in MARKETS or not str(member.get("name", "")).strip():
            raise ValueError(f"Invalid member {code!r}")
        if (member["market"] == "TW") != ("-" not in code):
            raise ValueError(f"Member {code} market does not match its record code")
    return group


class MarketIndustryDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def _require(self):
        if not self.sessions:
            raise RuntimeError("Industry database unavailable")

    def save_group(self, group: dict) -> dict:
        """Upsert a group, its members' stock entities and the membership rows (members not listed are unlinked)."""
        self._require()
        validate_group(group)
        now = datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            session.merge(MarketIndustryGroup(id=group["id"], name_zh=group["name"]["zh"].strip(), name_en=group["name"]["en"].strip(),
                                              diagram=group.get("diagram"), updated_at=now))
            session.execute(delete(MarketIndustryMember).where(MarketIndustryMember.group_id == group["id"]))
            for position, member in enumerate(group["members"]):
                code = member["recordCode"]
                session.merge(MarketInstrument(record_code=code, code=code.split("-")[0], market=member["market"],
                                               name=member["name"].strip(), updated_at=now))
                session.add(MarketIndustryMember(group_id=group["id"], record_code=code, role=str(member.get("role", "")).strip(),
                                                  position=position))
        return self.group(group["id"])

    def _group_dict(self, session, row) -> dict:
        members = (session.query(MarketIndustryMember, MarketInstrument)
                   .join(MarketInstrument, MarketInstrument.record_code == MarketIndustryMember.record_code)
                   .filter(MarketIndustryMember.group_id == row.id)
                   .order_by(MarketIndustryMember.position, MarketIndustryMember.record_code).all())
        return {"id": row.id, "name": {"zh": row.name_zh, "en": row.name_en}, "diagram": row.diagram,
                "updatedAt": row.updated_at.isoformat(),
                "members": [{"recordCode": inst.record_code, "code": inst.code, "market": inst.market, "name": inst.name, "role": member.role}
                            for member, inst in members]}

    def group(self, group_id: str) -> dict | None:
        self._require()
        with self.sessions() as session:
            row = session.get(MarketIndustryGroup, group_id)
            return self._group_dict(session, row) if row else None

    def list_groups(self) -> list[dict]:
        self._require()
        with self.sessions() as session:
            return [self._group_dict(session, row) for row in session.query(MarketIndustryGroup).order_by(MarketIndustryGroup.id).all()]

    def groups_for(self, record_code: str) -> list[dict]:
        self._require()
        with self.sessions() as session:
            ids = [row.group_id for row in session.query(MarketIndustryMember).filter_by(record_code=record_code).all()]
            rows = session.query(MarketIndustryGroup).filter(MarketIndustryGroup.id.in_(ids)).order_by(MarketIndustryGroup.id).all() if ids else []
            return [self._group_dict(session, row) for row in rows]

    def instrument(self, record_code: str) -> dict | None:
        self._require()
        with self.sessions() as session:
            row = session.get(MarketInstrument, record_code)
            return {"recordCode": row.record_code, "code": row.code, "market": row.market, "name": row.name} if row else None


market_industry_db = MarketIndustryDatabase(market_dashboard_db.engine)
