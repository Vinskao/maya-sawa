from maya_sawa.services.social.post_text import SITE_LINE, build_post


def source(content, kind='stock', code='2330'):
    return {'id': f'{kind}:{code}:4', 'productType': kind, 'code': code, 'revision': 4,
            'updatedAt': '2026-10-30T10:00:00+00:00', 'content': content}


def test_short_stock_post_is_verbatim_with_code_added_only_when_missing():
    assert build_post(source('結論：中性'), 'threads') == '2330\n\n結論：中性'
    assert build_post(source('2330 台積電｜結論：中性'), 'threads') == '2330 台積電｜結論：中性'


def test_macro_post_uses_the_shared_title():
    assert build_post(source('結論：中性', 'macro', 'US'), 'facebook') == '總經評論｜所有個股分析共用\n\n結論：中性'


def test_threads_keeps_the_front_within_500_and_appends_the_site_line():
    content = '2330 分析\n' + '需求強勁，毛利改善。' * 80
    post = build_post(source(content), 'threads')
    assert len(post) <= 500
    assert post.endswith('\n\n' + SITE_LINE)
    kept = post.removesuffix('\n\n' + SITE_LINE)
    assert content.startswith(kept)
    assert kept.endswith('。')  # cut at a sentence boundary, not mid-sentence


def test_site_link_is_not_repeated_when_the_kept_text_already_has_it():
    content = '2330 完整研究 https://tymultiverse.cc/ \n' + '內容。' * 400
    post = build_post(source(content), 'threads')
    assert post.count('tymultiverse.cc') == 1
    assert len(post) <= 500


def test_instagram_limit_is_2200_and_facebook_keeps_the_full_text():
    content = '2330 ' + '段落內容。' * 1000
    assert len(build_post(source(content), 'instagram')) <= 2200
    assert build_post(source(content), 'facebook') == content


def test_hard_cut_when_there_is_no_boundary_near_the_limit():
    content = '2330' + 'x' * 2000
    post = build_post(source(content), 'threads')
    assert len(post) == 500
    assert post.startswith('2330xxx')
    assert post.endswith(SITE_LINE)
