"""Every post (Facebook, Instagram, Threads) carries one summary card rendered from the analysis: ticker, name, data date,
verdict, tags, close."""
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
BG, WHITE, DIM, LINE = (10, 10, 11), (244, 244, 244), (150, 150, 155), (70, 70, 76)  # the black card of the owner's reference image
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


FOOTER_URL = 'tymultiverse.cc'
VERDICT = re.compile(r'結論[：:]\s*([^。\n]+)。?([^\n]*)')
HEADER_VERDICT = re.compile(r'^【結論】\s*(\S+)')
AS_OF = re.compile(r'資料截點[：:]\s*本站\s*(\d{4})-(\d{2})-(\d{2})')
CLOSE = re.compile(r'(\d{1,2}/\d{1,2})\s*收\s*([\d,\.]+)\s*[（(]([+\-−]?[\d\.]+%)[）)]')


def parse_card(source):
    """Fields of the owner's card (ticker, name, data date, verdict, tags, close) read from the analysis text.
    Missing pieces come back empty so the card still renders."""
    content = source['content'].strip()
    lines = [line.strip() for line in content.split('\n') if line.strip()]
    updated = datetime.fromisoformat(source['updatedAt']).astimezone(TAIPEI)
    macro = source['productType'] == 'macro'
    verdict = tags = close = name = ''
    match = VERDICT.search(content)
    if match:
        verdict = match.group(1).strip()
        rest = match.group(2)
        tags = ' · '.join(part.strip() for part in re.split(r'[、，,]', rest.split('時機')[0].strip(' 。')) if part.strip())
    elif lines and HEADER_VERDICT.match(lines[0]):
        verdict = HEADER_VERDICT.match(lines[0]).group(1)
    price = CLOSE.search(content)
    if price:
        close = f'{price.group(1)} 收盤  {price.group(2)}  （{price.group(3)}）'
    if not macro:
        for line in lines[:3]:
            if '｜' in line and not line.startswith('【'):
                name = line.split('｜', 1)[0].strip()
                break
    as_of = AS_OF.search(content)
    date = '.'.join(as_of.groups()) if as_of else f'{updated:%Y.%m.%d}'
    return {'code': '總經評論' if macro else source['code'], 'name': name, 'asOf': date, 'verdict': verdict,
            'tags': tags, 'close': close}


@lru_cache(maxsize=8)
def _font(weight, size):
    path = os.path.join(FONT_DIR, f'NotoSansTC-{weight}.otf')
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)  # tests and local runs without the bundled CJK font


def render_card(source):
    card = parse_card(source)
    image = Image.new('RGB', CARD_SIZE, BG)
    draw = ImageDraw.Draw(image)
    width = CARD_SIZE[0] - 2 * MARGIN
    draw.rounded_rectangle([40, 40, CARD_SIZE[0] - 40, CARD_SIZE[1] - 40], radius=28, outline=LINE, width=3)
    left = MARGIN
    draw.text((left, 100), 'BIRCH INVESTMENTS', font=_font('Bold', 44), fill=WHITE)
    draw.text((left, 164), '樺樹資本工具', font=_font('Regular', 32), fill=DIM)
    draw.line([left, 236, left + width, 236], fill=LINE, width=2)
    headline = f"{card['code']}    {card['name']}".rstrip()
    draw.text((left, 276), headline, font=_font('Bold', 84), fill=WHITE)
    draw.text((left, 400), f"DATA AS OF {card['asOf']}", font=_font('Regular', 30), fill=DIM)
    verdict_font = _font('Bold', 150 if len(card['verdict']) <= 6 else 110)
    draw.text((left, 480), card['verdict'] or '—', font=verdict_font, fill=WHITE)
    draw.text((left, 690), card['tags'].replace(' · ', '  ·  '), font=_font('Regular', 38), fill=DIM)
    draw.line([left, 790, left + width, 790], fill=LINE, width=2)
    if card['close']:
        draw.text((left, 830), card['close'], font=_font('Regular', 48), fill=WHITE)
    draw.text((left, 1090), '完整研究與資料來源', font=_font('Regular', 32), fill=DIM)
    draw.text((left, 1146), FOOTER_URL, font=_font('Regular', 38), fill=WHITE)
    draw.text((left, 1236), 'TY MARKET LAB · TY MULTIVERSE', font=_font('Regular', 26), fill=DIM)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG', optimize=True)
    return buffer.getvalue()
