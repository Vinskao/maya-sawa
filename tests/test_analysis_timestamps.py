"""Daily OpenTimestamps proofs for AI analysis revisions.

Fixtures: hello-world.txt(.ots) is the OpenTimestamps client's own example (Bitcoin block 358391); calendar-*.bin are real
2026-10-28 responses of three public calendars to POST /digest for sha256(b"maya-sawa opentimestamps fixture 2026-10-28").
"""
import hashlib
import io
import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from maya_sawa.services import analysis_timestamps as ots

FIXTURES = Path(__file__).parent / "fixtures/ots"
FIXTURE_DIGEST = hashlib.sha256(b"maya-sawa opentimestamps fixture 2026-10-28").digest()
CALENDARS = ["calendar-a-pool.bin", "calendar-b-pool.bin", "calendar-eternitywall.bin"]


def read(name):
    return (FIXTURES / name).read_bytes()


def test_reads_and_rewrites_the_official_example_proof_byte_for_byte():
    raw = read("hello-world.txt.ots")
    digest, timestamp = ots.read_proof(raw)
    assert digest == hashlib.sha256(read("hello-world.txt")).digest()
    assert ots.write_proof(digest, timestamp) == raw
    assert ots.bitcoin_heights(timestamp, digest) == [358391]
    assert ots.pending_calendars(timestamp, digest) == []


def test_a_proof_from_three_calendars_waits_on_each_of_them():
    timestamp = ots.merge([ots.parse_timestamp(io.BytesIO(read(name))) for name in CALENDARS])
    proof = ots.write_proof(FIXTURE_DIGEST, timestamp)
    assert proof.startswith(ots.HEADER)
    digest, again = ots.read_proof(proof)
    assert digest == FIXTURE_DIGEST and ots.write_proof(digest, again) == proof
    uris = [uri for uri, _ in ots.pending_calendars(timestamp, FIXTURE_DIGEST)]
    assert uris == ["https://alice.btc.calendar.opentimestamps.org", "https://bob.btc.calendar.opentimestamps.org",
                    "https://finney.calendar.eternitywall.com"]
    assert ots.bitcoin_heights(timestamp, FIXTURE_DIGEST) == []


def test_upgrading_swaps_a_pending_calendar_for_its_bitcoin_path_and_keeps_waiting_on_the_others():
    hello = hashlib.sha256(read("hello-world.txt")).digest()
    _, confirmed = ots.read_proof(read("hello-world.txt.ots"))
    pending = ots.Timestamp(attestations=[ots.pending_attestation("https://alice.btc.calendar.opentimestamps.org"),
                                          ots.pending_attestation("https://bob.btc.calendar.opentimestamps.org")])
    asked = []

    def fetch(uri, commitment):
        asked.append((uri, commitment))
        return ots.serialize(confirmed) if "alice" in uri else None   # bob has not been confirmed yet (HTTP 404)

    assert ots.upgrade(pending, hello, fetch) is True
    assert asked == [("https://alice.btc.calendar.opentimestamps.org", hello), ("https://bob.btc.calendar.opentimestamps.org", hello)]
    assert ots.bitcoin_heights(pending, hello) == [358391]
    assert [uri for uri, _ in ots.pending_calendars(pending, hello)] == ["https://bob.btc.calendar.opentimestamps.org"]
    assert ots.upgrade(pending, hello, lambda uri, commitment: None) is False


def test_only_known_public_calendars_are_contacted():
    assert ots.calendar_allowed("https://alice.btc.calendar.opentimestamps.org")
    assert ots.calendar_allowed("https://finney.calendar.eternitywall.com")
    for uri in ("http://alice.btc.calendar.opentimestamps.org", "https://evil.example.com", "https://opentimestamps.org.evil.com",
                "https://10.0.0.1", "https://alice.btc.calendar.opentimestamps.org@evil.com"):
        assert not ots.calendar_allowed(uri), uri


def revision(code, number, content, at, product_type="stock", model="claude-sonnet-5-5"):
    return {"productType": product_type, "code": code, "revision": number, "model": model, "content": content, "updatedAt": at}


