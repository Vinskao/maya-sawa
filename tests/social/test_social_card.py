import io

from PIL import Image

from pathlib import Path

from maya_sawa.services.social.card import CARD_SIZE, card_text, parse_card, render_card, wrap

ANALYSIS_6187 = (Path(__file__).parents[1] / 'fixtures' / 'analysis_6187.txt').read_text(encoding='utf-8')


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


def test_parse_card_reads_name_verdict_tags_date_and_close_from_a_real_analysis():
    """The card the owner wants on every platform (2026-11-02): 6187 萬潤 / DATA AS OF / 買（維持） / tags / 收盤."""
    source = {'productType': 'stock', 'code': '6187', 'revision': 13, 'updatedAt': '2026-10-28T12:00:00+00:00',
              'content': ANALYSIS_6187}
    assert parse_card(source) == {
        'code': '6187', 'name': '萬潤', 'asOf': '2026.10.28', 'verdict': '買（維持）',
        'tags': '循環順風 · 技術力中性 · 交貨順風', 'close': '10/28 收盤  1,345  （+4.67%）'}


def test_parse_card_degrades_gracefully_when_fields_are_missing():
    source = {'productType': 'stock', 'code': '2330', 'revision': 1, 'updatedAt': '2026-10-30T10:00:00+00:00',
              'content': '沒有結論格式的文字'}
    card = parse_card(source)
    assert card['code'] == '2330' and card['verdict'] == '' and card['close'] == '' and card['tags'] == ''
    assert card['asOf'] == '2026.10.30'  # falls back to the revision date (Taipei)
    macro = {'productType': 'macro', 'code': 'US', 'revision': 9, 'updatedAt': '2026-10-27T10:00:00+00:00',
             'content': '結論：中性。通膨降溫。'}
    assert parse_card(macro)['code'] == '總經評論' and parse_card(macro)['verdict'] == '中性'


def test_card_footer_uses_the_new_domain_and_the_card_still_renders_for_a_real_analysis():
    source = {'productType': 'stock', 'code': '6187', 'revision': 13, 'updatedAt': '2026-10-28T12:00:00+00:00',
              'content': ANALYSIS_6187}
    assert Image.open(io.BytesIO(render_card(source))).size == CARD_SIZE
    from maya_sawa.services.social import card
    assert card.FOOTER_URL == 'tymultiverse.cc' and 'tatdvsonorth' not in card.FOOTER_URL


def test_fit_size_shrinks_text_until_it_fits_the_card_width_but_never_below_the_minimum():
    """2026-11-02 production (8996): '中立（由買改為中立）' at a fixed size ran off the right edge of the card."""
    from maya_sawa.services.social.card import fit_size
    cjk = lambda text, size: len(text) * size  # every character is a full-width square
    assert fit_size('買（維持）', 150, 48, 904, cjk) == 150  # short text keeps the big size
    size = fit_size('中立（由買改為中立）', 150, 48, 904, cjk)
    assert 48 <= size < 150 and cjk('中立（由買改為中立）', size) <= 904
    assert fit_size('很長' * 40, 150, 48, 904, cjk) == 48  # at the floor it stops (caller wraps or clips)


def test_card_text_sizes_all_fit_inside_the_margins_for_the_longest_real_verdict():
    from maya_sawa.services.social.card import CARD_SIZE, MARGIN, card_font_sizes
    cjk = lambda text, size: len(text) * size
    card = {'code': '8996', 'name': '高力熱處理工業', 'asOf': '2026.10.28', 'verdict': '中立（由買改為中立）',
            'tags': '循環順風 · 技術力中性 · 交貨中性', 'close': '10/28 收盤  1,585  （+8.19%）'}
    sizes = card_font_sizes(card, cjk)
    width = CARD_SIZE[0] - 2 * MARGIN
    assert cjk(card['verdict'], sizes['verdict']) <= width
    assert cjk(f"{card['code']}    {card['name']}", sizes['headline']) <= width
    assert cjk(card['tags'].replace(' · ', '  ·  '), sizes['tags']) <= width
    assert cjk(card['close'], sizes['close']) <= width
