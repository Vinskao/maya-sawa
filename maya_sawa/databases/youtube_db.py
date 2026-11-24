"""Which daily readings are already on YouTube, and the latest episode's MP4 (docs/YOUTUBE_DAILY.md)."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, LargeBinary, Text, delete, select, text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class YoutubeUpload(Base):
    __tablename__ = 'maya_sawa_youtube_upload'
    day = Column(Text, primary_key=True)
    video_id = Column(Text, nullable=False)
    privacy = Column(Text, nullable=False)
    version = Column(Text, nullable=False, default='cover', server_default='cover')
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
            self._add_version_column(engine)

    @staticmethod
    def _add_version_column(engine):
        """Tables created before 2026-11-16 have no `version`; those uploads used the plain cover."""
        from sqlalchemy import inspect, text
        if 'version' not in {c['name'] for c in inspect(engine).get_columns('maya_sawa_youtube_upload')}:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE maya_sawa_youtube_upload ADD COLUMN version TEXT NOT NULL DEFAULT 'cover'"))

    def uploaded(self) -> dict:
        """day -> (video id, video version) of the newest upload for that day."""
        with self.sessions() as session:
            return {row.day: (row.video_id, row.version) for row in session.execute(select(YoutubeUpload)).scalars()}

    def record(self, day: str, video_id: str, privacy: str, title: str, version: str = "presenter-clips-1",
               now: datetime | None = None) -> None:
        with self.sessions.begin() as session:
            session.merge(YoutubeUpload(day=day, video_id=video_id, privacy=privacy, title=title, version=version,
                                        uploaded_at=now or datetime.now(timezone.utc)))

    def save_latest(self, day: str, mp4: bytes, now: datetime | None = None) -> None:
        created_at = now or datetime.now(timezone.utc)
        with self.sessions.begin() as session:
            connection = session.connection()
            if connection.dialect.name != "postgresql":
                session.execute(delete(YoutubeLatestVideo))
                session.add(YoutubeLatestVideo(day=day, mp4=mp4, created_at=created_at))
                return

            # psycopg2 expands bound bytea values into hex SQL literals. Stream the
            # video through a transaction-local large object to avoid that expansion.
            blob = connection.connection.driver_connection.lobject(mode="wb")
            oid = blob.oid
            chunk_size = 1024 * 1024
            try:
                for offset in range(0, len(mp4), chunk_size):
                    blob.write(mp4[offset:offset + chunk_size])
            finally:
                blob.close()
            session.execute(delete(YoutubeLatestVideo))
            session.execute(
                text("INSERT INTO maya_sawa_youtube_latest_video (day, mp4, created_at) "
                     "VALUES (:day, lo_get(:oid), :created_at)"),
                {"day": day, "oid": oid, "created_at": created_at},
            )
            session.execute(text("SELECT lo_unlink(:oid)"), {"oid": oid})

    def latest(self):
        with self.sessions() as session:
            row = session.execute(select(YoutubeLatestVideo)).scalars().first()
            return (row.day, row.mp4) if row else None