def test_the_daily_manifest_lists_each_revision_by_hash_in_a_fixed_order():
    rows = [revision("SNOW-US", 1, "中立：首版", "2026-10-28T07:41:00+00:00"),
            revision("2330", 12, "偏多", "2026-10-28T13:20:00+00:00"),
            revision("2330", 11, "中立", "2026-10-28T01:05:00+00:00")]
    manifest = ots.day_manifest(date(2026, 10, 28), rows)
    body = json.loads(manifest)
    assert body["day"] == "2026-10-28" and body["timezone"] == "Asia/Taipei" and body["schema"] == ots.SCHEMA
    assert [(r["code"], r["revision"]) for r in body["revisions"]] == [("2330", 11), ("2330", 12), ("SNOW-US", 1)]
    leaf = body["revisions"][2]["sha256"]
    assert leaf == ots.revision_hash(rows[0])
    assert "content" not in body["revisions"][0]                   # only hashes: the proof itself reveals nothing
    assert ots.day_manifest(date(2026, 10, 28), list(reversed(rows))) == manifest
    edited = [dict(rows[0], content="中立：首版。")] + rows[1:]
    assert ots.day_manifest(date(2026, 10, 28), edited) != manifest


def test_a_revision_hash_is_what_anyone_can_recompute_from_the_public_analysis_api():
    row = revision("SNOW-US", 1, "中立：首版", "2026-10-28T07:41:00+00:00")
    canonical = json.dumps({"code": "SNOW-US", "content": "中立：首版", "model": "claude-sonnet-5-5", "productType": "stock",
                            "revision": 1, "updatedAt": "2026-10-28T07:41:00+00:00"}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert ots.revision_hash(row) == hashlib.sha256(canonical.encode()).hexdigest()
    assert ots.revision_hash(dict(row, updatedBy="someone")) == ots.revision_hash(row)   # fields the API does not publish are ignored


def test_a_taipei_day_is_the_utc_range_from_16_00_the_day_before():
    assert ots.day_window(date(2026, 10, 28)) == (datetime(2026, 10, 27, 16, tzinfo=UTC), datetime(2026, 10, 28, 16, tzinfo=UTC))


class FakeDatabase:
    def __init__(self, rows):
        self.rows, self.records = rows, {}

    def revisions_between(self, start, end):
        return [row for row in self.rows if start <= datetime.fromisoformat(row["updatedAt"]) < end]

    def get(self, day):
        return self.records.get(day)

    def save(self, record):
        self.records[record["day"]] = dict(record)

    def pending(self):
        return [dict(r) for r in self.records.values() if r["status"] == "pending"]

    def update(self, day, **fields):
        self.records[day].update(fields)


def test_stamping_a_day_submits_its_manifest_digest_once_and_stores_the_receipt():
    rows = [revision("2330", 11, "中立", "2026-10-27T17:00:00+00:00"), revision("2330", 10, "前一天", "2026-10-27T15:59:59+00:00")]
    database, submitted = FakeDatabase(rows), []

    def submit(uri, digest):
        submitted.append((uri, digest))
        if "eternitywall" in uri:
            raise OSError("calendar down")
        return read("calendar-a-pool.bin")

    record = ots.stamp_day(database, date(2026, 10, 28), submit)
    manifest = record["manifest"].encode()
    assert record["digest"] == hashlib.sha256(manifest).hexdigest() and record["revisionCount"] == 1
    assert json.loads(manifest)["revisions"][0]["revision"] == 11                       # 2026-10-27 23:59:59 Taipei is the day before
    assert record["status"] == "pending" and record["calendars"] == 2
    assert {uri for uri, _ in submitted} == set(ots.CALENDARS) and {d for _, d in submitted} == {hashlib.sha256(manifest).digest()}
    digest, timestamp = ots.read_proof(record["proof"])
    assert digest.hex() == record["digest"] and len(ots.pending_calendars(timestamp, digest)) == 2
    assert ots.stamp_day(database, date(2026, 10, 28), submit) is None                   # already stamped
    assert len(submitted) == 3
    assert ots.stamp_day(FakeDatabase([]), date(2026, 10, 28), submit) is None           # nothing written that day


def test_a_day_is_not_stamped_when_every_calendar_fails():
    database = FakeDatabase([revision("2330", 11, "中立", "2026-10-28T01:00:00+00:00")])
    with pytest.raises(RuntimeError, match="no calendar"):
        ots.stamp_day(database, date(2026, 10, 28), lambda uri, digest: (_ for _ in ()).throw(OSError("down")))
    assert database.records == {}


def test_checking_pending_days_records_the_bitcoin_block_once_a_calendar_confirms():
    hello = hashlib.sha256(read("hello-world.txt")).digest()
    _, confirmed = ots.read_proof(read("hello-world.txt.ots"))
    waiting = ots.Timestamp(attestations=[ots.pending_attestation("https://alice.btc.calendar.opentimestamps.org")])
    database = FakeDatabase([])
    database.records["2026-10-28"] = {"day": "2026-10-28", "digest": hello.hex(), "proof": ots.write_proof(hello, waiting),
                                      "status": "pending", "bitcoinHeight": None}
    assert ots.check_pending(database, lambda uri, commitment: None) == 0
    assert database.records["2026-10-28"]["status"] == "pending"
    assert ots.check_pending(database, lambda uri, commitment: ots.serialize(confirmed)) == 1
    stored = database.records["2026-10-28"]
    assert stored["status"] == "confirmed" and stored["bitcoinHeight"] == 358391
    assert ots.bitcoin_heights(ots.read_proof(stored["proof"])[1], hello) == [358391]


def test_hashes_from_the_database_match_hashes_recomputed_from_the_public_analysis_api(tmp_path):
    from sqlalchemy import create_engine
    from maya_sawa.databases.analysis_timestamp_db import AnalysisTimestampDatabase
    from maya_sawa.databases.market_ai_analysis_db import MarketAiAnalysisDatabase
    engine = create_engine(f"sqlite:///{tmp_path / 'stamps.db'}")
    analyses, stamps = MarketAiAnalysisDatabase(engine), AnalysisTimestampDatabase(engine)
    first = analyses.save("stock", "2330", "claude-sonnet-5-5", "中立", 0, "agent")
    analyses.save("stock", "2330", "claude-sonnet-5-5", "偏多", first["revision"], "agent")
    day = datetime.fromisoformat(first["updatedAt"]).replace(tzinfo=UTC).astimezone(ots.TAIPEI).date()
    rows = stamps.revisions_between(*ots.day_window(day))
    public = analyses.read("stock", "2330")["history"]                         # what GET /market/dashboard/analysis/2330 returns
    assert sorted(ots.revision_hash(row) for row in rows) == sorted(ots.revision_hash(row) for row in public)

    record = ots.stamp_day(stamps, day, lambda uri, digest: read("calendar-a-pool.bin"))
    stored = stamps.get(day.isoformat())
    assert stored["proof"] == record["proof"] and stored["status"] == "pending" and stored["revisionCount"] == 2
    assert [r["day"] for r in stamps.pending()] == [day.isoformat()]
    stamps.update(day.isoformat(), status="confirmed", bitcoinHeight=900000)
    assert stamps.pending() == [] and stamps.recent()[0]["bitcoinHeight"] == 900000


def test_the_public_endpoints_serve_the_exact_stamped_bytes(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market
    manifest = ots.day_manifest(date(2026, 10, 28), [revision("2330", 11, "中立", "2026-10-28T01:00:00+00:00")])
    digest = hashlib.sha256(manifest).digest()
    record = {"day": "2026-10-28", "digest": digest.hex(), "manifest": manifest.decode(), "revisionCount": 1,
              "proof": ots.write_proof(digest, ots.parse_timestamp(io.BytesIO(read("calendar-a-pool.bin")))),
              "status": "pending", "bitcoinHeight": None, "calendars": 1, "submittedAt": datetime(2026, 10, 28, 16, 20, tzinfo=UTC), "checkedAt": None}

    class Stub:
        def recent(self, limit=90): return [record]
        def get(self, day): return record if day == "2026-10-28" else None
    monkeypatch.setattr(market, "analysis_timestamp_db", Stub())
    app = FastAPI(); app.include_router(market.router)
    client = TestClient(app)
    listed = client.get("/market/timestamps").json()
    assert listed["days"][0] == {"day": "2026-10-28", "digest": digest.hex(), "revisionCount": 1, "status": "pending", "bitcoinHeight": None,
                                 "calendars": 1, "submittedAt": "2026-10-28T16:20:00+00:00",
                                 "manifestUrl": "/maya-sawa/market/timestamps/2026-10-28/manifest",
                                 "proofUrl": "/maya-sawa/market/timestamps/2026-10-28/proof"}
    body = client.get("/market/timestamps/2026-10-28/manifest")
    assert body.content == manifest and hashlib.sha256(body.content).hexdigest() == digest.hex()
    assert "ai-analysis-2026-10-28.json" in body.headers["content-disposition"]
    proof = client.get("/market/timestamps/2026-10-28/proof")
    assert proof.content == record["proof"] and "ai-analysis-2026-10-28.json.ots" in proof.headers["content-disposition"]
    assert client.get("/market/timestamps/2026-10-27/proof").status_code == 404
    assert client.get("/market/timestamps/..%2Fetc/proof").status_code in (404, 422)
