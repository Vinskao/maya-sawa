"""Public benchmark catalog and background ingestion of official Taiwan filings."""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from maya_sawa.databases.market_dashboard_db import market_dashboard_db
from maya_sawa.services.benchmark_analysis import process_annual_filings
from maya_sawa.tw_benchmark_filings import catalog_url, download, listing
from maya_sawa import overseas_benchmark_filings as overseas
from maya_sawa.api.market_reports import _verify_agent
from maya_sawa.benchmark_versions import VERSIONS, definition, members
from maya_sawa.services import benchmark_monitor

router = APIRouter(prefix="/market/benchmark")
logger = logging.getLogger(__name__)

SCHEMA = (
    benchmark_monitor.SCHEMA,
    """CREATE TABLE IF NOT EXISTS benchmark (
        code TEXT PRIMARY KEY, company_name TEXT NOT NULL,
        segment TEXT NOT NULL, significance TEXT NOT NULL, annual_report_location TEXT NOT NULL,
        is_active BOOLEAN NOT NULL DEFAULT TRUE
    )""",
    "ALTER TABLE benchmark ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE",
    """CREATE TABLE IF NOT EXISTS benchmark_filing (
        code TEXT NOT NULL REFERENCES benchmark(code), fiscal_year INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('A', 'F')), filename TEXT NOT NULL,
        source_url TEXT NOT NULL, sha256 TEXT NOT NULL, pdf BYTEA NOT NULL,
        collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (code, filename, sha256)
    )""",
    "ALTER TABLE benchmark_filing ADD COLUMN IF NOT EXISTS analysis_status TEXT",
    "ALTER TABLE benchmark_filing ADD COLUMN IF NOT EXISTS analysis_profile TEXT",
    "ALTER TABLE benchmark_filing ADD COLUMN IF NOT EXISTS analysis_attempted_at TIMESTAMPTZ",
    """CREATE TABLE IF NOT EXISTS benchmark_version (
        version INTEGER PRIMARY KEY, name TEXT NOT NULL, rationale TEXT NOT NULL,
        definition JSONB NOT NULL, adopted_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )""",
)


def sync():
    engine = market_dashboard_db.engine
    year = datetime.now(ZoneInfo("Asia/Taipei")).year
    with engine.connect() as conn:
        if not conn.scalar(text("SELECT pg_try_advisory_lock(72405839)")):
            return
        try:
            with conn.begin_nested():
                for ddl in SCHEMA:
                    conn.execute(text(ddl))
                # A line-up version is applied once, when it is first seen. After that the table is
                # authoritative, so the daily sync never undoes a manual selection.
                applied = conn.scalar(text("SELECT max(version) FROM benchmark_version"))
                latest = VERSIONS[-1]
                # How a version is described and drawn follows the code on every sync; only the
                # membership below is applied once.
                for version in VERSIONS:
                    conn.execute(text("""
                        INSERT INTO benchmark_version (version, name, rationale, definition)
                        VALUES (:version, :name, :rationale, CAST(:definition AS JSONB))
                        ON CONFLICT (version) DO UPDATE SET name=excluded.name,
                          rationale=excluded.rationale, definition=excluded.definition
                    """), dict(version=version["version"], name=version["name"],
                               rationale=version["rationale"],
                               definition=json.dumps(definition(version), ensure_ascii=False)))
                if applied is None or applied < latest["version"]:
                    lineup = members(latest)
                    for company in lineup:
                        conn.execute(text("""
                            INSERT INTO benchmark
                              (code, company_name, segment, significance, annual_report_location, is_active)
                            VALUES (:code, :company_name, :segment, :significance, :location, TRUE)
                            ON CONFLICT (code) DO UPDATE SET company_name=excluded.company_name,
                              segment=excluded.segment, significance=excluded.significance, is_active=TRUE
                        """), {**company, "location": report_location(company["code"], year)})
                    conn.execute(text("UPDATE benchmark SET is_active=FALSE WHERE code <> ALL(:codes)"),
                                 dict(codes=[company["code"] for company in lineup]))
            conn.commit()
            active_companies = conn.execute(text(
                "SELECT code FROM benchmark WHERE is_active=TRUE ORDER BY code"
            )).mappings().all()
            for company_row in active_companies:
                code = company_row["code"]
                if overseas.is_overseas(code):
                    sync_overseas(conn, code)
                    continue
                # Benchmarks set the guidance and cycle view, they are not holdings: only the newest
                # shareholder annual report is kept. This year's is tried first, then last year's.
                for fiscal_year in (year, year - 1):
                    try:
                        source, files = listing(code, fiscal_year, "F")
                        for filename in files:
                            known = conn.scalar(text("""
                                SELECT 1 FROM benchmark_filing WHERE code=:code AND filename=:filename
                                LIMIT 1
                            """), dict(code=code, filename=filename))
                            conn.commit()
                            if known:
                                continue
                            pdf = download(code, "F", filename)
                            conn.execute(text("""
                                INSERT INTO benchmark_filing
                                  (code,fiscal_year,kind,filename,source_url,sha256,pdf)
                                VALUES (:code,:year,'F',:filename,:source,:sha,:pdf)
                                ON CONFLICT DO NOTHING
                            """), dict(code=code, year=fiscal_year, filename=filename,
                                       source=source, sha=sha256(pdf).hexdigest(), pdf=pdf))
                            conn.commit()
                        if files:
                            break
                    except Exception:
                        conn.rollback()
                        logger.exception("Benchmark filing sync failed: %s %s", code, fiscal_year)
            process_annual_filings(conn)
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(72405839)"))
            conn.commit()


