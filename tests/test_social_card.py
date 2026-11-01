import io

from PIL import Image

from maya_sawa.services.social.card import CARD_SIZE, card_text, render_card, wrap


def test_wrap_breaks_cjk_by_character_and_keeps_latin_words_whole():
    assert wrap('台積電毛利率改善', 4, len) == ['台積電毛', '利率改善']
    assert wrap('AI capex 強', 6, len) == ['AI ', 'capex ', '強']
    assert wrap('第一段\n\n第二段', 10, len) == ['第一段', '', '第二段']


def test_card_text_uses_title_revision_and_taipei_date():
    stock = {'productType': 'stock', 'code': '2330', 'revision': 4,
             'updatedAt': '2026-10-30T17:30:00+00:00', 'content': '結論：中性'}
    text = card_text(stock)
    assert text['title'] == '2330'
    assert text['meta'] == 'AI 分析 rev 4 · 2026-10-31'  # 17:30 UTC is the next day in Taipei
    assert text['body'] == '結論：中性'
    macro = dict(stock, productType='macro', code='US')
    assert card_text(macro)['title'] == '總經評論'


def test_render_card_returns_a_portrait_png_even_for_long_text():
    source = {'productType': 'stock', 'code': '2330', 'revision': 4,
              'updatedAt': '2026-10-30T10:00:00+00:00', 'content': '需求強勁。' * 600}
    image = Image.open(io.BytesIO(render_card(source)))
    assert image.format == 'PNG'
    assert image.size == CARD_SIZE == (1080, 1350)
