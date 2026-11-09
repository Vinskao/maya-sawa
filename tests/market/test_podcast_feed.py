import xml.etree.ElementTree as ET

from maya_sawa.services.podcast_feed import build_podcast_rss, describe_sources

ITUNES = '{http://www.itunes.com/dtds/podcast-1.0.dtd}'
CONFIG = {
    'title': 'Birch Investments 每日市場精讀',
    'description': '每日市場精讀。',
    'link': 'https://tymultiverse.cc/learn/',
    'language': 'zh-tw',
    'author': 'Birch Investments',
    'ownerName': 'Birch Investments',
    'ownerEmail': 'tianyikao@tymultiverse.cc',
    'imageUrl': 'https://tymultiverse.cc/images/podcast-cover.jpg',
    'category': 'Business',
    'subcategory': 'Investing',
    'audioBaseUrl': 'https://tymultiverse.cc/api/market/audio',
    'disclaimer': '本節目為 AI 合成語音，內容僅供參考，不構成投資建議。',
}


def episode(**overrides):
    row = {'id': 'a1b2', 'revision': 1, 'day': '2026-11-03', 'title': '淨流動性與聯發科的出貨驗證',
           'content': '第一段。第二段 & 風險 <測試>。', 'sources': ['stock:2330:2', 'macro-node:NET-LIQUIDITY:2',
                                                              'https://www.bls.gov/news.release/empsit.nr0.htm'],
           'createdAt': '2026-11-03T01:40:00+00:00', 'size': 719136}
    row.update(overrides)
    return row


def parse(items):
    return ET.fromstring(build_podcast_rss(items, CONFIG))


def test_channel_has_the_fields_spotify_requires():
    channel = parse([episode()]).find('channel')
    assert channel.find('title').text == 'Birch Investments 每日市場精讀'
    assert channel.find('language').text == 'zh-tw'
    assert channel.find(ITUNES + 'explicit').text == 'false'
    assert channel.find(ITUNES + 'owner/' + ITUNES + 'email').text == 'tianyikao@tymultiverse.cc'
    assert channel.find(ITUNES + 'image').get('href') == 'https://tymultiverse.cc/images/podcast-cover.jpg'
    category = channel.find(ITUNES + 'category')
    assert category.get('text') == 'Business' and category.find(ITUNES + 'category').get('text') == 'Investing'


def test_each_episode_has_title_enclosure_guid_and_date():
    item = parse([episode()]).find('channel/item')
    assert item.find('title').text == '淨流動性與聯發科的出貨驗證'
    enclosure = item.find('enclosure')
    assert enclosure.get('url') == 'https://tymultiverse.cc/api/market/audio/daily/a1b2/1'
    assert enclosure.get('type') == 'audio/mpeg' and enclosure.get('length') == '719136'
    guid = item.find('guid')
    assert guid.text == 'a1b2' and guid.get('isPermaLink') == 'false'
    assert item.find('pubDate').text == 'Tue, 03 Nov 2026 01:40:00 +0000'


def test_show_notes_list_readable_sources_and_the_disclaimer_with_escaping():
    notes = parse([episode()]).find('channel/item/description').text
    assert '第一段。' in notes and '&amp; 風險 &lt;測試&gt;' in notes
    assert 'TY Multiverse 個股分析 2330（第 2 版）' in notes
    assert 'TY Multiverse 總經分析 NET-LIQUIDITY（第 2 版）' in notes
    assert 'https://www.bls.gov/news.release/empsit.nr0.htm' in notes
    assert '不構成投資建議' in notes
    assert 'stock:2330:2' not in notes


def test_newest_episode_first_and_untitled_legacy_episode_gets_a_dated_title():
    older = episode(id='old', day='2026-11-02', title=None, createdAt='2026-11-02T01:40:00+00:00')
    newer = episode(id='new', day='2026-11-03')
    titles = [i.find('title').text for i in parse([older, newer]).findall('channel/item')]
    assert titles == ['淨流動性與聯發科的出貨驗證', '每日市場精讀｜2026/11/02']


def test_episode_without_audio_size_is_left_out_of_the_feed():
    items = parse([episode(id='ready'), episode(id='nosize', size=0)]).findall('channel/item')
    assert [i.find('guid').text for i in items] == ['ready']


def test_describe_sources_covers_known_reference_types_and_keeps_unknown_text():
    assert describe_sources(['stock:2330:2']) == ['TY Multiverse 個股分析 2330（第 2 版）']
    assert describe_sources(['macro-node:NET-LIQUIDITY:2']) == ['TY Multiverse 總經分析 NET-LIQUIDITY（第 2 版）']
    assert describe_sources(['https://example.com/a?b=1']) == ['https://example.com/a?b=1']
    assert describe_sources(['something-else']) == ['something-else']
