from datetime import date

import pytest

from maya_sawa.services.market_reports import (
    chunk_pages,
    extract_pdf_pages,
    MAX_REPORT_BYTES,
    validate_claims,
)


def test_owner_pdf_upload_persists_queued_record_and_schedules_backend_processing(monkeypatch):
    import asyncio
    import io
    from fastapi import UploadFile
    from starlette.background import BackgroundTasks
    from starlette.datastructures import Headers
    from maya_sawa.api import market_reports

    class FakeDatabase:
        def find_by_digest(self, _digest):
            return None

        def save_queued(self, **kwargs):
            return {
                "id": "queued-report",
                "title": kwargs["title"],
                "visibility": kwargs["visibility"],
                "status": "queued",
                "page_count": 0,
                "claim_count": 0,
                "claims": [],
                "uploaded_by": kwargs["uploaded_by"],
            }, False

    database = FakeDatabase()
    monkeypatch.setattr(market_reports, "market_reports_db", database)
    monkeypatch.setattr(market_reports, "report_digest", lambda _data: "queued-digest")
    monkeypatch.setattr(market_reports, "extract_pdf_pages", lambda _data: pytest.fail("PDF extraction must run after the response"))
    background = BackgroundTasks()
    result = asyncio.run(market_reports.upload_report(
        file=UploadFile(file=io.BytesIO(b"%PDF-test"), filename="queued.pdf", headers=Headers({"content-type": "application/pdf"})),
        title="Queued report",
        publisher="Research",
        published_at=None,
        visibility="public",
        claims={"sub": "owner"},
        background_tasks=background,
    ))

    assert result["report"]["status"] == "queued"
    assert result["duplicate"] is False
    assert len(background.tasks) == 1
    assert background.tasks[0].func is market_reports.process_queued_report
    assert background.tasks[0].args == ("queued-report",)


def test_backend_processor_persists_status_transitions_without_blocking_upload(monkeypatch):
    import asyncio
    from maya_sawa.api import market_reports

    class FakeDatabase:
        statuses = []

        def get_report(self, report_id, *, include_pdf=False):
            assert report_id == "queued-report" and include_pdf
            return ({"id": report_id, "status": "queued"}, b"%PDF-test", "owner")

        def set_upload_status(self, report_id, status, failure_reason=None):
            self.statuses.append((report_id, status, failure_reason))

        def update_upload_extracted(self, report_id, pages):
            self.statuses.append((report_id, "extracted", len(pages)))

        def add_chunks(self, report_id, chunks, vectors):
            assert report_id == "queued-report" and len(chunks) == len(vectors)

    class FakeEmbeddings:
        def embed_documents(self, texts):
            return [[0.0] * 1536 for _ in texts]

    database = FakeDatabase()
    monkeypatch.setattr(market_reports, "market_reports_db", database)
    monkeypatch.setattr(market_reports, "extract_pdf_pages", lambda _pdf: ["Readable report text."])
    monkeypatch.setattr(market_reports, "get_embedding_service", lambda: FakeEmbeddings())

    asyncio.run(market_reports.process_queued_report("queued-report"))

    assert [status for _, status, _ in database.statuses] == ["processing", "extracted", "claims_pending"]


def text_pdf(pages):
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{3 + i * 3} 0 R' for i in range(len(pages)))}] /Count {len(pages)} >>".encode(),
    ]
    for index, text in enumerate(pages):
        page_id = 3 + index * 3
        stream_id = page_id + 2
        content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
        objects.extend(
            [
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents {stream_id} 0 R >>".encode(),
                (
                    b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
                    if index == 0
                    else b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
                ),
                f"<< /Length {len(content)} >>\nstream\n".encode()
                + content
                + b"\nendstream",
            ]
        )
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return bytes(output)


def test_extracts_text_with_original_page_numbers_from_text_pdf():
    # Minimal, secret-free text PDF fixture; pypdf parses real page objects and text operators.
    assert extract_pdf_pages(
        text_pdf(
            [
                "Memory makers expect tight supply through 2027.",
                "Advanced packaging capacity remains constrained.",
            ]
        )
    ) == [
        "Memory makers expect tight supply through 2027.",
        "Advanced packaging capacity remains constrained.",
    ]


