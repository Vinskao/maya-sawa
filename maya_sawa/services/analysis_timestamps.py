"""Daily OpenTimestamps proofs for AI analysis revisions.

Each Taipei day, the revisions written that day are listed by hash in a small JSON manifest. The manifest's SHA-256 goes
to public OpenTimestamps calendars, which batch it into a Bitcoin transaction for free; a few hours later the calendar
returns the path to that Bitcoin block. Anyone holding the manifest and its .ots proof can check at opentimestamps.org
that the day's analyses existed, unchanged, before that block. The proof shows when, not who or whether it was right.

The .ots format is parsed here (no extra dependency): a timestamp is a tree of operations (append, prepend, sha256, ...)
from the digest to attestations (pending at a calendar, or a Bitcoin block height). See docs/ANALYSIS_TIMESTAMPS.md.
"""
import asyncio
import hashlib
import io
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TAIPEI = ZoneInfo("Asia/Taipei")
SCHEMA = "maya-sawa/ai-analysis-day/v1"
HEADER = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94" + b"\x01"   # magic, then major version 1
CALENDARS = ("https://a.pool.opentimestamps.org", "https://b.pool.opentimestamps.org", "https://a.pool.eternitywall.com")
CALENDAR_HOSTS = (".opentimestamps.org", ".eternitywall.com")
PENDING = bytes.fromhex("83dfe30d2ef90c8e")
BITCOIN = bytes.fromhex("0588960d73d71901")
SHA256 = 0x08
BINARY_OPS = {0xf0: lambda msg, arg: msg + arg, 0xf1: lambda msg, arg: arg + msg}
UNARY_OPS = {0x08: lambda msg: hashlib.sha256(msg).digest(), 0x02: lambda msg: hashlib.sha1(msg).digest(),
             0x03: lambda msg: hashlib.new("ripemd160", msg).digest(), 0xf2: lambda msg: msg[::-1], 0xf3: lambda msg: msg.hex().encode()}


@dataclass
class Timestamp:
    """One node: attestations about the message here, and operations leading to child nodes. Order is kept as read."""
    attestations: list = field(default_factory=list)   # (8-byte tag, payload bytes)
    ops: list = field(default_factory=list)            # (op tag, argument bytes or None, Timestamp)


def _read_varuint(stream) -> int:
    value, shift = 0, 0
    while True:
        byte = stream.read(1)
        if not byte:
            raise ValueError("truncated proof")
        value |= (byte[0] & 0x7f) << shift
        if not byte[0] & 0x80:
            return value
        shift += 7


def _varuint(value: int) -> bytes:
    out = bytearray()
    while True:
        out.append((value & 0x7f) | (0x80 if value > 0x7f else 0))
        value >>= 7
        if not value:
            return bytes(out)


def _read_varbytes(stream, limit=8192) -> bytes:
    length = _read_varuint(stream)
    if length > limit:
        raise ValueError("proof field too long")
    data = stream.read(length)
    if len(data) != length:
        raise ValueError("truncated proof")
    return data


def parse_timestamp(stream, depth=0) -> Timestamp:
    if depth > 256:
        raise ValueError("proof too deep")
    node = Timestamp()
    while True:
        tag = stream.read(1)
        if not tag:
            raise ValueError("truncated proof")
        more = tag == b"\xff"
        if more:
            tag = stream.read(1)
        if tag == b"\x00":
            node.attestations.append((stream.read(8), _read_varbytes(stream)))
        elif tag[0] in BINARY_OPS:
            node.ops.append((tag[0], _read_varbytes(stream), parse_timestamp(stream, depth + 1)))
        elif tag[0] in UNARY_OPS or tag[0] == 0x67:
            node.ops.append((tag[0], None, parse_timestamp(stream, depth + 1)))
        else:
            raise ValueError(f"unknown proof operation {tag.hex()}")
        if not more:
            return node


