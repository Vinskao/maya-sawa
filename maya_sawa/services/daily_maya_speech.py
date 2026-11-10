"""Fail-closed checks and conservative cleanup for spoken Maya scripts."""
import re


_DOCUMENT_LANGUAGE = re.compile(
    r'版本更新時間|更新時間|底層資料|資料截點|資料截至|引用來源|來源網址|原始來源|'
    r'根據報告|根據分析|本站.{0,12}(?:版本|分析)|最近\s*24\s*小時|'
    r'僅作背景|不代表.{0,12}(?:即時|新消息)|尚未獨立核實|沒有再.{0,12}核實|'
    r'來源.{0,8}(?:核實|查證|引用)|(?:macro-node|stock):[A-Z0-9-]+:\d+|'
    r'https?://|www\.|(?<![A-Za-z0-9])(?:[A-Za-z0-9-]+\.)+(?:com|org|net|edu|gov|tw|cc|io|ai|co)(?:\b|/)', re.I)
_MARKDOWN = re.compile(r'(?m)^\s{0,3}#{1,6}\s*|\*\*|__|`{1,3}|~~')
_DATE = re.compile(r'(?<!\d)(20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)')
_CLOCK = re.compile(r'(?<!\d)(\d{1,2}):(\d{2})(?!\d)')
_PERCENT = re.compile(r'(?<!\d)(\d+(?:\.\d+)?)\s*%')
_THOUSANDS = re.compile(r'(?<=\d),(?=\d{3}(?:\D|$))')
_ALLOWED = re.compile(r'^[\u3400-\u4dbf\u4e00-\u9fffA-Za-z0-9\s，。.]*$')


class InvalidSpokenTranscript(ValueError):
    """Transcript is unsuitable for speech and must not be sent to a provider."""


def _clean_formatting(text: str) -> str:
    text = _MARKDOWN.sub('', text)
    text = _DATE.sub(lambda m: f'{int(m[1])}年{int(m[2])}月{int(m[3])}日', text)
    text = _CLOCK.sub(lambda m: f'{int(m[1])}點{int(m[2])}分', text)
    # Ticker separators are not speech punctuation; retain both ticker components.
    text = re.sub(r'(?<=[A-Za-z])[-.](?=[A-Za-z])', ' ', text)
    # A numeric range is spoken with 到, preserving both endpoints.
    text = re.sub(r'(?<=\d)[–—-](?=\d)', '到', text)
    text = re.sub(r'(?<![A-Za-z0-9])-(?=\d)', '負', text)
    text = re.sub(r'(?<![A-Za-z0-9])\+(?=\d)', '正', text)
    text = _PERCENT.sub(lambda m: f'百分之{m[1]}', text)
    text = _THOUSANDS.sub('', text)
    # 頓號 is a spoken pause between list items; read it as a comma instead of failing the whole day's audio.
    text = text.replace('、', '，')
    # Paragraph boundaries carry no audible content; keep sentence punctuation intact.
    return re.sub(r'\s+', ' ', text).strip()


def validate_spoken_transcript(text: str) -> str:
    """Reject source/document residue and any unsupported spoken punctuation."""
    if not isinstance(text, str) or not text.strip():
        raise InvalidSpokenTranscript('Empty spoken transcript')
    # Check source references before any safe punctuation cleanup can obscure them.
    if _DOCUMENT_LANGUAGE.search(text):
        raise InvalidSpokenTranscript('Transcript contains document metadata')
    cleaned = _clean_formatting(text)
    if _DOCUMENT_LANGUAGE.search(cleaned):
        raise InvalidSpokenTranscript('Transcript contains document metadata')
    if not _ALLOWED.fullmatch(cleaned):
        raise InvalidSpokenTranscript('Transcript contains unsupported punctuation or symbols')
    # ASCII period is permitted only as a decimal point, never sentence punctuation.
    if re.search(r'(?<!\d)\.|\.(?!\d)', cleaned):
        raise InvalidSpokenTranscript('Transcript contains non-spoken punctuation')
    return cleaned


def prepare_spoken_transcript(text: str) -> str:
    """Clean safe formatting and validate before a provider sees transcript text."""
    return validate_spoken_transcript(text)
