"""LinkedIn alert parsing and durable application state."""
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit

from sqlalchemy import Column, DateTime, MetaData, Table, Text, insert, select, update
from sqlalchemy.exc import IntegrityError

metadata = MetaData()
messages = Table("maya_linkedin_job_mail", metadata, Column("id", Text, primary_key=True))
jobs = Table(
    "maya_linkedin_job", metadata,
    Column("id", Text, primary_key=True),
    Column("title", Text, nullable=False),
    Column("company", Text),
    Column("location", Text),
    Column("mail_id", Text, nullable=False),
    Column("received", Text),
    Column("status", Text, nullable=False),
    Column("identity", Text, unique=True),
    Column("note", Text),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


def linkedin_id(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in {"www.linkedin.com", "linkedin.com"}:
        return None
    match = re.fullmatch(r"/(?:comm/)?jobs/view/([0-9]+)/?", parsed.path)
    return match[1] if match else None


class JobLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.jobs = {}
        self.job_id = None
        self.label = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.job_id = linkedin_id(dict(attrs).get("href") or "")
            self.label = []

    def handle_data(self, data):
        if self.job_id:
            self.label.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.job_id:
            title = " ".join("".join(self.label).split())
            if title:
                self.jobs.setdefault(self.job_id, {"id": self.job_id, "title": title[:500]})
            self.job_id = None


def parse_alert(body, html=True):
    if html:
        parser = JobLinks()
        parser.feed(body)
        return list(parser.jobs.values())
    found = {}
    for block in re.split(r"(?m)^-{5,}\s*$", body):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if not line.startswith("View job: "):
                continue
            job_id = linkedin_id(line.removeprefix("View job: ").strip())
            details = [text for text in lines[:index] if text != "Apply with resume & profile"]
            if job_id and len(details) >= 3:
                title, company, location = details[-3:]
                found[job_id] = dict(id=job_id, title=title[:500], company=company[:250], location=location[:250])
    return list(found.values())


class JobQueue:
    def __init__(self, engine):
        self.engine = engine
        metadata.create_all(engine)

    def seen(self, mail_id):
        with self.engine.connect() as conn:
            return conn.scalar(select(messages.c.id).where(messages.c.id == mail_id)) is not None

    def ingest(self, mail_id, entries, received=None):
        try:
            with self.engine.begin() as conn:
                conn.execute(insert(messages).values(id=mail_id))
                for entry in entries:
                    try:
                        with conn.begin_nested():
                            conn.execute(insert(jobs).values(
                                **entry, mail_id=mail_id, received=received,
                                status="pending", updated_at=datetime.now(timezone.utc),
                            ))
                    except IntegrityError:
                        if conn.scalar(select(jobs.c.id).where(jobs.c.id == entry["id"])) is None:
                            raise
        except IntegrityError:
            if not self.seen(mail_id):
                raise

    def list(self):
        with self.engine.connect() as conn:
            return [dict(row) for row in conn.execute(
                select(jobs).order_by(jobs.c.received.desc(), jobs.c.id.desc())
            ).mappings()]

    def transition(self, job_id, before, after, **values):
        try:
            with self.engine.begin() as conn:
                result = conn.execute(update(jobs).where(jobs.c.id == job_id, jobs.c.status == before)
                                      .values(status=after, updated_at=datetime.now(timezone.utc), **values))
                return result.rowcount == 1
        except IntegrityError:
            if "identity" not in values:
                raise
            return False

    def claim(self):
        with self.engine.begin() as conn:
            candidate = select(jobs.c.id).where(jobs.c.status == "approved").order_by(jobs.c.id).limit(1)
            row = conn.execute(
                update(jobs).where(jobs.c.id == candidate.scalar_subquery(), jobs.c.status == "approved")
                .values(status="claimed", updated_at=datetime.now(timezone.utc)).returning(*jobs.c)
            ).mappings().first()
            return dict(row) if row else None
