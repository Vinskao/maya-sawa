"""
Markdown Q&A System - 主應用程式入口點

這個模組是整個 Markdown Q&A 系統的主要入口點，負責：
1. 初始化 FastAPI 應用程式
2. 配置 CORS 中間件
3. 註冊 API 路由
4. 管理應用程式的啟動和關閉事件
5. 啟動文章同步排程器

作者: Maya Sawa Team
版本: 0.1.0
"""

# 標準庫導
try:
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware
except ImportError as e:
    raise ImportError(f"FastAPI is required but not installed. Please install with: poetry install") from e

import os
import logging
import asyncio
import pathlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager

# 第三方庫導入
try:
    from dotenv import load_dotenv
except ImportError as e:
    raise ImportError(f"python-dotenv is required but not installed. Please install with: poetry install") from e

# ==================== 日誌配置 ====================
# 設置日誌級別為 DEBUG，用於開發環境的詳細調試信息；HTTP 用戶端的請求網址不記錄（OpenDART key 在 query 參數裡）
from .core.log_config import configure_logging
configure_logging()
logger = logging.getLogger(__name__)

# ==================== 環境變數配置 ====================
# 本機 dotenv 僅補缺值；部署注入的設定始終優先。
env_path = pathlib.Path(__file__).parent.parent / '.env'
logger.debug(f"Loading .env file from: {env_path}")
load_dotenv(env_path, override=False)

# 本地模組導入
from .api.qa import router as qa_router
from .api.articles import router as articles_router
from .api.blog import router as blog_router
from .services.blog_worker import blog_worker
from .api.legacy_chat_history import legacy_router as legacy_chat_router
from .api.people import router as people_router
from .api.voyeur import router as voyeur_router
from .api.proxy import router as proxy_router
from .api.videos import router as videos_router
from .api.git_commits import router as git_commits_router
from .api.otel_usage import router as otel_usage_router
from .api.market import router as market_router
from .api.market_reports import router as market_reports_router
from .api.admin_users import router as admin_users_router
from .api.reader_events import router as reader_events_router
from .api.ai_visibility import router as ai_visibility_router
from .api.publisher_mcp import router as publisher_mcp_router
from .api.social_publishing import router as social_publishing_router
from .services.social import runner as social_runner
from .services.social_publish_queue import start_monitor as start_publishing_monitor, stop_monitor as stop_publishing_monitor
from .api.runpod import router as runpod_router
from .api.research_pipeline import router as research_pipeline_router
from .research_pipeline.container import get_container as get_research_pipeline_container
from .services.shioaji_market import shioaji_market_service
from .services.ibkr_market import ibkr_market_service
from .services.market_history_collector import market_history_collector
from .services.market_fundamentals import market_fundamentals_service
from .services.metrics_consumer import MetricsConsumer
from .core.services.scheduler import ArticleSyncScheduler
from .api.tw_benchmark import benchmark_worker, router as benchmark_router
from .people import sync_data
from .core.config import Config
from .core.errors.errors import register_exception_handlers
from .core.security import SecurityMiddleware

# 從環境變數獲取 OpenAI API 配置
api_key = os.getenv("OPENAI_API_KEY")
api_base = os.getenv("OPENAI_API_BASE")

# 記錄 API 配置信息（隱藏敏感信息）
logger.debug("OpenAI API credential configured: %s", bool(api_key))
logger.debug(f"API Base URL: {api_base}")
logger.debug(f"PUBLIC_API_BASE_URL: {Config.PUBLIC_API_BASE_URL}")

# 檢查關鍵環境變數是否正確載入
if not api_key:
    logger.error("OPENAI_API_KEY not found in environment variables!")
if not api_base:
    logger.error("OPENAI_API_BASE not found in environment variables!")

