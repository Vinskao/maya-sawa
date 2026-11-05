from datetime import date

from sqlalchemy import create_engine

from maya_sawa.databases.market_audio_db import MarketAudioDatabase
from maya_sawa.services.market_audio_worker import MarketAudioWorker
from maya_sawa.services.market_audio_worker import audio_autogen_is_configured


def database():
    return MarketAudioDatabase(create_engine('sqlite:///:memory:'))


def test_worker_is_disabled_by_default_and_does_not_claim_or_spend():
    db = database()
    db.enqueue('daily', 'brief-disabled', 1, 'full text')
    class Provider:
        def synthesize(self, text):
            raise AssertionError('disabled worker must not call provider')
    worker = MarketAudioWorker(db, Provider())
    assert worker.process_one() is None
    assert db.job('daily', 'brief-disabled', 1)['status'] == 'pending'


def test_daily_autogen_worker_never_claims_macro_or_stock_jobs():
    db = database()
    db.enqueue('stock', '2454', 3, 'stock analysis')
    db.enqueue('macro', 'NET-LIQUIDITY', 2, 'macro analysis')
    db.enqueue('daily', 'approved-brief', 1, 'approved daily brief')
    seen = []

    class Provider:
        @staticmethod
        def billable_characters(text): return len(text)
        def synthesize(self, text):
            seen.append(text)
            return b'audio', 'audio/mpeg', 'test-voice'

    worker = MarketAudioWorker(db, Provider(), enabled=True, monthly_char_limit=50000, daily_only=True,
                               eligible_daily_codes=lambda: {'approved-brief'})
    assert worker.process_one() == 'ready'
    assert seen == ['approved daily brief']
    assert db.job('stock', '2454', 3)['status'] == 'pending'
    assert db.job('macro', 'NET-LIQUIDITY', 2)['status'] == 'pending'


def test_daily_autogen_worker_only_claims_explicitly_approved_current_day_ids():
    db = database()
    db.enqueue('daily', 'older-approved', 1, 'older approved brief')
    db.enqueue('daily', 'today-approved', 1, 'today approved brief')
    seen = []

    class Provider:
        @staticmethod
        def billable_characters(text): return len(text)
        def synthesize(self, text):
            seen.append(text)
            return b'audio', 'audio/mpeg', 'test-voice'

    worker = MarketAudioWorker(db, Provider(), enabled=True, monthly_char_limit=50000,
                               daily_only=True, eligible_daily_codes=lambda: {'today-approved'})
    assert worker.process_one() == 'ready'
    assert seen == ['today approved brief']
    assert db.job('daily', 'older-approved', 1)['status'] == 'pending'


def test_daily_worker_uses_scheduled_presenter_voice_but_analysis_keeps_default():
    db = database()
    brief_id = 'a1e3f5d0-7401-46e9-a110-a20261103001'
    db.enqueue('daily', brief_id, 1, '今天市場的第一段內容。')
    calls = []

    class Provider:
        @staticmethod
        def billable_characters(text): return len(text)
        def synthesize(self, text, voice=None):
            calls.append(voice)
            return b'audio', 'audio/mpeg', voice or 'legacy-maya-voice'

    worker = MarketAudioWorker(db, Provider(), enabled=True, monthly_char_limit=10000,
                               daily_brief_day=lambda code: date(2026, 11, 3) if code == brief_id else None)
    assert worker.process_one() == 'ready'
    assert calls == ['zh-CN-XiaoyiNeural']
    assert db.enqueue('stock', '2454', 3, 'stock report') is True
    assert worker.process_one() == 'ready'
    assert calls == ['zh-CN-XiaoyiNeural', None]


def test_autogen_requires_two_explicit_flags_credential_region_and_monthly_cap():
    base = {'MARKET_AUDIO_AUTOGEN_ENABLED': 'true', 'MARKET_AUDIO_AZURE_ENABLED': 'true',
            'AZURE_SPEECH_KEY': 'secret', 'MARKET_AUDIO_SPEECH_REGION': 'eastus',
            'MARKET_AUDIO_MONTHLY_CHARACTER_LIMIT': '100000'}
    assert audio_autogen_is_configured(base) is True
    for key in ('MARKET_AUDIO_AUTOGEN_ENABLED', 'MARKET_AUDIO_AZURE_ENABLED', 'AZURE_SPEECH_KEY',
                'MARKET_AUDIO_SPEECH_REGION', 'MARKET_AUDIO_MONTHLY_CHARACTER_LIMIT'):
        missing = {**base}
        missing.pop(key)
        assert audio_autogen_is_configured(missing) is False


def test_audio_worker_leader_lock_fails_closed_on_non_postgres_database():
    db = database()
    assert db.acquire_worker_lock() is None