def test_chunks_stay_within_page_and_keep_sentence_boundaries():
    pages = ["First sentence. Second sentence. Third sentence.", "Separate page text."]
    chunks = chunk_pages(pages, max_chars=24)
    assert [(c["page"], c["text"]) for c in chunks] == [
        (1, "First sentence."),
        (1, "Second sentence."),
        (1, "Third sentence."),
        (2, "Separate page text."),
    ]


def test_scanned_pdf_fails_with_ocr_reason_and_retains_page_count(monkeypatch):
    from maya_sawa.services import market_reports

    class EmptyPage:
        def extract_text(self):
            return ""

    class ScannedReader:
        def __init__(self, _stream, strict=False):
            self.pages = [EmptyPage(), EmptyPage(), EmptyPage()]

    monkeypatch.setattr(market_reports, "PdfReader", ScannedReader)
    with pytest.raises(ValueError, match="OCR") as error:
        extract_pdf_pages(b"%PDF-scanned")
    assert error.value.page_count == 3


def test_pdf_validation_rejects_non_pdf_and_files_over_40_mib():
    from maya_sawa.services.market_reports import validate_pdf

    with pytest.raises(ValueError, match="PDF"):
        validate_pdf("notes.txt", "text/plain", b"not a pdf")
    with pytest.raises(ValueError, match="40 MB"):
        validate_pdf("large.pdf", "application/pdf", b"%PDF-" + b"x" * MAX_REPORT_BYTES)


def test_report_visibility_never_exposes_owner_pdf_to_public():
    from maya_sawa.services.market_reports import report_for_viewer

    report = {
        "id": "r1",
        "visibility": "owner",
        "uploaded_by": "owner-sub",
        "pdf": b"secret",
        "text": "full text",
    }
    assert report_for_viewer(report, None) is None
    assert "text" not in report_for_viewer(report, "owner-sub")
    visible = report_for_viewer(report, "owner-sub", include_text=True)
    assert visible["text"] == "full text"
    assert "pdf" not in visible


def test_duplicate_digest_is_the_same_report_and_claims_validation_is_bounded():
    from maya_sawa.services.market_reports import validate_claims

    valid = [
        {
            "page": 1,
            "segment": "memory",
            "codes": ["2408"],
            "dimension": "cycle",
            "direction": "tailwind",
            "claim": "Tight supply supports pricing.",
            "evidence": "2027 outlook",
            "as_of": date(2026, 9, 15).isoformat(),
        }
    ]
    assert validate_claims(valid, page_count=1)[0]["codes"] == ["2408"]
    with pytest.raises(ValueError, match="page"):
        validate_claims([{**valid[0], "page": 2}], page_count=1)