def serialize(node: Timestamp) -> bytes:
    items = [b"\x00" + tag + _varuint(len(payload)) + payload for tag, payload in node.attestations]
    items += [bytes([op]) + (b"" if arg is None else _varuint(len(arg)) + arg) + serialize(child) for op, arg, child in node.ops]
    if not items:
        raise ValueError("empty timestamp")
    return b"".join(b"\xff" + item for item in items[:-1]) + items[-1]


def read_proof(raw: bytes) -> tuple[bytes, Timestamp]:
    """A detached .ots file over a SHA-256 file digest: (digest, timestamp)."""
    if not raw.startswith(HEADER) or raw[len(HEADER)] != SHA256:
        raise ValueError("not a SHA-256 OpenTimestamps proof")
    stream = io.BytesIO(raw[len(HEADER) + 1:])
    digest = stream.read(32)
    node = parse_timestamp(stream)
    if stream.read(1):
        raise ValueError("trailing bytes after proof")
    return digest, node


def write_proof(digest: bytes, node: Timestamp) -> bytes:
    return HEADER + bytes([SHA256]) + digest + serialize(node)


def merge(nodes: list[Timestamp]) -> Timestamp:
    """Timestamps for the same message, from several calendars, become one node with every path."""
    return Timestamp(attestations=[a for node in nodes for a in node.attestations], ops=[o for node in nodes for o in node.ops])


def pending_attestation(uri: str) -> tuple[bytes, bytes]:
    encoded = uri.encode()
    return PENDING, _varuint(len(encoded)) + encoded


def _apply(op: int, arg: bytes | None, message: bytes) -> bytes:
    if op in BINARY_OPS:
        return BINARY_OPS[op](message, arg)
    if op == 0x67:
        raise ValueError("keccak256 is not supported")
    return UNARY_OPS[op](message)


def _walk(node: Timestamp, message: bytes):
    yield node, message
    for op, arg, child in node.ops:
        yield from _walk(child, _apply(op, arg, message))


def pending_calendars(node: Timestamp, message: bytes) -> list[tuple[str, bytes]]:
    """(calendar URI, commitment to ask it about) for every attestation still waiting on Bitcoin."""
    return [(_read_varbytes(io.BytesIO(payload)).decode(), at) for here, at in _walk(node, message)
            for tag, payload in here.attestations if tag == PENDING]


def bitcoin_heights(node: Timestamp, message: bytes) -> list[int]:
    return sorted({_read_varuint(io.BytesIO(payload)) for here, _ in _walk(node, message) for tag, payload in here.attestations if tag == BITCOIN})


def upgrade(node: Timestamp, message: bytes, fetch) -> bool:
    """Ask each pending calendar for the rest of its path; a confirmed one replaces its pending attestation."""
    changed = False
    for here, at in list(_walk(node, message)):
        for attestation in list(here.attestations):
            if attestation[0] != PENDING:
                continue
            uri = _read_varbytes(io.BytesIO(attestation[1])).decode()
            raw = fetch(uri, at)
            if not raw:
                continue
            extra = parse_timestamp(io.BytesIO(raw))
            if not bitcoin_heights(extra, at):
                continue                                  # still pending at that calendar
            here.attestations.remove(attestation)
            here.attestations += extra.attestations
            here.ops += extra.ops
            changed = True
    return changed


def calendar_allowed(uri: str) -> bool:
    parts = urllib.parse.urlsplit(uri)
    return (parts.scheme == "https" and parts.hostname is not None and parts.port is None and not parts.username
            and parts.netloc == parts.hostname and parts.hostname.endswith(CALENDAR_HOSTS))


