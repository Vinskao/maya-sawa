"""One-job worker; automatic invocation is deliberately controlled by deployment config."""
import hashlib
import os

from ..databases.market_audio_db import AudioBudgetExceeded
from .daily_maya_speech import InvalidSpokenTranscript, prepare_spoken_transcript


def audio_autogen_is_configured(environ=None):
    values = environ if environ is not None else os.environ
    if (values.get('MARKET_AUDIO_AUTOGEN_ENABLED', '').strip().lower() != 'true'
            or values.get('MARKET_AUDIO_AZURE_ENABLED', '').strip().lower() != 'true'
            or not values.get('AZURE_SPEECH_KEY', '').strip()
            or values.get('MARKET_AUDIO_SPEECH_REGION', '').strip().lower()
            not in {'eastus', 'westeurope', 'southeastasia', 'chinanorth3'}):
        return False
    try:
        return int(values.get('MARKET_AUDIO_MONTHLY_CHARACTER_LIMIT', '0')) > 0
    except (TypeError, ValueError):
        return False


class MarketAudioWorker:
    def __init__(self, database, provider, max_attempts=3, enabled=False, monthly_char_limit=None,
                 daily_only=False, eligible_daily_codes=None):
        self.database = database
        self.provider = provider
        self.max_attempts = max_attempts
        self.enabled = enabled
        self.daily_only = daily_only
        self.eligible_daily_codes = eligible_daily_codes
        configured_limit = monthly_char_limit if monthly_char_limit is not None else os.getenv('MARKET_AUDIO_MONTHLY_CHARACTER_LIMIT', '0')
        self.monthly_char_limit = int(configured_limit)
        if enabled and self.monthly_char_limit < 1:
            raise ValueError('An explicit positive monthly character limit is required to enable speech')

    def process_one(self):
        if not self.enabled:
            return None
        eligible_codes = self.eligible_daily_codes() if self.daily_only and self.eligible_daily_codes else None
        if self.daily_only and eligible_codes is None:
            return None
        job = self.database.claim(self.max_attempts, product_type='daily' if self.daily_only else None,
                                  codes=eligible_codes if self.daily_only else None)
        if job is None:
            return None
        try:
            source_text = job['sourceText']
            digest = hashlib.sha256(source_text.encode('utf-8')).hexdigest()
            if digest != job['sourceSha256']:
                raise ValueError('Source integrity check failed')
            spoken_text = (prepare_spoken_transcript(source_text)
                           if job['productType'] == 'daily' else source_text)
            character_counter = getattr(self.provider, 'billable_characters', None)
            if not callable(character_counter):
                raise ValueError('Speech provider must supply a billable character counter')
            try:
                self.database.reserve_monthly_characters(character_counter(spoken_text), self.monthly_char_limit)
            except AudioBudgetExceeded:
                self.database.finish_job(job['productType'], job['code'], job['revision'], 'blocked', 'AudioBudgetExceeded')
                return 'budget_blocked'
            audio, content_type, voice = self.provider.synthesize(spoken_text)
            if not audio or not content_type or not voice:
                raise ValueError('Provider returned incomplete audio')
            self.database.save(job['productType'], job['code'], job['revision'], source_text,
                               audio, content_type, voice)
            self.database.finish_job(job['productType'], job['code'], job['revision'], 'ready')
            return 'ready'
        except InvalidSpokenTranscript as exc:
            self.database.finish_job(job['productType'], job['code'], job['revision'], 'failed', type(exc).__name__[:80])
            return 'failed'
        except Exception as exc:
            status = 'retry' if job['attempts'] < self.max_attempts else 'failed'
            # Persist only the exception class, never provider messages that may contain credentials.
            self.database.finish_job(job['productType'], job['code'], job['revision'], status,
                                     type(exc).__name__[:80])
            return status
