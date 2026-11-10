"""Homepage search box: keyword search over the whole report text, not only titles and claims."""
import asyncio

import pytest
from sqlalchemy import create_engine

from maya_sawa.databases.market_reports_db import MarketReportsDatabase
from maya_sawa.services.market_reports import chunk_pages


def _db(tmp_path):
    db = MarketReportsDatabase(create_engine(f"sqlite:///{tmp_path / 'reports.db'}"))

    def add(digest, pages, visibility="public", title="Report"):
        chunks = chunk_pages(pages)
        row, _ = db.ingest(title=title, publisher="Research", published_at=None, visibility=visibility,
                           uploaded_by="owner", digest=digest, pdf=b"%PDF", pages=pages, chunks=chunks,
                           vectors=[[0.0] * 1536 for _ in chunks])
        return row["id"]
    return db, add


def test_finds_words_that_only_appear_in_the_body_and_reports_page_and_snippet(tmp_path):
    db, add = _db(tmp_path)
    hit = add("a", ["Opening remarks.", "矽光子模組的良率在第三季提升，CPO 出貨開始放量。"])
    add("b", ["Unrelated foundry pricing discussion."])
    results = db.search_text("矽光子 cpo")
    assert [row["report_id"] for row in results] == [hit]
    assert results[0]["page"] == 2 and "矽光子" in results[0]["snippet"]
    assert "=====PAGE" not in results[0]["snippet"]


def test_every_word_must_match_and_private_reports_stay_hidden(tmp_path):
    db, add = _db(tmp_path)
    add("a", ["Liquid cooling demand is rising."])
    add("b", ["Liquid cooling secret memo."], visibility="private")
    assert db.search_text("cooling pricing") == []
    assert len(db.search_text("COOLING")) == 1          # case-insensitive, public only
    assert db.search_text("100%") == []                 # LIKE wildcards are literal
    assert db.search_text("   ") == []


def test_public_endpoint_returns_matches_and_bounds_the_query(monkeypatch):
    from fastapi import HTTPException
    from maya_sawa.api import market_reports

    class Fake:
        def search_text(self, q, limit=200):
            return [{"report_id": "r1", "page": 3, "snippet": q}]
    monkeypatch.setattr(market_reports, "market_reports_db", Fake())
    assert asyncio.run(market_reports.fulltext_reports(q=" cpo "))["results"][0]["report_id"] == "r1"
    assert asyncio.run(market_reports.fulltext_reports(q="  "))["results"] == []
    with pytest.raises(HTTPException) as error:
        asyncio.run(market_reports.fulltext_reports(q="x" * 201))
    assert error.value.status_code == 422