def report_location(code, year):
    """Where a reader finds the company's annual reports: MOPS for Taiwan, the official source abroad."""
    return overseas.catalog_url(code) if overseas.is_overseas(code) else catalog_url(code, year - 1, "F")


def sync_overseas(conn, code):
    """Store the newest annual report of an overseas benchmark (SEC ARS, Advantest IR, OpenDART)."""
    try:
        report = overseas.latest_report(code)
        if report is None:
            logger.warning("Benchmark annual report not found: %s", code)
            return
        known = conn.scalar(text(
            "SELECT 1 FROM benchmark_filing WHERE code=:code AND filename=:filename LIMIT 1"
        ), dict(code=code, filename=report["filename"]))
        conn.commit()
        if known:
            return
        document = overseas.download(code, report)
        conn.execute(text("""
            INSERT INTO benchmark_filing (code,fiscal_year,kind,filename,source_url,sha256,pdf)
            VALUES (:code,:year,'F',:filename,:source,:sha,:pdf)
            ON CONFLICT DO NOTHING
        """), dict(code=code, year=report["fiscal_year"], filename=report["filename"],
                   source=report["url"], sha=sha256(document).hexdigest(), pdf=document))
        conn.commit()
    except Exception as exc:
        conn.rollback()
        logger.warning("Benchmark annual report sync failed: %s %s", code, type(exc).__name__)


@asynccontextmanager
async def benchmark_worker():
    async def run():
        while True:
            try:
                await asyncio.to_thread(sync)
            except Exception:
                logger.exception("Benchmark sync failed")
            await asyncio.sleep(86400)

    task = asyncio.create_task(run()) if market_dashboard_db.engine is not None else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@router.get("")
def benchmark_list():
    engine = market_dashboard_db.engine
    if engine is None:
        raise HTTPException(503, "Benchmark database unavailable")
    with engine.connect() as conn:
        if not conn.scalar(text("SELECT to_regclass('benchmark')")):
            raise HTTPException(503, "Benchmark catalog initializing")
        return [dict(row) for row in conn.execute(text("""
            SELECT b.*, f.fiscal_year AS report_year,
                   coalesce(f.source_url, b.annual_report_location) AS report_url,
                   a.fiscal_year AS financial_year, a.source_url AS financial_url
            FROM benchmark b
            LEFT JOIN LATERAL (
                SELECT fiscal_year, source_url FROM benchmark_filing
                WHERE code=b.code AND kind='F' ORDER BY fiscal_year DESC, collected_at DESC LIMIT 1
            ) f ON true
            LEFT JOIN LATERAL (
                SELECT fiscal_year, source_url FROM benchmark_filing
                WHERE code=b.code AND kind='A' ORDER BY fiscal_year DESC, collected_at DESC LIMIT 1
            ) a ON true
            WHERE b.is_active
            ORDER BY b.code
        """)).mappings()]


@router.get("/versions")
def benchmark_versions():
    """Every line-up so far, newest first, with why it was chosen and how its stages connect."""
    engine = market_dashboard_db.engine
    if engine is None:
        raise HTTPException(503, "Benchmark database unavailable")
    with engine.connect() as conn:
        if not conn.scalar(text("SELECT to_regclass('benchmark_version')")):
            raise HTTPException(503, "Benchmark catalog initializing")
        rows = list(conn.execute(text(
            "SELECT version, name, rationale, definition, adopted_at FROM benchmark_version ORDER BY version DESC"
        )).mappings())
    return [{"version": row["version"], "name": row["name"], "rationale": row["rationale"],
             "adopted_at": row["adopted_at"], "is_current": index == 0, **row["definition"]}
            for index, row in enumerate(rows)]