def test_monthly_local_character_budget_blocks_before_provider_call(caplog):
    db = database()
    db.enqueue('daily', 'brief-budget', 1, '年增5%')
    class Provider:
        @staticmethod
        def billable_characters(text):
            from html import escape
            return len(escape(text, quote=False))
        called = False
        def synthesize(self, text):
            self.called = True
            return b'ok', 'audio/mpeg', 'test-voice'
    provider = Provider()
    # Converting percent notation to spoken Mandarin expands the text to 6 characters.
    worker = MarketAudioWorker(db, provider, enabled=True, monthly_char_limit=5)
    assert worker.process_one() == 'budget_blocked'
    assert not provider.called
    assert db.job('daily', 'brief-budget', 1)['status'] == 'blocked'
    assert 'blocked' in caplog.text and 'brief-budget' in caplog.text


def test_monthly_budget_reserves_every_attempt_and_never_exceeds_limit():
    db = database()
    db.enqueue('daily', 'brief-one', 1, 'one')
    db.enqueue('daily', 'brief-two', 1, 'two')
    class Provider:
        @staticmethod
        def billable_characters(text): return len(text)
        def synthesize(self, text):
            return b'ok', 'audio/mpeg', 'test-voice'
    worker = MarketAudioWorker(db, Provider(), enabled=True, monthly_char_limit=5)
    assert worker.process_one() == 'ready'
    assert worker.process_one() == 'budget_blocked'
    assert db.monthly_reserved_characters() <= 5


def test_worker_synthesizes_full_text_and_persists_audio(caplog):
    caplog.set_level('INFO')
    db = database()
    full_text = '第一段。\n\n第二段，完整版本。'
    db.enqueue('daily', 'brief-1', 1, full_text)
    seen = []

    class Provider:
        @staticmethod
        def billable_characters(text): return len(text)
        def synthesize(self, text):
            seen.append(text)
            return b'complete-audio', 'audio/mpeg', 'test-voice'

    assert MarketAudioWorker(db, Provider(), enabled=True, monthly_char_limit=10000).process_one() == 'ready'
    assert seen == ['第一段。 第二段，完整版本。']
    assert db.audio('daily', 'brief-1', 1) == (b'complete-audio', 'audio/mpeg')
    assert db.job('daily', 'brief-1', 1)['status'] == 'ready'
    assert 'estimated_list_usd' in caplog.text
    assert 'ready' in caplog.text
    assert full_text not in caplog.text


def test_worker_blocks_document_style_daily_maya_before_provider_call():
    db = database()
    unsafe = '分析版本更新時間為2026-11-03 07:36，資料截至10月28日。'
    db.enqueue('daily', 'brief-metadata', 1, unsafe)
    class Provider:
        called = False
        @staticmethod
        def billable_characters(text): return len(text)
        def synthesize(self, text):
            self.called = True
            return b'ok', 'audio/mpeg', 'test-voice'
    provider = Provider()
    worker = MarketAudioWorker(db, provider, enabled=True, monthly_char_limit=10000)
    assert worker.process_one() == 'failed'
    assert not provider.called
    assert db.job('daily', 'brief-metadata', 1)['status'] == 'failed'
    assert db.job('daily', 'brief-metadata', 1)['errorType'] == 'InvalidSpokenTranscript'


def test_daily_spoken_guard_does_not_change_macro_or_stock_audio_sources():
    db = database()
    text = 'EPS & capex analysis: 5.19%.'
    db.enqueue('stock', '2454', 3, text)
    seen = []
    class Provider:
        @staticmethod
        def billable_characters(value): return len(value)
        def synthesize(self, value):
            seen.append(value)
            return b'ok', 'audio/mpeg', 'test-voice'
    worker = MarketAudioWorker(db, Provider(), enabled=True, monthly_char_limit=10000)
    assert worker.process_one() == 'ready'
    assert seen == [text]


def test_worker_records_failure_then_retries_same_complete_revision(caplog):
    db = database()
    text = '完整文章，不是增量。'
    db.enqueue('daily', 'brief-2', 1, text)

    class Provider:
        @staticmethod
        def billable_characters(text): return len(text)
        calls = 0
        def synthesize(self, text):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError('provider rejected key=NEVER-STORE-THIS')
            return b'ok', 'audio/mpeg', 'test-voice'

    worker = MarketAudioWorker(db, Provider(), max_attempts=2, enabled=True, monthly_char_limit=10000)
    assert worker.process_one() == 'retry'
    failed_attempt = db.job('daily', 'brief-2', 1)
    assert failed_attempt['status'] == 'retry' and failed_attempt['errorType'] == 'RuntimeError'
    assert 'retry' in caplog.text and 'RuntimeError' in caplog.text
    assert 'NEVER-STORE-THIS' not in str(failed_attempt)
    assert worker.process_one() == 'ready'
    assert db.job('daily', 'brief-2', 1)['attempts'] == 2


def test_audio_work_is_version_deduplicated_and_conflicting_text_is_rejected():
    db = database()
    assert db.enqueue('daily', 'brief-3', 1, 'full text') is True
    assert db.enqueue('daily', 'brief-3', 1, 'full text') is False
    try:
        db.enqueue('daily', 'brief-3', 1, 'different text')
    except ValueError as exc:
        assert 'different source' in str(exc)
    else:
        raise AssertionError('conflicting source must not overwrite an existing revision')
