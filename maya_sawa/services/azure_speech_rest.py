"""Azure Speech REST adapter. It is opt-in and reads credentials only from process env."""
from html import escape
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from .market_audio_text import split_speech_text


VOICE = 'zh-CN-Xiaoyu:DragonHDFlashLatestNeural'
SUPPORTED_REGIONS = {'eastus', 'westeurope', 'southeastasia', 'chinanorth3'}
OUTPUT_FORMAT = 'audio-24khz-48kbitrate-mono-mp3'


def merge_mp3_parts(parts, ffmpeg=None):
    if not parts or any(not part for part in parts):
        raise ValueError('Nonempty MP3 parts are required')
    if len(parts) == 1:
        return parts[0]
    executable = ffmpeg or os.getenv('FFMPEG_PATH', 'ffmpeg')
    try:
        with tempfile.TemporaryDirectory(prefix='market-audio-') as directory:
            root = Path(directory)
            files = []
            for index, part in enumerate(parts):
                path = root / f'part-{index:04d}.mp3'
                path.write_bytes(part)
                files.append(path.resolve().as_posix().replace("'", "\\'"))
            listing = root / 'concat.txt'
            listing.write_text(''.join(f"file '{path}'\n" for path in files), encoding='utf-8')
            output = root / 'merged.mp3'
            subprocess.run([executable, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat',
                            '-safe', '0', '-i', str(listing), '-map', '0:a:0', '-c:a', 'copy',
                            '-map_metadata', '-1', str(output)], check=True, capture_output=True, timeout=120)
            merged = output.read_bytes()
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError('MP3 segments could not be merged into playable audio') from None
    if not merged:
        raise RuntimeError('MP3 merge returned empty audio')
    return merged


class AzureSpeechRestProvider:
    def __init__(self, environ=None, opener=None, timeout=30, chunk_limit=2000,
                 min_request_interval=3.1, sleep=time.sleep, monotonic=time.monotonic,
                 merge_parts=merge_mp3_parts, voice=None):
        self.environ = environ if environ is not None else os.environ
        self.opener = opener or urllib.request.urlopen
        self.timeout = timeout
        self.chunk_limit = chunk_limit
        self.min_request_interval = min_request_interval
        self.sleep = sleep
        self.monotonic = monotonic
        self.merge_parts = merge_parts
        self.voice = voice or VOICE
        self.last_request_at = None

    @property
    def enabled(self):
        return self.environ.get('MARKET_AUDIO_AZURE_ENABLED', '').strip().lower() == 'true'

    @staticmethod
    def billable_characters(text):
        # SSML contains only the required speak/voice wrappers; metered text is XML escaped.
        return len(escape(text, quote=False))

    def synthesize(self, text, voice=None):
        if not self.enabled:
            raise RuntimeError('Azure Speech provider is disabled')
        if not isinstance(text, str) or not text.strip():
            raise ValueError('Speech text is required')
        region = self.environ.get('MARKET_AUDIO_SPEECH_REGION', '').strip().lower()
        if region not in SUPPORTED_REGIONS:
            raise ValueError('Unsupported Azure Speech region')
        key = self.environ.get('AZURE_SPEECH_KEY', '').strip()
        if not key:
            raise RuntimeError('Azure Speech credential is not configured')
        if self.chunk_limit < 1:
            raise ValueError('Speech chunk limit must be positive')
        voice = voice or self.voice
        if not isinstance(voice, str) or not voice.strip() or len(voice) > 128:
            raise ValueError('Speech voice is invalid')
        chunks = split_speech_text(text, self.chunk_limit)
        audio_parts = []
        for chunk in chunks:
            if self.last_request_at is not None and self.min_request_interval > 0:
                wait = self.min_request_interval - (self.monotonic() - self.last_request_at)
                if wait > 0:
                    self.sleep(wait)
            ssml = (
                '<speak version="1.0" xml:lang="zh-CN">'
                f'<voice name="{escape(voice, quote=True)}">{escape(chunk, quote=False)}</voice>'
                '</speak>'
            )
            request = urllib.request.Request(
                f'https://{region}.tts.speech.microsoft.com/cognitiveservices/v1',
                data=ssml.encode('utf-8'),
                headers={
                    'Ocp-Apim-Subscription-Key': key,
                    'Content-Type': 'application/ssml+xml',
                    'X-Microsoft-OutputFormat': OUTPUT_FORMAT,
                    'User-Agent': 'TY-Multiverse-MarketAudio',
                }, method='POST',
            )
            self.last_request_at = self.monotonic()
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    audio = response.read()
                    content_type = response.headers.get('Content-Type', 'audio/mpeg').split(';', 1)[0]
            except (urllib.error.URLError, TimeoutError, OSError):
                # Keep URL/key/provider response details out of app logs and persisted job errors.
                raise RuntimeError('Azure Speech request failed') from None
            if not audio:
                raise RuntimeError('Azure Speech returned empty audio')
            if content_type not in {'audio/mpeg', 'audio/mp3'}:
                raise RuntimeError('Azure Speech returned an unexpected audio format')
            audio_parts.append(audio)
        return self.merge_parts(audio_parts), 'audio/mpeg', voice