@router.get('/monitor')
def benchmark_monitor_view():
    from maya_sawa.databases.market_reports_db import market_reports_db
    engine = market_dashboard_db.engine
    if engine is None:
        raise HTTPException(503, 'Benchmark database unavailable')
    try:
        with engine.connect() as connection:
            definitions = connection.execute(text('SELECT definition FROM benchmark_monitor_rule')).scalars().all()
        codes = {check['code'] for rule in definitions for check in rule.get('checks', [])}
        return benchmark_monitor.snapshot(engine, market_dashboard_db, market_reports_db,
                                          benchmark_monitor.current_observations(codes))
    except Exception as exc:
        logger.warning('Benchmark monitor unavailable: %s', type(exc).__name__)
        raise HTTPException(503, 'Benchmark monitor initializing or unavailable') from None


class MonitorRule(BaseModel):
    code: str = Field(min_length=1, max_length=24)
    checks: list[dict] = Field(max_length=20)
    holdings: list[dict] = Field(max_length=50)
    reviewNote: str = Field(min_length=10, max_length=2000)


@router.put('/monitor/{code}')
def save_benchmark_monitor(code: str, body: MonitorRule, x_market_agent_key: str | None = Header(None)):
    _verify_agent(x_market_agent_key)
    if code != body.code:
        raise HTTPException(422, 'Path and body codes differ')
    current = benchmark_monitor_view()
    node = next((item for item in current['nodes'] if item['code'] == code), None)
    try:
        benchmark_monitor.validate_rule(body.model_dump(), node['claims'] if node else [],
                                        {item['code'] for item in current['nodes']})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with market_dashboard_db.engine.begin() as connection:
        connection.execute(text('''INSERT INTO benchmark_monitor_rule (code, definition)
            VALUES (:code, CAST(:definition AS JSONB)) ON CONFLICT (code)
            DO UPDATE SET definition=excluded.definition, updated_at=now()'''),
            {'code': code, 'definition': json.dumps(body.model_dump(), ensure_ascii=False)})
    return {'code': code, 'saved': True}


class BenchmarkCompany(BaseModel):
    # Taiwan four-digit codes, or an overseas record code with a supported annual-report source.
    code: str = Field(pattern=r"^(\d{4}|[A-Z0-9]{1,6}-(US|JP|KR))$")
    company_name: str = Field(min_length=1, max_length=100)
    segment: str = Field(min_length=1, max_length=200)
    significance: str = Field(min_length=10, max_length=3000)
    active: bool = True


class BenchmarkSelection(BaseModel):
    active: bool


@router.put("/{code}")
def upsert_benchmark_company(
    code: str,
    company: BenchmarkCompany,
    x_market_agent_key: str | None = Header(None),
):
    """Add or update a Taiwan benchmark company and its current selection state."""
    _verify_agent(x_market_agent_key)
    if code != company.code:
        raise HTTPException(422, "Path code and company code must match")
    if "-" in code and not overseas.is_overseas(code):
        raise HTTPException(422, "No annual report source for this overseas code")
    engine = market_dashboard_db.engine
    if engine is None:
        raise HTTPException(503, "Benchmark database unavailable")
    year = datetime.now(ZoneInfo("Asia/Taipei")).year
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO benchmark
              (code, company_name, segment, significance, annual_report_location, is_active)
            VALUES (:code, :company_name, :segment, :significance, :location, :active)
            ON CONFLICT (code) DO UPDATE SET company_name=excluded.company_name,
              segment=excluded.segment, significance=excluded.significance,
              annual_report_location=excluded.annual_report_location, is_active=excluded.is_active
        """), {**company.model_dump(exclude={"active"}),
               "location": report_location(code, year), "active": company.active})
    return {"code": code, "is_active": company.active}


@router.put("/{code}/selection")
def set_benchmark_selection(
    code: str,
    selection: BenchmarkSelection,
    x_market_agent_key: str | None = Header(None),
):
    """Select or retire a Taiwan benchmark company without deleting its filing history."""
    _verify_agent(x_market_agent_key)
    engine = market_dashboard_db.engine
    if engine is None:
        raise HTTPException(503, "Benchmark database unavailable")
    with engine.begin() as conn:
        result = conn.execute(text(
            "UPDATE benchmark SET is_active=:active WHERE code=:code"
        ), {"code": code, "active": selection.active})
        if not result.rowcount:
            raise HTTPException(404, "Benchmark company not found")
    return {"code": code, "is_active": selection.active}