def _calendar_request(url: str, data: bytes | None = None) -> bytes | None:
    request = urllib.request.Request(url, data=data, headers={"User-Agent": "maya-sawa analysis timestamps",
                                                              "Accept": "application/vnd.opentimestamps.v1"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.read(65536)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None                                   # not in a Bitcoin block yet
        raise


def submit_digest(uri: str, digest: bytes) -> bytes:
    if not calendar_allowed(uri):
        raise ValueError("calendar not allowed")
    return _calendar_request(f"{uri}/digest", digest) or b""


def fetch_upgrade(uri: str, commitment: bytes) -> bytes | None:
    if not calendar_allowed(uri):
        return None
    return _calendar_request(f"{uri}/timestamp/{commitment.hex()}")


def revision_hash(row: dict) -> str:
    """SHA-256 of a revision exactly as GET /market/dashboard/analysis/{code} publishes it."""
    fields = {key: row[key] for key in ("code", "content", "model", "productType", "revision", "updatedAt")}
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def day_manifest(day: date, rows: list[dict]) -> bytes:
    revisions = sorted(({"productType": row["productType"], "code": row["code"], "revision": row["revision"],
                         "updatedAt": row["updatedAt"], "sha256": revision_hash(row)} for row in rows),
                       key=lambda r: (r["productType"], r["code"], r["revision"]))
    body = {"schema": SCHEMA, "day": day.isoformat(), "timezone": "Asia/Taipei", "revisions": revisions}
    return json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(), TAIPEI).astimezone(UTC)
    return start, start + timedelta(days=1)


def stamp_day(database, day: date, submit=submit_digest) -> dict | None:
    """Stamp one Taipei day's revisions; None when the day is already stamped or nothing was written."""
    if database.get(day.isoformat()):
        return None
    rows = database.revisions_between(*day_window(day))
    if not rows:
        return None
    manifest = day_manifest(day, rows)
    digest = hashlib.sha256(manifest).digest()
    answers = []
    for uri in CALENDARS:
        try:
            answers.append(parse_timestamp(io.BytesIO(submit(uri, digest))))
        except Exception as exc:
            logger.warning("OpenTimestamps calendar %s failed: %s", uri, str(exc)[:80])
    if not answers:
        raise RuntimeError("no calendar accepted the digest")
    record = {"day": day.isoformat(), "digest": digest.hex(), "manifest": manifest.decode(), "revisionCount": len(rows),
              "proof": write_proof(digest, merge(answers)), "status": "pending", "bitcoinHeight": None,
              "calendars": len(answers), "submittedAt": datetime.now(UTC)}
    database.save(record)
    return record


def check_pending(database, fetch=fetch_upgrade) -> int:
    """Upgrade waiting proofs; returns how many days reached a Bitcoin block."""
    confirmed = 0
    for record in database.pending():
        digest, node = read_proof(record["proof"])
        try:
            changed = upgrade(node, digest, fetch)
        except Exception as exc:
            logger.warning("OpenTimestamps upgrade for %s failed: %s", record["day"], str(exc)[:80])
            continue
        heights = bitcoin_heights(node, digest)
        fields = {"checkedAt": datetime.now(UTC)}
        if changed:
            fields["proof"] = write_proof(digest, node)
        if heights:
            fields.update(status="confirmed", bitcoinHeight=heights[0])
            confirmed += 1
        database.update(record["day"], **fields)
    return confirmed


class AnalysisTimestamper:
    """Hourly: stamp yesterday (Taipei) once, and ask the calendars about proofs still waiting on Bitcoin."""

    def __init__(self, database_factory):
        self._database_factory = database_factory
        self._task: asyncio.Task | None = None

    async def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="analysis-timestamps")

    async def close(self):
        if self._task:
            self._task.cancel()
            self._task = None

    def run_once(self) -> dict:
        database = self._database_factory()
        if not database.sessions:
            return {}
        yesterday = datetime.now(TAIPEI).date() - timedelta(days=1)
        stamped = stamp_day(database, yesterday)
        return {"stamped": stamped["day"] if stamped else None, "confirmed": check_pending(database)}

    async def _loop(self):
        await asyncio.sleep(120)
        while True:
            try:
                logger.info("Analysis timestamps: %s", await asyncio.to_thread(self.run_once))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Analysis timestamping failed")
            await asyncio.sleep(3600)


def _database():
    from ..databases.analysis_timestamp_db import analysis_timestamp_db
    return analysis_timestamp_db


analysis_timestamper = AnalysisTimestamper(_database)
