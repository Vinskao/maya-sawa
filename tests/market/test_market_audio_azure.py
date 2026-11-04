import pytest

from maya_sawa.services.azure_speech_rest import AzureSpeechRestProvider, VOICE


def test_provider_is_disabled_without_explicit_opt_in(monkeypatch):
    monkeypatch.delenv('MARKET_AUDIO_AZURE_ENABLED', raising=False)
    monkeypatch.setenv('AZURE_SPEECH_KEY', 'test-key')
    monkeypatch.setenv('MARKET_AUDIO_SPEECH_REGION', 'eastus')
    with pytest.raises(RuntimeError, match='disabled'):
        AzureSpeechRestProvider().synthesize('hello')


def test_rest_provider_posts_escaped_ssml_to_regional_endpoint(monkeypatch):
    monkeypatch.setenv('MARKET_AUDIO_AZURE_ENABLED', 'true')
    monkeypatch.setenv('AZURE_SPEECH_KEY', 'do-not-print-this')
    monkeypatch.setenv('MARKET_AUDIO_SPEECH_REGION', 'eastus')
    captured = {}

    def fake_urlopen(request, timeout):
        captured['url'] = request.full_url
        captured['headers'] = request.headers
        captured['body'] = request.data.decode()
        captured['timeout'] = timeout
        class Response:
            headers = {'Content-Type': 'audio/mpeg'}
            def read(self): return b'mp3-data'
            def __enter__(self): return self
            def __exit__(self, *args): return None
        return Response()

    monkeypatch.setattr('maya_sawa.services.azure_speech_rest.urllib.request.urlopen', fake_urlopen)
    audio, mime, voice = AzureSpeechRestProvider().synthesize('A & B <C>')
    assert audio == b'mp3-data' and mime == 'audio/mpeg'
    assert voice == 'zh-CN-Xiaoyu:DragonHDFlashLatestNeural'
    assert captured['url'] == 'https://eastus.tts.speech.microsoft.com/cognitiveservices/v1'
    assert captured['headers']['Ocp-apim-subscription-key'] == 'do-not-print-this'
    assert '<voice name="zh-CN-Xiaoyu:DragonHDFlashLatestNeural">A &amp; B &lt;C&gt;</voice>' in captured['body']
    assert captured['headers']['X-microsoft-outputformat'] == 'audio-24khz-48kbitrate-mono-mp3'


def test_provider_accepts_configured_uiobbeci_voice(monkeypatch):
    monkeypatch.setenv('MARKET_AUDIO_AZURE_ENABLED', 'true')
    monkeypatch.setenv('AZURE_SPEECH_KEY', 'fake-key')
    monkeypatch.setenv('MARKET_AUDIO_SPEECH_REGION', 'eastus')
    captured = []

    def fake_urlopen(request, timeout):
        captured.append(request.data.decode())
        class Response:
            headers = {'Content-Type': 'audio/mpeg'}
            def read(self): return b'mp3-data'
            def __enter__(self): return self
            def __exit__(self, *args): return None
        return Response()

    monkeypatch.setattr('maya_sawa.services.azure_speech_rest.urllib.request.urlopen', fake_urlopen)
    audio, mime, voice = AzureSpeechRestProvider(voice='zh-CN-Xiaoxiao2:DragonHDFlashLatestNeural').synthesize('你好')
    assert (audio, mime, voice) == (b'mp3-data', 'audio/mpeg', 'zh-CN-Xiaoxiao2:DragonHDFlashLatestNeural')
    assert '<voice name="zh-CN-Xiaoxiao2:DragonHDFlashLatestNeural">你好</voice>' in captured[0]
    assert VOICE == 'zh-CN-Xiaoyu:DragonHDFlashLatestNeural'


def test_provider_rejects_unsupported_region_and_missing_key(monkeypatch):
    monkeypatch.setenv('MARKET_AUDIO_AZURE_ENABLED', 'true')
    monkeypatch.setenv('AZURE_SPEECH_KEY', 'test-key')
    monkeypatch.setenv('MARKET_AUDIO_SPEECH_REGION', 'wrong-region')
    with pytest.raises(ValueError, match='region'):
        AzureSpeechRestProvider().synthesize('hello')
    monkeypatch.setenv('MARKET_AUDIO_SPEECH_REGION', 'eastus')
    monkeypatch.delenv('AZURE_SPEECH_KEY')
    with pytest.raises(RuntimeError, match='credential'):
        AzureSpeechRestProvider().synthesize('hello')


def test_long_text_is_split_under_request_limit_without_losing_any_content(monkeypatch):
    monkeypatch.setenv('MARKET_AUDIO_AZURE_ENABLED', 'true')
    monkeypatch.setenv('AZURE_SPEECH_KEY', 'fake')
    monkeypatch.setenv('MARKET_AUDIO_SPEECH_REGION', 'eastus')
    chunks = []
    def fake_urlopen(request, timeout):
        chunks.append(request.data.decode())
        class Response:
            headers = {'Content-Type': 'audio/mpeg'}
            def read(self): return f'part-{len(chunks)}|'.encode()
            def __enter__(self): return self
            def __exit__(self, *args): return None
        return Response()
    monkeypatch.setattr('maya_sawa.services.azure_speech_rest.urllib.request.urlopen', fake_urlopen)
    source = ('完整段落。' * 400) + '最後完整結尾。'
    provider = AzureSpeechRestProvider(chunk_limit=500, min_request_interval=0, sleep=lambda _: None,
                                       merge_parts=lambda parts: b''.join(parts))
    audio, _, _ = provider.synthesize(source)
    assert len(chunks) > 1
    assert all(len(body) < 3000 for body in chunks)
    inner_text = ''.join(body.split('<voice name="' + 'zh-CN-Xiaoyu:DragonHDFlashLatestNeural' + '">')[1].split('</voice>')[0] for body in chunks)
    from html import unescape
    assert unescape(inner_text) == source
    assert audio == b''.join(f'part-{index}|'.encode() for index in range(1, len(chunks) + 1))
