"""Checks for the reader-facing version of a daily reading.

The spoken script (content) is limited to commas and full stops so speech synthesis reads it cleanly, which makes it
a single glued block on a page. The reading version carries the same piece laid out for the eye: paragraphs separated
by a blank line, optional one-line `## ` section headings, ordinary punctuation and digits. It is never sent to
speech synthesis.
"""
import re

from .daily_maya_speech import _DOCUMENT_LANGUAGE

MAX_LENGTH = 20000
MIN_PARAGRAPHS = 3
MAX_PARAGRAPH_LENGTH = 600
HEADING = '## '
FAREWELL = '今天的市場精讀到這裡，我們下次見。'  # last sentence of every episode, in both versions


class InvalidReading(ValueError):
    """The reading version is not laid out for readers."""


def reading_blocks(text: str) -> list[tuple[str, str]]:
    """Split a reading version into ('heading' | 'paragraph', text) blocks."""
    blocks = []
    for block in re.split(r'\n\s*\n', text.replace('\r\n', '\n').strip()):
        block = block.strip()
        if not block:
            continue
        if block.startswith(HEADING) and '\n' not in block:
            blocks.append(('heading', block[len(HEADING):].strip()))
        else:
            blocks.append(('paragraph', block))
    return blocks


def validate_reading(text: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise InvalidReading('閱讀版是空的')
    text = text.replace('\r\n', '\n').strip()
    if len(text) > MAX_LENGTH:
        raise InvalidReading(f'閱讀版超過 {MAX_LENGTH} 字')
    if re.search(r'[<>`]|\*\*|__', text):
        raise InvalidReading('閱讀版不得有 HTML 或粗體等標記，只能用空行分段與「## 小標」')
    if _DOCUMENT_LANGUAGE.search(text):
        raise InvalidReading('閱讀版不得有來源、版本、資料截點、網址等製程用語')
    blocks = reading_blocks(text)
    paragraphs = [body for kind, body in blocks if kind == 'paragraph']
    if any(kind == 'heading' and not body for kind, body in blocks) or any(p.lstrip().startswith('#') for p in paragraphs):
        raise InvalidReading('小標只能是單獨一行的「## 小標文字」，前後各空一行')
    if len(paragraphs) < MIN_PARAGRAPHS:
        raise InvalidReading(f'閱讀版至少要有 {MIN_PARAGRAPHS} 段，段與段之間空一行')
    if any(len(p) > MAX_PARAGRAPH_LENGTH for p in paragraphs):
        raise InvalidReading(f'閱讀版每段不得超過 {MAX_PARAGRAPH_LENGTH} 字，請再分段')
    return text