def test_report_api_owner_upload_duplicate_and_private_pdf_rules(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market_reports

    class FakeDatabase:
        stored = {
            "id": "existing",
            "title": "Public report",
            "publisher": "Publisher",
            "visibility": "public",
            "status": "ready",
            "page_count": 1,
            "text": "private full text",
            "claim_count": 0,
            "claims": [],
        }
        uploader = "owner-sub"

        def find_by_digest(self, digest):
            return (
                {**self.stored, "uploaded_by": self.uploader}
                if digest == "duplicate-digest"
                else None
            )

        def list_reports(self, owner):
            rows = [
                {**self.stored, "uploaded_by": self.uploader},
                {
                    **self.stored,
                    "id": "private",
                    "visibility": "owner",
                    "uploaded_by": "someone-else",
                },
            ]
            return [
                row
                for row in rows
                if row["visibility"] == "public" or row["uploaded_by"] == owner
            ]

        def get_report(self, report_id, *, include_pdf=False):
            if report_id != "private":
                return None
            return (
                {**self.stored, "id": report_id, "visibility": "owner"},
                b"%PDF-original" if include_pdf else None,
                self.uploader,
            )

    class FakeEmbeddings:
        def embed_documents(self, texts):
            return [[0.0] * 1536 for _ in texts]

    database = FakeDatabase()
    monkeypatch.setattr(market_reports, "market_reports_db", database)
    monkeypatch.setattr(
        market_reports, "get_embedding_service", lambda: FakeEmbeddings()
    )
    monkeypatch.setattr(
        market_reports, "report_digest", lambda _data: "duplicate-digest"
    )
    app = FastAPI()
    app.include_router(market_reports.router)
    app.dependency_overrides[market_reports.require_manage_users_request] = lambda: {
        "sub": "owner-sub"
    }
    app.dependency_overrides[market_reports._optional_owner] = lambda: None
    client = TestClient(app)

    duplicate = client.post(
        "/market/reports",
        data={"title": "Same", "visibility": "public"},
        files={"file": ("same.pdf", b"%PDF-test", "application/pdf")},
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    listing = client.get("/market/reports").json()["reports"]
    assert [row["id"] for row in listing] == ["existing"]
    assert "text" not in listing[0] and "uploaded_by" not in listing[0]

    assert client.get("/market/reports/private").status_code == 404
    app.dependency_overrides[market_reports._optional_owner] = lambda: {
        "sub": "owner-sub"
    }
    assert client.get("/market/reports/private").status_code == 200
    assert (
        client.get("/market/reports/private?download=true").content == b"%PDF-original"
    )


def test_failed_report_upload_can_be_retried_by_its_owner(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market_reports

    class FakeDatabase:
        deleted = []

        def find_by_digest(self, _digest):
            return {
                "id": "failed-report",
                "title": "Previously failed",
                "visibility": "public",
                "status": "failed",
                "uploaded_by": "owner-sub",
            }

        def delete_failed_owned(self, report_id, owner):
            self.deleted.append((report_id, owner))
            return report_id == "failed-report" and owner == "owner-sub"

        def save_queued(self, **kwargs):
            return (
                {
                    "id": "retried-report",
                    "title": kwargs["title"],
                    "visibility": "public",
                    "status": "queued",
                    "uploaded_by": kwargs["uploaded_by"],
                },
                False,
            )

    database = FakeDatabase()
    monkeypatch.setattr(market_reports, "market_reports_db", database)
    monkeypatch.setattr(market_reports, "report_digest", lambda _data: "same-digest")
    async def no_op(_report_id):
        return None
    monkeypatch.setattr(market_reports, "process_queued_report", no_op)
    app = FastAPI()
    app.include_router(market_reports.router)
    app.dependency_overrides[market_reports.require_manage_users_request] = lambda: {
        "sub": "owner-sub"
    }
    client = TestClient(app)

    response = client.post(
        "/market/reports",
        data={"title": "Retry succeeds", "visibility": "public"},
        files={"file": ("retry.pdf", b"%PDF-test", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["duplicate"] is False
    assert response.json()["report"]["status"] == "queued"
    assert database.deleted == [("failed-report", "owner-sub")]


def test_failed_report_retry_cleanup_only_deletes_owned_failed_rows(tmp_path):
    from sqlalchemy import create_engine
    from maya_sawa.databases.market_reports_db import MarketReportsDatabase

    db = MarketReportsDatabase(create_engine(f"sqlite:///{tmp_path / 'retry.db'}"))
    failed = db.save_failed(
        title="Failed",
        publisher="",
        published_at=None,
        visibility="public",
        uploaded_by="owner",
        digest="failed-digest",
        pdf=b"%PDF-failed",
        reason="Embedding failed",
        page_count=1,
        pages=["Text"],
    )
    ready, _ = db.ingest(
        title="Ready",
        publisher="",
        published_at=None,
        visibility="public",
        uploaded_by="owner",
        digest="ready-digest",
        pdf=b"%PDF-ready",
        pages=["Text"],
        chunks=[{"page": 1, "seq": 0, "text": "Text"}],
        vectors=[[0.0] * 1536],
    )

    assert db.delete_failed_owned(failed["id"], "someone-else") is False
    assert db.delete_failed_owned(ready["id"], "owner") is False
    assert db.delete_failed_owned(failed["id"], "owner") is True
    assert db.find_by_digest("failed-digest") is None
    assert db.find_by_digest("ready-digest")["id"] == ready["id"]


def test_queued_upload_is_persisted_and_transitions_to_text_extracted(tmp_path):
    from sqlalchemy import create_engine
    from maya_sawa.databases.market_reports_db import MarketReportsDatabase

    db = MarketReportsDatabase(create_engine(f"sqlite:///{tmp_path / 'queued.db'}"))
    queued, duplicate = db.save_queued(
        title="Queued PDF",
        publisher="Research",
        published_at=None,
        visibility="public",
        uploaded_by="owner",
        digest="queued-digest",
        pdf=b"%PDF-queued",
    )
    assert duplicate is False and queued["status"] == "queued"
    stored, pdf, owner = db.get_report(queued["id"], include_pdf=True)
    assert (stored["status"], stored["page_count"], stored["text"], pdf, owner) == (
        "queued", 0, "", b"%PDF-queued", "owner"
    )

    assert db.set_upload_status(queued["id"], "processing") is True
    assert db.update_upload_extracted(queued["id"], ["First page", "Second page"]) is True
    extracted = db.find_by_digest("queued-digest")
    assert extracted["status"] == "extracted"
    assert extracted["page_count"] == 2
    assert "=====PAGE 2=====\nSecond page" in extracted["text"]


def test_embedding_failure_keeps_extracted_report_ready_for_claims(monkeypatch):
    import asyncio
    from maya_sawa.api import market_reports

    class FakeDatabase:
        statuses = []

        def get_report(self, report_id, *, include_pdf=False):
            return ({"id": report_id, "status": "queued"}, b"%PDF-test", "owner")

        def set_upload_status(self, report_id, status, failure_reason=None):
            self.statuses.append(status)

        def update_upload_extracted(self, _report_id, _pages):
            self.statuses.append("extracted")

        def add_chunks(self, *_args, **_kwargs):
            raise AssertionError("chunks must not be stored without embeddings")

    class FailedEmbeddings:
        def embed_documents(self, _texts):
            raise RuntimeError("provider unavailable")

    database = FakeDatabase()
    monkeypatch.setattr(market_reports, "market_reports_db", database)
    monkeypatch.setattr(market_reports, "extract_pdf_pages", lambda _data: ["Readable page."])
    monkeypatch.setattr(
        market_reports, "get_embedding_service", lambda: FailedEmbeddings()
    )
    asyncio.run(market_reports.process_queued_report("failed-report"))
    assert database.statuses == ["processing", "extracted", "claims_pending"]


def test_extracted_report_without_vectors_is_in_claims_pending_queue(tmp_path):
    from sqlalchemy import create_engine
    from maya_sawa.databases.market_reports_db import MarketReportsDatabase

    db = MarketReportsDatabase(create_engine(f"sqlite:///{tmp_path / 'pending.db'}"))
    report, duplicate = db.save_extracted(
        title="Readable, not vectorized",
        publisher="Research",
        published_at=None,
        visibility="public",
        uploaded_by="owner",
        digest="no-vectors",
        pdf=b"%PDF-test",
        pages=["2408 memory supply outlook"],
    )

    assert duplicate is False
    assert report["status"] == "claims_pending"
    pending = db.pending_claims()
    assert [row["id"] for row in pending] == [report["id"]]
    assert "2408 memory supply outlook" in pending[0]["text"]


def test_legacy_embedding_failed_report_with_text_is_retried_by_claim_queue(tmp_path):
    from sqlalchemy import create_engine
    from maya_sawa.databases.market_reports_db import MarketReportsDatabase

    db = MarketReportsDatabase(create_engine(f"sqlite:///{tmp_path / 'legacy.db'}"))
    failed = db.save_failed(
        title="Legacy report",
        publisher="Research",
        published_at=None,
        visibility="public",
        uploaded_by="owner",
        digest="legacy-failed",
        pdf=b"%PDF-test",
        reason="Vectorization failed",
        page_count=1,
        pages=["2408 memory cycle outlook"],
    )

    pending = db.pending_claims()
    assert [row["id"] for row in pending] == [failed["id"]]
    assert "2408 memory cycle outlook" in pending[0]["text"]


def test_report_upload_requires_owner_and_pdf_metadata(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market_reports

    app = FastAPI()
    app.include_router(market_reports.router)
    client = TestClient(app)
    assert (
        client.post(
            "/market/reports",
            files={"file": ("r.pdf", b"%PDF-x", "application/pdf")},
            data={"title": "Report"},
        ).status_code
        == 401
    )
    app.dependency_overrides[market_reports.require_manage_users_request] = lambda: {
        "sub": "owner"
    }
    assert (
        client.post(
            "/market/reports",
            files={"file": ("r.txt", b"no", "text/plain")},
            data={"title": "Report"},
        ).status_code
        == 422
    )


def test_scanned_upload_is_saved_as_failed_with_ocr_reason(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market_reports
    from maya_sawa.services.market_reports import PDFTextExtractionError

    class FakeDatabase:
        statuses = []

        def find_by_digest(self, digest):
            return None

        def save_queued(self, **kwargs):
            return ({"id": "r1", "title": kwargs["title"], "status": "queued", "page_count": 0,
                     "visibility": kwargs["visibility"], "uploaded_by": kwargs["uploaded_by"]}, False)

        def get_report(self, report_id, *, include_pdf=False):
            assert report_id == "r1" and include_pdf
            return ({"id": report_id, "status": "queued"}, b"%PDF-scan", "owner")

        def set_upload_status(self, report_id, status, failure_reason=None):
            self.statuses.append((report_id, status, failure_reason))

        def set_upload_page_count(self, report_id, page_count):
            self.statuses.append((report_id, "page_count", page_count))

    database = FakeDatabase()
    monkeypatch.setattr(market_reports, "market_reports_db", database)

    def extraction_failure(_data):
        raise PDFTextExtractionError("PDF has no text layer; OCR is required", 2)

    monkeypatch.setattr(market_reports, "extract_pdf_pages", extraction_failure)
    app = FastAPI()
    app.include_router(market_reports.router)
    app.dependency_overrides[market_reports.require_manage_users_request] = lambda: {
        "sub": "owner"
    }
    client = TestClient(app)
    response = client.post(
        "/market/reports",
        data={"title": "Scan"},
        files={"file": ("scan.pdf", b"%PDF-scan", "application/pdf")},
    )
    assert response.status_code == 200
    assert response.json()["report"]["status"] == "queued"
    assert [(status, value) for _, status, value in database.statuses] == [
        ("processing", None), ("failed", "PDF has no text layer; OCR is required"), ("page_count", 2)
    ]


def test_database_deduplicates_and_cascades_chunks_and_claims(tmp_path):
    from sqlalchemy import create_engine, event, text
    from maya_sawa.databases.market_reports_db import MarketReportsDatabase

    engine = create_engine(f"sqlite:///{tmp_path / 'reports.db'}")
    event.listen(
        engine,
        "connect",
        lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
    )
    db = MarketReportsDatabase(engine)
    pages = ["First page text.", "Second page text."]
    chunks = chunk_pages(pages)
    kwargs = dict(
        title="Sample",
        publisher="Research",
        published_at=None,
        visibility="public",
        uploaded_by="owner",
        digest="same-sha",
        pdf=b"%PDF-test",
        pages=pages,
        chunks=chunks,
        vectors=[[0.0] * 1536 for _ in chunks],
    )
    first, duplicate = db.ingest(**kwargs)
    second, duplicate_again = db.ingest(**kwargs)
    assert first["id"] == second["id"]
    assert duplicate is False and duplicate_again is True
    report_id = first["id"]
    assert "=====PAGE 2=====\nSecond page text." in first["text"]
    private, _ = db.ingest(
        **{
            **kwargs,
            "title": "Private",
            "visibility": "owner",
            "digest": "private-sha",
            "uploaded_by": "owner",
        }
    )
    assert [row["title"] for row in db.list_reports(None)] == ["Sample"]
    assert {row["title"] for row in db.list_reports("owner")} == {"Sample", "Private"}
    claim = {
        "page": 2,
        "segment": "memory",
        "codes": ["2408"],
        "dimension": "cycle",
        "direction": "tailwind",
        "claim": "Tight memory supply.",
        "evidence": "FY27 guidance",
        "as_of": "2026-09-15",
    }
    assert db.replace_claims(report_id, validate_claims([claim], 2), "Claude routine")
    assert db.get_report(report_id)[0]["claims"][0]["page"] == 2
    assert db.delete_owned(report_id, "other-owner") is False
    assert db.delete_owned(report_id, "owner") is True
    assert db.delete_owned(private["id"], "owner") is True
    with db.sessions() as session:
        assert (
            session.execute(
                text("select count(*) from maya_sawa_market_report_chunks")
            ).scalar()
            == 0
        )
        assert (
            session.execute(
                text("select count(*) from maya_sawa_market_report_claims")
            ).scalar()
            == 0
        )


def test_ready_report_clears_stale_vectorization_failure_reason(tmp_path):
    from sqlalchemy import create_engine
    from maya_sawa.databases.market_reports_db import MarketReportsDatabase

    db = MarketReportsDatabase(create_engine(f"sqlite:///{tmp_path / 'ready-report.db'}"))
    pages = ["Memory supply remains tight."]
    report, _ = db.save_extracted(
        title="2408 industry note",
        publisher="Research",
        published_at=None,
        visibility="public",
        uploaded_by="owner",
        digest="ready-with-old-vector-error",
        pdf=b"%PDF-test",
        pages=pages,
    )
    db.fail_by_digest("ready-with-old-vector-error", "向量化失敗，請稍後重試")

    assert db.replace_claims(
        report["id"],
        [{"page": 1, "segment": "memory", "dimension": "supply", "direction": "headwind",
          "claim": "Memory supply is constrained.", "codes": [], "evidence": "Supply remains tight."}],
        "Claude (scheduled)",
    )

    ready = next(item for item in db.list_reports("owner") if item["id"] == report["id"])
    assert ready["status"] == "ready"
    assert ready["failure_reason"] is None


def test_claim_api_requires_agent_key_and_validates_claim_pages(monkeypatch):
    import hashlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market_reports

    class FakeDatabase:
        def page_count(self, report_id):
            return 1

        def replace_claims(self, report_id, claims, extracted_by):
            return report_id == "r1"

    monkeypatch.setattr(market_reports, "market_reports_db", FakeDatabase())
    key = "test-reports-agent-key"
    monkeypatch.setenv(
        "MARKET_AGENT_KEY_SHA256", hashlib.sha256(key.encode()).hexdigest()
    )
    app = FastAPI()
    app.include_router(market_reports.router)
    client = TestClient(app)
    endpoint = "/market/reports/r1/claims"
    claim = {
        "page": 1,
        "segment": "memory",
        "codes": ["2408"],
        "dimension": "cycle",
        "direction": "tailwind",
        "claim": "Supply remains constrained.",
        "evidence": "FY27",
    }
    assert (
        client.put(
            endpoint, json={"claims": [claim], "extracted_by": "Claude"}
        ).status_code
        == 401
    )
    assert (
        client.put(
            endpoint,
            json={"claims": [{**claim, "page": 2}], "extracted_by": "Claude"},
            headers={"X-Market-Agent-Key": key},
        ).status_code
        == 422
    )
    assert (
        client.put(
            endpoint,
            json={"claims": [{**claim, "direction": "long"}], "extracted_by": "Claude"},
            headers={"X-Market-Agent-Key": key},
        ).status_code
        == 422
    )
    assert client.put(
        endpoint,
        json={"claims": [claim], "extracted_by": "Claude"},
        headers={"X-Market-Agent-Key": key},
    ).json() == {"saved": True, "claim_count": 1}


def test_semantic_search_includes_private_reports_only_when_explicitly_requested(monkeypatch):
    import hashlib
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from maya_sawa.api import market_reports

    calls = []

    class FakeDatabase:
        def search_chunks(self, _vector, **kwargs):
            calls.append(kwargs)
            return []

    class FakeEmbeddings:
        def embed_query(self, _query):
            return [0.0] * 1536

    key = "private-search-agent-key"
    monkeypatch.setenv(
        "MARKET_AGENT_KEY_SHA256", hashlib.sha256(key.encode()).hexdigest()
    )
    monkeypatch.setattr(market_reports, "market_reports_db", FakeDatabase())
    monkeypatch.setattr(
        market_reports, "get_embedding_service", lambda: FakeEmbeddings()
    )
    app = FastAPI()
    app.include_router(market_reports.router)
    client = TestClient(app)

    default_search = client.get(
        "/market/reports/search?q=CoWoS",
        headers={"X-Market-Agent-Key": key},
    )
    assert default_search.status_code == 200
    assert calls[-1]["include_private"] is False

    private_search = client.get(
        "/market/reports/search?q=CoWoS&include_private=true",
        headers={"X-Market-Agent-Key": key},
    )
    assert private_search.status_code == 200
    assert calls[-1]["include_private"] is True

    anonymous_private_search = client.get(
        "/market/reports/search?q=CoWoS&include_private=true"
    )
    assert anonymous_private_search.status_code == 401
