"""Instagram needs an image on every post, so each analysis gets a plain text card rendered from its public content."""
import io
import os
import re
from datetime import datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

CARD_SIZE = (1080, 1350)
TAIPEI = ZoneInfo('Asia/Taipei')
FONT_DIR = os.getenv('SOCIAL_CARD_FONT_DIR', '/usr/share/fonts/noto-tc')
TOKEN = re.compile(r'[A-Za-z0-9.,%+\-/:]+ ?|.', re.S)
BACKGROUND, INK, MUTED, ACCENT = (20, 35, 28), (241, 236, 224), (170, 182, 172), (214, 178, 94)
MARGIN = 88


def wrap(text, width, measure):
    """Lines no wider than `width`: CJK breaks between characters, Latin words stay whole, blank lines are kept."""
    lines = []
    for paragraph in text.split('\n'):
        line = ''
        for token in TOKEN.findall(paragraph):
            if line and measure(line + token.rstrip()) > width:
                lines.append(line)
                line = token.lstrip() if token.strip() else ''
            else:
                line += token
        lines.append(line)
    return lines


def card_text(source):
    updated = datetime.fromisoformat(source['updatedAt']).astimezone(TAIPEI)
    title = '總經評論' if source['productType'] == 'macro' else source['code']
    return {'title': title, 'meta': f"AI 分析 rev {source['revision']} · {updated:%Y-%m-%d}",
            'body': source['content'].strip()}


@lru_cache(maxsize=8)
def _font(weight, size):
    path = os.path.join(FONT_DIR, f'NotoSansTC-{weight}.otf')
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)  # tests and local runs without the bundled CJK font


def render_card(source):
    text = card_text(source)
    image = Image.new('RGB', CARD_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    width = CARD_SIZE[0] - 2 * MARGIN
    draw.rectangle([MARGIN, 96, MARGIN + 72, 104], fill=ACCENT)
    draw.text((MARGIN, 128), 'BIRCH INVESTMENTS', font=_font('Bold', 34), fill=ACCENT)
    draw.text((MARGIN, 196), text['title'], font=_font('Bold', 88), fill=INK)
    draw.text((MARGIN, 318), text['meta'], font=_font('Regular', 34), fill=MUTED)
    body_font = _font('Regular', 40)
    line_height = 62
    top, bottom = 410, CARD_SIZE[1] - 170
    lines = [line for line in wrap(text['body'], width, lambda value: draw.textlength(value, font=body_font))]
    room = (bottom - top) // line_height
    if len(lines) > room:
        lines = lines[:room]
        lines[-1] = lines[-1].rstrip()[:-1] + '…' if lines[-1].strip() else '…'
    for index, line in enumerate(lines):
        draw.text((MARGIN, top + index * line_height), line, font=body_font, fill=INK)
    draw.line([MARGIN, CARD_SIZE[1] - 140, CARD_SIZE[0] - MARGIN, CARD_SIZE[1] - 140], fill=MUTED, width=2)
    draw.text((MARGIN, CARD_SIZE[1] - 112), 'AI 輔助研究 · 非投資建議 · tymultiverse.cc', font=_font('Regular', 30), fill=MUTED)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()
