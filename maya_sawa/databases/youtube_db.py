"""Which daily readings are already on YouTube, and the latest episode's MP4 (docs/YOUTUBE_DAILY.md)."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, LargeBinary, Text, delete, select
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class YoutubeUpload(Base):
    __tablename__ = 'maya_sawa_youtube_upload'
    day = Column(Text, primary_key=True)
    video_id = Column(Text, nullable=False)
    privacy = Column(Text, nullable=False)
    title = Column(Text, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), nullable=False)


class YoutubeLatestVideo(Base):
    """Exactly one row: the newest episode's MP4, replaced on every upload (older MP4s are never kept)."""
    __tablename__ = 'maya_sawa_youtube_latest_video'
    day = Column(Text, primary_key=True)
    mp4 = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class YoutubeDatabase:
    def __init__(self, engine):
        self.sessions = sessionmaker(bind=engine) if engine else None
        if engine:
            Base.metadata.create_all(engine)

    def uploaded(self) -> dict:
        """day -> YouTube video id."""
        with self.sessions() as session:
            return {row.day: row.video_id for row in session.execute(select(YoutubeUpload)).scalars()}

    def record(self, day: str, video_id: str, privacy: str, title: str, now: datetime | None = None) -> None:
        with self.sessions.begin() as session:
            session.merge(YoutubeUpload(day=day, video_id=video_id, privacy=privacy, title=title,
                                        uploaded_at=now or datetime.now(timezone.utc)))

    def save_latest(self, day: str, mp4: bytes, now: datetime | None = None) -> None:
        with self.sessions.begin() as session:
            session.execute(delete(YoutubeLatestVideo))
            session.add(YoutubeLatestVideo(day=day, mp4=mp4, created_at=now or datetime.now(timezone.utc)))

    def latest(self):
        with self.sessions() as session:
            row = session.execute(select(YoutubeLatestVideo)).scalars().first()
            return (row.day, row.mp4) if row else None
