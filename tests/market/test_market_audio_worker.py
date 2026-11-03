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


def test_monthly_local_character_budget_blocks_before_provider_call():
    db = database()
    db.enqueue('daily', 'brief-budget', 1, 'A & B')
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
    # Escaping the ampersand expands the billable source to 9 chars.
    worker = MarketAudioWorker(db, provider, enabled=True, monthly_char_limit=8)
    assert worker.process_one() == 'budget_blocked'
    assert not provider.called
    assert db.job('daily', 'brief-budget', 1)['status'] == 'blocked'


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


def test_worker_synthesizes_full_text_and_persists_audio():
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
    assert seen == [full_text]
    assert db.audio('daily', 'brief-1', 1) == (b'complete-audio', 'audio/mpeg')
    assert db.job('daily', 'brief-1', 1)['status'] == 'ready'


def test_worker_records_failure_then_retries_same_complete_revision():
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
