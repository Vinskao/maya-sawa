"""2026-11-16: the daily narration is angry after a TAIEX drop of 2% or more, cheerful after a rise of 2% or more, otherwise normal.
Only newly synthesized episodes get a tone."""
import io
from datetime import date

import pytest

from maya_sawa.services import azure_speech_rest as az
from maya_sawa.services import voice_tone as vt
from maya_sawa.services.market_audio_worker import MarketAudioWorker

TODAY = date(2026, 11, 17)


def test_tone_follows_the_two_percent_rule_at_the_boundaries():
    assert [vt.tone_for_change(p) for p in (-3.1, -2.0, -1.99, 0, 1.99, 2.0, 5)] == ["angry", "angry", "normal", "normal", "normal", "cheerful", "cheerful"]
    assert vt.tone_for_change(None) == "normal"


def test_last_session_change_ignores_todays_unfinished_bar_and_needs_two_days():
    closes = [(date(2026, 11, 12), 100.0), (date(2026, 11, 13), 98.0), (date(2026, 11, 17), 90.0)]
    assert vt.last_session_change(closes, TODAY) == -2.0           # 11/13 vs 11/12; today's partial 90 is not used
    assert vt.last_session_change([(date(2026, 11, 13), 98.0)], TODAY) is None


def test_current_tone_is_normal_when_the_quote_cannot_be_read():
    def boom():
        raise RuntimeError("yahoo down")
    assert vt.current_tone(TODAY, fetch=boom) == ("normal", None)
    assert vt.current_tone(TODAY, fetch=lambda: [(date(2026, 11, 12), 100.0), (date(2026, 11, 13), 97.0)]) == ("angry", -3.0)


class Opener:
    def __init__(self):
        self.bodies = []

    def __call__(self, request, timeout=None):
        self.bodies.append(request.data.decode("utf-8"))
        response = io.BytesIO(b"ID3audio")
        response.headers = {"Content-Type": "audio/mpeg"}
        return response


def provider(opener):
    return az.AzureSpeechRestProvider(environ={"MARKET_AUDIO_AZURE_ENABLED": "true", "MARKET_AUDIO_SPEECH_REGION": "eastus", "AZURE_SPEECH_KEY": "k"},
                                      opener=opener, min_request_interval=0, merge_parts=lambda parts: b"".join(parts))


def test_a_style_wraps_the_text_in_express_as_with_the_mstts_namespace():
    opener = Opener()
    provider(opener).synthesize("昨天大跌。", voice="zh-CN-XiaoyiNeural", style="angry")
    ssml = opener.bodies[0]
    assert 'xmlns:mstts="https://www.w3.org/2001/mstts"' in ssml
    assert '<mstts:express-as style="angry" styledegree="1.5">昨天大跌。</mstts:express-as>' in ssml


def test_without_a_style_the_ssml_is_exactly_what_it_was_before():
    opener = Opener()
    provider(opener).synthesize("一般。", voice="zh-CN-XiaoyiNeural")
    assert opener.bodies[0] == '<speak version="1.0" xml:lang="zh-CN"><voice name="zh-CN-XiaoyiNeural">一般。</voice></speak>'


def test_an_unknown_style_is_refused_instead_of_being_sent():
    with pytest.raises(ValueError):
        provider(Opener()).synthesize("x", style="shouting<script>")


def test_text_with_markup_characters_stays_escaped_inside_the_style_tag():
    opener = Opener()
    provider(opener).synthesize("A<B & C", voice="v", style="cheerful")
    assert "A&lt;B &amp; C" in opener.bodies[0]


# ---- worker: tone only for new daily episodes ----
class Db:
    def __init__(self, product="daily"):
        self.job = {"productType": product, "code": "2026-11-17", "revision": 1, "attempts": 1, "sourceText": "今天先看大盤。", "sourceSha256": None}
        import hashlib
        self.job["sourceSha256"] = hashlib.sha256(self.job["sourceText"].encode()).hexdigest()
        self.saved = []

    def claim(self, *a, **k):
        return self.job

    def reserve_monthly_characters(self, n, limit):
        return n

    def monthly_reserved_characters(self):
        return 1

    def save(self, *a):
        self.saved.append(a)

    def finish_job(self, *a, **k):
        self.status = a[3]


class Provider:
    def __init__(self):
        self.calls = []

    @staticmethod
    def billable_characters(text):
        return len(text)

    def synthesize(self, text, voice=None, style=None):
        self.calls.append({"voice": voice, "style": style})
        return b"mp3", "audio/mpeg", voice or "zh-CN-Xiaoqi"


def run(tone_provider, product="daily"):
    provider_ = Provider()
    worker = MarketAudioWorker(Db(product), provider_, enabled=True, monthly_char_limit=1000, tone_provider=tone_provider,
                               daily_brief_day=lambda code: date(2026, 11, 17))
    return worker.process_one(), provider_.calls[0]


def test_worker_passes_the_style_for_a_daily_episode_after_a_big_drop_or_rise():
    assert run(lambda: ("angry", -2.5))[1]["style"] == "angry"
    assert run(lambda: ("cheerful", 2.4))[1]["style"] == "cheerful"


def test_worker_keeps_the_normal_voice_for_a_calm_day_a_failure_or_no_tone_provider():
    def boom():
        raise RuntimeError("x")
    assert run(lambda: ("normal", 0.3))[1]["style"] is None
    assert run(boom)[1]["style"] is None
    assert run(None)[1]["style"] is None


def test_stock_and_macro_audio_never_gets_a_tone():
    assert run(lambda: ("angry", -3.0), product="macro")[1]["style"] is None


def test_a_provider_without_style_support_still_works_when_the_tone_is_normal():
    class Old(Provider):
        def synthesize(self, text, voice=None):
            self.calls.append({"voice": voice, "style": None})
            return b"mp3", "audio/mpeg", voice or "v"
    provider_ = Old()
    worker = MarketAudioWorker(Db(), provider_, enabled=True, monthly_char_limit=1000, tone_provider=lambda: ("normal", 0.0),
                               daily_brief_day=lambda code: date(2026, 11, 17))
    assert worker.process_one() == "ready"