# ==================== 應用程式生命週期 ====================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期。

    research pipeline 的 checkpointer 與 compiled graph 在這裡建立一次、關閉一次，
    不在每個 request 開 context manager。設定不完整會直接讓應用啟動失敗，
    避免 approve/reject 在 runtime 才發現無法 resume。
    """
    get_research_pipeline_container().startup()
    try:
        await _startup_event()
        start_publishing_monitor()
        social_runner.start()
        async with blog_worker(), benchmark_worker():
            yield
    finally:
        await stop_publishing_monitor()
        await social_runner.stop()
        await _shutdown_event()
        get_research_pipeline_container().shutdown()


# ==================== FastAPI 應用程式初始化 ====================
# 創建 FastAPI 應用程式實例
app = FastAPI(
    lifespan=lifespan,
    title="Maya Sawa Unified API",  # API 文檔標題
    description="""
    A unified API system integrating multiple services:
    
    - **/qa/** - Document Q&A system (Original maya-sawa-v1)
    - **/paprika/** - Article management (Migrated from Laravel)
    
    All APIs maintain backward compatibility with their original endpoints.
    """,  # API 描述
    version="0.2.0",  # API 版本
    root_path="/maya-sawa"  # 添加根路徑支持，用於 Kubernetes Ingress 路徑前綴
)

# ==================== 全域例外處理器註冊 ====================
# 註冊統一的錯誤處理器，提供一致的錯誤回應格式
register_exception_handlers(app)

app.add_middleware(SecurityMiddleware)

# ==================== CORS 中間件配置 ====================
# 添加 CORS 中間件，允許跨域請求
# 在生產環境中應該限制 allow_origins 為特定的域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:4321",
        "https://localhost:4321",
        "http://127.0.0.1:4321",
        "http://localhost:3000",
        "https://localhost:3000",
        "https://tymultiverse.cc",
    ],
    allow_credentials=True,  # 允許攜帶認證信息
    allow_methods=["*"],  # 允許所有 HTTP 方法
    allow_headers=["*"],  # 允許所有請求頭
)

# ==================== 路由註冊 ====================
# 註冊問答相關的 API 路由 (原有功能)
app.include_router(qa_router)

# 註冊 Paprika 文章 API 路由 (從 Laravel 移植)
app.include_router(articles_router)
app.include_router(blog_router)

# 註冊 Legacy 聊天歷史 API 路由 (向後兼容)
app.include_router(legacy_chat_router)

# 註冊 People API 路由 (新增 - 用於支援前端獲取角色列表)
app.include_router(people_router)

# 註冊 Voyeur API 路由 (新增 - 移植自 Voyeur 專案)
app.include_router(voyeur_router)

# 註冊 Proxy API 路由 (新增 - 用於代理外部 API 請求，解決 CORS 問題)
app.include_router(proxy_router)

# 註冊 Video Merging API 路由
app.include_router(videos_router, prefix="/videos", tags=["Videos"])

# Git commit knowledge ingestion API
app.include_router(git_commits_router)

# OpenTelemetry usage ingestion for Claude Code and Gemini CLI
app.include_router(otel_usage_router)

# Read-only market quote endpoints backed by Shioaji.
app.include_router(market_router)
app.include_router(market_reports_router)
app.include_router(benchmark_router)
from .api.daily_maya import make_router as make_daily_maya_router
from .api.market import _verify_agent_key
from .databases.daily_maya_db import DailyMayaDatabase
from .databases.market_audio_db import MarketAudioDatabase
from .databases.market_dashboard_db import market_dashboard_db
from .databases.market_ai_analysis_db import market_ai_analysis_db
from .api.market_audio import make_router as make_market_audio_router
from .api.podcast import make_router as make_podcast_router
from .services.azure_speech_rest import AzureSpeechRestProvider
from .services.market_audio_worker import MarketAudioWorker, audio_autogen_is_configured
from .services.market_presenters import presenter_for_day

market_audio_db = MarketAudioDatabase(market_dashboard_db.engine)
daily_maya_db = DailyMayaDatabase(market_dashboard_db.engine)

def _today_approved_daily_audio_ids():
    today = datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat()
    return {row['id'] for row in daily_maya_db.published() if row['day'] == today}

def _daily_brief_day(proposal_id):
    row = daily_maya_db.get(proposal_id)
    return datetime.fromisoformat(row['day']).date() if row else None

def _enqueue_analysis_audio(product_type, code, revision):
    if product_type not in {'stock', 'macro'}:
        return
    history = market_ai_analysis_db.read(product_type, code)['history']
    analysis = next((item for item in history if item['revision'] == revision), None)
    if analysis:
        market_audio_db.enqueue(product_type, code, revision, analysis['content'])

market_ai_analysis_db.listeners.append(_enqueue_analysis_audio)
_market_audio_worker_task = None
_market_audio_worker_lock = None

async def _market_audio_worker_loop(worker):
    while True:
        try:
            result = await asyncio.to_thread(worker.process_one)
        except Exception:
            logger.exception('Market audio worker failed')
            result = None
        if result in ('failed', 'budget_blocked'):
            # The owner used to find out only when the episode never appeared (docs/MARKET_AUDIO.md, 2026-11-16).
            try:
                from .services import telegram_notify
                reason = '本月字元上限已用完，語音不會合成' if result == 'budget_blocked' else '口播稿檢查或合成失敗，請看 maya-sawa 日誌的 Market audio job'
                await asyncio.to_thread(telegram_notify.send, 'attention', '每日精讀語音沒有產生', reason)
            except Exception:
                logger.warning('Market audio failure alert was not delivered')
        if result is None:
            await asyncio.sleep(30)

async def _start_market_audio_worker_if_configured():
    global _market_audio_worker_task, _market_audio_worker_lock
    if _market_audio_worker_task or not audio_autogen_is_configured():
        return
    _market_audio_worker_lock = market_audio_db.acquire_worker_lock()
    if _market_audio_worker_lock is None:
        logger.info('Market audio worker not started: another pod owns the database lease')
        return
    provider = AzureSpeechRestProvider()
    from .services import voice_tone
    worker = MarketAudioWorker(market_audio_db, provider, enabled=True,
                               monthly_char_limit=os.environ['MARKET_AUDIO_MONTHLY_CHARACTER_LIMIT'],
                               daily_only=True,
                               eligible_daily_codes=_today_approved_daily_audio_ids,
                               daily_brief_day=_daily_brief_day,
                               tone_provider=voice_tone.current_tone)
    _market_audio_worker_task = asyncio.create_task(_market_audio_worker_loop(worker))
    logger.warning('Market audio autogeneration is enabled with the configured local character cap')

def _daily_maya_authorized(request):
    _verify_agent_key(request)
    return True

async def _daily_conference_check(content, day):
    """Conferences the reading claims that are not in the event list (services/daily_maya_events.py)."""
    from .api.market import get_market_dashboard_events
    from .services.daily_maya_events import company_names, unlisted_conferences
    auto = market_dashboard_db.latest_auto()
    symbols = [*auto.get("positions", []), *market_dashboard_db.custom_symbols(), *market_dashboard_db.watch_symbols()]
    events = (await get_market_dashboard_events())["events"]
    return unlisted_conferences(content, day, company_names(symbols), events)


async def _daily_coverage_check(content, day):
    """Held Taiwan stocks with a highlighted event that the draft never mentions (services/daily_maya_coverage.py)."""
    from .api.market import get_market_dashboard_events
    from .services.daily_maya_coverage import uncovered_holdings
    positions = market_dashboard_db.latest_auto().get("positions", [])
    return uncovered_holdings(content, positions, (await get_market_dashboard_events())["events"])


async def _social_metrics_loop():
    """Daily follower / reach snapshot of every social channel for /palais (services/social_metrics.py)."""
    from .databases.youtube_db import YoutubeDatabase
    from .services import social_metrics
    from .services.social.outbox import SocialOutbox
    if market_dashboard_db.engine is None:
        return
    database = social_metrics.SocialMetricsDatabase(market_dashboard_db.engine)
    while True:
        try:
            saved = await asyncio.to_thread(social_metrics.snapshot_today, database, SocialOutbox(market_dashboard_db.engine),
                                            YoutubeDatabase(market_dashboard_db.engine).uploaded)
            logger.warning("Social metrics snapshot: %s values", saved)
        except Exception:
            logger.exception("Social metrics snapshot failed")
        await asyncio.sleep(6 * 3600)


async def _insider_transfer_loop():
    """Insiders' pre-filed transfers: the OpenAPI lists one day at a time, so keep each day's filings (docs/INSIDER_TRANSFERS.md)."""
    if not market_dashboard_db.engine:
        return
    from .databases.insider_transfer_db import InsiderTransferDatabase
    from .services import market_insider_transfers
    from .services.market_company_events import market_company_events_service
    db = InsiderTransferDatabase(market_dashboard_db.engine)
    market_company_events_service.insider_source = db.open_on
    market_company_events_service.insider_extra_source = lambda day: (
        db.untransferred_since(day - timedelta(days=market_insider_transfers.UNTRANSFERRED_DAYS)), db.latest_changes())
    rounds = 0
    while True:
        try:
            saved = await asyncio.to_thread(market_insider_transfers.collect, db.save)
            logger.info("Insider transfer filings stored: %s", saved)
            # Untransferred filings and the ~10 MB monthly holdings file: once a day is enough.
            if rounds % 6 == 0:
                counts = await asyncio.to_thread(market_insider_transfers.collect_monthly_and_untransferred, db)
                logger.info("Insider untransferred / holdings: %s", counts)
        except Exception:
            logger.exception("Insider transfer collection failed")
        rounds += 1
        await asyncio.sleep(4 * 3600)  # published once a business day; four checks a day never miss one


async def _youtube_daily_loop():
    """Daily reading -> MP4 -> YouTube (services/youtube_daily.py). Off until the channel's OAuth credentials are configured."""
    import os
    from .services import youtube_daily
    if not youtube_daily.configured():
        return
    from .databases.youtube_db import YoutubeDatabase
    daily = youtube_daily.YoutubeDaily(
        YoutubeDatabase(market_dashboard_db.engine), market_audio_db,
        youtube_daily.YouTubeClient(os.environ["YOUTUBE_CLIENT_ID"], os.environ["YOUTUBE_CLIENT_SECRET"], os.environ["YOUTUBE_REFRESH_TOKEN"]),
        youtube_daily.privacy())
    logger.warning("YouTube daily upload enabled (privacy=%s)", daily.privacy)
    failures = 0
    while True:
        try:
            result = await asyncio.to_thread(lambda: daily.process_one(daily_maya_db.published()))
            if result:
                logger.warning("YouTube upload: %s -> %s", *result)
                continue  # more may be waiting; no pause between episodes
            failures = 0
        except Exception as exc:
            logger.exception("YouTube daily upload failed")
            failures += 1
            if failures in (1, 3):  # at once, then once more if it is still failing two hours later (hourly retries)
                try:
                    from .services import telegram_notify
                    await asyncio.to_thread(telegram_notify.send, "attention", "YouTube 每日上傳失敗",
                                            f"{type(exc).__name__}：每小時重試一次。授權過期時需重新授權（docs/YOUTUBE_DAILY.md）。")
                except Exception:
                    logger.warning("YouTube failure alert was not delivered")
        await asyncio.sleep(youtube_daily.retry_delay_seconds(failures))


def _daily_reading_to_blog(rows):
    """Approved daily readings go on /blog too (services/daily_reading_blog.py); a no-op until BLOG_ENABLED."""
    import os
    from .services.daily_reading_blog import sync_published
    if os.getenv('BLOG_ENABLED', 'false').lower() != 'true':
        return None
    from .api.blog import get_blog
    return sync_published(rows, get_blog())


def _retitle_blog_articles():
    """Descriptive titles for articles still titled by their slug (services/blog_retitle.py); no-op until BLOG_ENABLED."""
    import os
    if os.getenv('BLOG_ENABLED', 'false').lower() != 'true':
        return
    try:
        from .api.blog import get_blog
        from .services.blog_retitle import sync_titles
        logger.warning('Blog retitle: %s', sync_titles(get_blog()))
        from .services.blog_consolidate import consolidate
        logger.warning('Blog consolidate: %s', consolidate(get_blog()))
    except Exception:
        logger.exception('Blog retitle/consolidate failed')


def _backfill_daily_reading_blog():
    _retitle_blog_articles()
    try:
        result = _daily_reading_to_blog(daily_maya_db.published())
        if result:
            logger.warning('Daily reading blog backfill: %s', result)
    except Exception:
        logger.exception('Daily reading blog backfill failed')


def _on_daily_approved(row):
    market_audio_db.enqueue('daily', row['id'], 1, row['content'])
    try:
        _daily_reading_to_blog([row])
    except Exception:
        logger.exception('Daily reading could not be put on the blog')


app.include_router(make_daily_maya_router(daily_maya_db,
                                         market_ai_analysis_db, _daily_maya_authorized,
                                         on_approved=_on_daily_approved,
                                         conference_check=_daily_conference_check, coverage_check=_daily_coverage_check))
app.include_router(make_market_audio_router(market_audio_db, daily_maya_db))

# Daily reading by email: sign-ups are stored at once; mail goes out only once SMTP is configured.
from .api.brief_subscriptions import make_router as make_brief_subscriptions_router
from .services.brief_mailer import smtp_configured as _brief_smtp_configured
from .databases.brief_subscribers_db import BriefSubscribersDatabase
from .services.brief_mailer import BriefMailer

brief_subscribers_db = BriefSubscribersDatabase(market_dashboard_db.engine)
app.include_router(make_brief_subscriptions_router(brief_subscribers_db, lambda: datetime.now(ZoneInfo('UTC')), mail_enabled=_brief_smtp_configured))
_brief_mail_task = None

def _today_approved_brief():
    today = datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat()
    return next((row for row in daily_maya_db.published() if row['day'] == today), None)

async def _brief_mail_loop(mailer):
    while True:
        try:
            await asyncio.to_thread(lambda: mailer.run_once(_today_approved_brief()))
        except Exception:
            logger.exception('Brief mail loop failed')
        await asyncio.sleep(300)
app.include_router(make_podcast_router(market_audio_db, daily_maya_db))
app.include_router(admin_users_router)
app.include_router(reader_events_router)
app.include_router(ai_visibility_router)
app.include_router(publisher_mcp_router)
app.include_router(social_publishing_router)

# RunPod GPU cost & balance observability (GraphQL-backed, read-only).
app.include_router(runpod_router)

# Research Zone AI 更新管線的人工審核 API（目前使用 stub service）
app.include_router(research_pipeline_router)

# ==================== 排程器初始化 ====================
# 創建文章同步排程器實例
scheduler = ArticleSyncScheduler()
metrics_consumer = MetricsConsumer.get_instance()

# ==================== 應用程式生命週期事件 ====================

async def _startup_event():
    """
    應用程式啟動時執行的事件處理器
    
    這個函數在 FastAPI 應用程式啟動時自動執行，負責：
    1. 執行初始文章同步
    2. 執行人員和武器數據同步
    3. 啟動定期同步任務
    4. 啟動 Voyeur Metrics Consumer
    5. 記錄啟動日誌
    """
    try:
        # Backfill: approved readings that predate the blog copy (idempotent, one article per day).
        asyncio.get_running_loop().run_in_executor(None, _backfill_daily_reading_blog)
        await _start_market_audio_worker_if_configured()
        asyncio.create_task(_youtube_daily_loop())
        asyncio.create_task(_insider_transfer_loop())
        asyncio.create_task(_social_metrics_loop())
        global _brief_mail_task
        if _brief_mail_task is None and market_dashboard_db.engine:
            _brief_mail_task = asyncio.create_task(_brief_mail_loop(BriefMailer(brief_subscribers_db)))
        # 檢查配置
        missing_config = Config.validate_required_config()
        if missing_config:
            logger.warning(f"缺少必要的配置變數: {', '.join(missing_config)}")
        
        # 記錄同步配置
        sync_config = Config.get_sync_config_summary()
        logger.info(f"同步配置: {sync_config}")
        
        # 啟動 Voyeur Metrics Consumer (如果配置允許)
        try:
            from .databases.market_ai_analysis_db import market_ai_analysis_db
            from .services.market_research import seed_bundled_research
            await asyncio.to_thread(seed_bundled_research, market_ai_analysis_db)
            from .databases.market_industry_db import market_industry_db
            from .services.market_research import seed_bundled_industries
            await asyncio.to_thread(seed_bundled_industries, market_industry_db)
        except Exception as e:
            logger.error(f"Failed to seed market research maps: {e}")

        try:
            metrics_consumer.start()
        except Exception as e:
            logger.error(f"Failed to start MetricsConsumer: {e}")

        try:
            await shioaji_market_service.start_background_refresh()
        except Exception as e:
            logger.error(f"Failed to start Shioaji market cache refresh: {e}")

        try:
            await ibkr_market_service.start_background_refresh()
        except Exception as e:
            logger.error(f"Failed to start IBKR market cache refresh: {e}")

        try:
            await market_history_collector.start()
        except Exception as e:
            logger.error(f"Failed to start market history collection: {e}")

        try:
            await market_fundamentals_service.start()
        except Exception as e:
            logger.error(f"Failed to start low-frequency fundamentals collection: {e}")

        try:
            from .services.market_price_targets import price_target_collector
            await price_target_collector.start()
        except Exception as e:
            logger.error(f"Failed to start broker target price collection: {e}")

        try:
            from .services.telegram_posts import telegram_post_collector
            await telegram_post_collector.start()
        except Exception as e:
            logger.error(f"Failed to start Telegram post collection: {e}")

        try:
            from .services.analysis_timestamps import analysis_timestamper
            await analysis_timestamper.start()
        except Exception as e:
            logger.error(f"Failed to start AI analysis timestamps: {e}")

        try:
            from .services.market_macro import market_macro_service
            await market_macro_service.start()
        except Exception as e:
            logger.error(f"Failed to start macroeconomic data collection: {e}")

        try:
            from .services.tdnet_financials import tdnet_financials_collector
            await tdnet_financials_collector.start()
        except Exception as e:
            logger.error(f"Failed to start TDnet financials collection: {e}")

        try:
            from .services.jquants_financials import jquants_financials_collector
            await jquants_financials_collector.start()
        except Exception as e:
            logger.error(f"Failed to start J-Quants financials collection: {e}")

        try:
            from .services.edinet_financials import edinet_financials_collector
            await edinet_financials_collector.start()
        except Exception as e:
            logger.error(f"Failed to start EDINET financials collection: {e}")

        try:
            from .services.dart_financials import dart_financials_collector
            await dart_financials_collector.start()
        except Exception as e:
            logger.error(f"Failed to start OpenDART financials collection: {e}")

        try:
            from .services.binance_market import binance_market_collector
            await binance_market_collector.start()
        except Exception as e:
            logger.error(f"Failed to start Binance market collection: {e}")

        try:
            from .services.binance_account import binance_account_service
            await binance_account_service.start()
        except Exception as e:
            logger.error(f"Failed to start Binance balance collection: {e}")

        # 執行初始文章同步（如果啟用）
        if Config.ENABLE_AUTO_SYNC_ON_STARTUP:
            logger.info("應用程式啟動，開始執行初始文章同步...")
            try:
                await scheduler.run_initial_sync()
            except Exception as e:
                logger.error(f"初始文章同步失敗: {str(e)}")
                # 不讓文章同步失敗阻止應用程式啟動
        else:
            logger.info("跳過初始文章同步（已禁用）")
        
        # 執行人員和武器數據同步（如果啟用）- 改為背景任務
        if Config.ENABLE_PEOPLE_WEAPONS_SYNC:
            logger.info("開始執行人員和武器數據同步（背景任務）...")
            
            async def sync_people_weapons_background():
                """背景任務：同步人員和武器數據"""
                try:
                    people_weapons_result = sync_data()
                    logger.info(f"人員和武器數據同步完成: 人員 {people_weapons_result['people_updated']} 條, 武器 {people_weapons_result['weapons_updated']} 條")
                except Exception as e:
                    logger.error(f"人員和武器數據同步失敗: {str(e)}")
            
            # 創建背景任務，不阻塞主線程
            asyncio.create_task(sync_people_weapons_background())
        else:
            logger.info("跳過人員和武器數據同步（已禁用）")
        
        # 啟動定期同步任務（如果啟用）
        from .core.services.scheduler import periodic_sync_wanted
        if periodic_sync_wanted():
            await scheduler.start_periodic_sync(
                interval_days=Config.SYNC_INTERVAL_DAYS, 
                hour=Config.SYNC_HOUR, 
                minute=Config.SYNC_MINUTE
            )
            logger.info("定期同步任務已啟動")
        else:
            logger.info("跳過定期同步任務（已禁用）")
        
        logger.info("應用程式啟動完成")
    except Exception as e:
        # 記錄啟動錯誤，但不讓啟動錯誤阻止應用程式運行
        logger.error(f"啟動時發生錯誤: {str(e)}")

async def _shutdown_event():
    """
    應用程式關閉時執行的事件處理器
    
    這個函數在 FastAPI 應用程式關閉時自動執行，負責：
    1. 停止定期同步任務
    2. 停止 Metrics Consumer
    3. 清理資源
    4. 記錄關閉日誌
    """
    try:
        global _brief_mail_task
        if _brief_mail_task:
            _brief_mail_task.cancel()
            _brief_mail_task = None
        global _market_audio_worker_task, _market_audio_worker_lock
        if _market_audio_worker_task:
            _market_audio_worker_task.cancel()
            await asyncio.gather(_market_audio_worker_task, return_exceptions=True)
            _market_audio_worker_task = None
        if _market_audio_worker_lock:
            market_audio_db.release_worker_lock(_market_audio_worker_lock)
            _market_audio_worker_lock = None
        # 停止定期同步任務，避免資源洩漏
        await scheduler.stop_periodic_sync()
        
        # 停止 Metrics Consumer
        try:
            metrics_consumer.stop()
        except Exception as e:
            logger.error(f"Error stopping MetricsConsumer: {e}")

        await shioaji_market_service.close()
        await ibkr_market_service.close()
        await market_history_collector.close()
        await market_fundamentals_service.close()
        try:
            from .services.market_price_targets import price_target_collector
            await price_target_collector.close()
        except Exception as e:
            logger.error(f"Error stopping broker target price collection: {e}")
        try:
            from .services.telegram_posts import telegram_post_collector
            await telegram_post_collector.close()
        except Exception as e:
            logger.error(f"Error stopping Telegram post collection: {e}")
        try:
            from .services.analysis_timestamps import analysis_timestamper
            await analysis_timestamper.close()
        except Exception as e:
            logger.error(f"Error stopping AI analysis timestamps: {e}")
        try:
            from .services.market_macro import market_macro_service
            await market_macro_service.close()
        except Exception as e:
            logger.error(f"Error stopping macroeconomic data collection: {e}")
        try:
            from .services.tdnet_financials import tdnet_financials_collector
            await tdnet_financials_collector.close()
        except Exception as e:
            logger.error(f"Error stopping TDnet financials collection: {e}")
        try:
            from .services.jquants_financials import jquants_financials_collector
            await jquants_financials_collector.close()
            from .services.edinet_financials import edinet_financials_collector
            await edinet_financials_collector.close()
        except Exception as e:
            logger.error(f"Error stopping J-Quants financials collection: {e}")
        try:
            from .services.dart_financials import dart_financials_collector
            await dart_financials_collector.close()
        except Exception as e:
            logger.error(f"Error stopping OpenDART financials collection: {e}")
        try:
            from .services.binance_market import binance_market_collector
            await binance_market_collector.close()
        except Exception as e:
            logger.error(f"Error stopping Binance market collection: {e}")
        try:
            from .services.binance_account import binance_account_service
            await binance_account_service.close()
        except Exception as e:
            logger.error(f"Error stopping Binance balance collection: {e}")

        logger.info("應用程式關閉，排程任務與服務已停止")
    except Exception as e:
        # 記錄關閉錯誤
        logger.error(f"關閉時發生錯誤: {str(e)}")

# ==================== 根路由 ====================

@app.get("/public-openapi.json", include_in_schema=False)
async def public_openapi():
    """Opt-in OpenAPI document of the market-data endpoints anyone may read (see core/public_api.py); the site's API page renders it."""
    from .core.public_api import build_public_openapi
    return build_public_openapi(app)


@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Liveness/readiness: proves the event loop answers, touches no database or Redis. A probe on /paprika/articles
    (a DB query, 1 s timeout) failed whenever startup refreshes made queries slow, and the kubelet killed the pod."""
    return {"status": "ok"}


@app.get("/")
async def root():
    """
    根路由處理器
    
    返回 API 的基本信息，包括：
    - 歡迎消息
    - API 版本
    - API 文檔 URL
    - 可用的 API 端點
    
    Returns:
        dict: 包含 API 基本信息的字典
    """
    return {
        "message": "Welcome to Maya Sawa Unified API",
        "version": "0.2.0",
        "docs_url": "/docs",
        "endpoints": {
            "qa": "/qa/* - Document Q&A system",
            "paprika": "/paprika/* - Article management",
            "maya_v2": "/maya-v2/* - Conversation & AI model management"
        }
    }
