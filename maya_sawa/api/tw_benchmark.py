"""Public benchmark catalog and background ingestion of official Taiwan filings."""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from maya_sawa.databases.market_dashboard_db import market_dashboard_db
from maya_sawa.tw_benchmark_filings import catalog_url, download, listing

router = APIRouter(prefix="/market/benchmark")
logger = logging.getLogger(__name__)

BENCHMARKS = (
    ("2454", "聯發科", "IC 設計與終端應用", "以手機 SoC 觀察設計公司如何在效能、功耗與整合度之間取捨。對照產品組合與研發揭露，理解晶片如何轉化成終端裝置功能。"),
    ("2303", "聯電", "晶圓製造與廠務", "用成熟及特殊製程觀察代工如何把設計變成可量產的晶片。對照不同廠房與製程組合，有助於區分製造能力與產能利用率。"),
    ("6488", "環球晶", "8 吋與 12 吋矽晶圓", "以同一家材料商比較晶圓尺寸、產品規格與擴產配置。追蹤資本支出和產能時，將上游裸晶圓供給與晶圓代工產能分開。"),
    ("2330", "台積電", "專業晶圓代工與 CoWoS", "同時觀察邏輯晶圓製造和異質整合封裝，理解 AI 晶片效能如何受到運算晶粒、記憶體頻寬和封裝能力共同影響。"),
    ("6937", "天虹", "PVD、PECVD、ALD 薄膜設備", "比較不同沉積方法的膜厚控制、覆蓋性和設備用途，並用產品線與研發揭露觀察設備商如何把製程需求變成可銷售機台。"),
    ("3583", "辛耘", "晶圓濕蝕刻", "觀察濕製程設備如何透過藥液、流量與時間控制材料移除，並比較設備銷售和晶圓再生服務這兩種業務。"),
    ("3131", "弘塑", "晶圓清洗與濕製程設備", "從台灣自製設備商的角度，觀察設備如何滿足晶圓清洗、蝕刻均勻度與量產要求，以及前段和封裝應用的差異。"),
    ("1785", "光洋科", "濺鍍靶材", "以靶材連結原料純度、濺鍍薄膜與金屬回收。閱讀年報時可分辨材料研製與循環回收兩種價值來源。"),
    ("4772", "台特化", "半導體特殊氣體", "透過矽烷類與其他特氣觀察純度、製造及供應穩定性如何影響晶圓製程，並追蹤產品開發與產能的公開揭露。"),
    ("3413", "京鼎", "設備真空腔體與精密零件", "以腔體和真空零件觀察設備供應鏈的加工精度、潔淨度與可靠性要求，理解零件製造和整機整合的分工。"),
    ("5536", "聖暉*", "無塵室與廠務工程", "觀察空氣、微粒與公用設施如何影響晶圓廠量產環境。工程業務也提供辨識建廠投資與晶片產出的時間差的案例。"),
    ("3455", "由田", "晶圓光學檢測與良率", "利用自動光學檢測產品觀察缺陷如何被發現、分類與回饋至製程。比較檢測速度、解析度和誤判率的工程取捨。"),
    ("4949", "有成精密", "離子植入設備零件與維護", "從離子植入機的特殊材料零件及維護切入，理解摻雜設備的耗損與穩定度如何影響量產，並分辨設備服務與晶片製造。"),
    ("1560", "中砂", "CMP 鑽石碟", "用拋光墊修整耗材理解平坦度與良率如何連到耗材需求。年度報告可用來追蹤產品組合與製程應用的變化。"),
    ("3711", "日月光投控", "封裝、測試與異質整合", "對照封裝結構、測試及異質整合服務，理解晶粒出廠後如何形成可裝配、可驗證的產品，以及不同封裝方案的適用情境。"),
    ("3587", "閎康", "材料分析與可靠度驗證", "從材料分析、可靠度與失效分析理解更換材料前需要建立哪些證據，以及如何把檢測結果用於失效定位與供應商驗證。"),
)

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS benchmark (
        code TEXT PRIMARY KEY, company_name TEXT NOT NULL,
        segment TEXT NOT NULL, significance TEXT NOT NULL, annual_report_location TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS benchmark_filing (
        code TEXT NOT NULL REFERENCES benchmark(code), fiscal_year INTEGER NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('A', 'F')), filename TEXT NOT NULL,
        source_url TEXT NOT NULL, sha256 TEXT NOT NULL, pdf BYTEA NOT NULL,
        collected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (code, filename, sha256)
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
                for code, company, segment, significance in BENCHMARKS:
                    conn.execute(text("""
                        INSERT INTO benchmark VALUES (:code, :company, :segment, :meaning, :location)
                        ON CONFLICT (code) DO UPDATE SET company_name=excluded.company_name,
                        segment=excluded.segment, significance=excluded.significance,
                        annual_report_location=excluded.annual_report_location
                    """), dict(code=code, company=company, segment=segment, meaning=significance,
                               location=catalog_url(code, year - 1, "F")))
            conn.commit()
            for code, *_ in BENCHMARKS:
                for fiscal_year in (year - 2, year - 1, year):
                    for kind in ("F", "A"):
                        try:
                            source, files = listing(code, fiscal_year, kind)
                            for filename in files:
                                known = conn.scalar(text("""
                                    SELECT 1 FROM benchmark_filing WHERE code=:code AND filename=:filename
                                    LIMIT 1
                                """), dict(code=code, filename=filename))
                                conn.commit()
                                if known:
                                    continue
                                pdf = download(code, kind, filename)
                                conn.execute(text("""
                                    INSERT INTO benchmark_filing
                                      (code,fiscal_year,kind,filename,source_url,sha256,pdf)
                                    VALUES (:code,:year,:kind,:filename,:source,:sha,:pdf)
                                    ON CONFLICT DO NOTHING
                                """), dict(code=code, year=fiscal_year, kind=kind, filename=filename,
                                           source=source, sha=sha256(pdf).hexdigest(), pdf=pdf))
                                conn.commit()
                        except Exception:
                            conn.rollback()
                            logger.exception("Benchmark filing sync failed: %s %s %s", code, fiscal_year, kind)
        finally:
            conn.rollback()
            conn.execute(text("SELECT pg_advisory_unlock(72405839)"))
            conn.commit()


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
            ORDER BY b.code
        """)).mappings()]
