"""2026-11-16: approved daily readings are also published as /blog articles, once per day, with no AI in the path."""
from maya_sawa.services import daily_reading_blog as drb
from maya_sawa.services.blog import Missing


class FakeBlog:
    def __init__(self):
        self.articles, self.published = {}, []

    def read(self, slug, admin=False):
        if slug not in self.articles:
            raise Missing()
        return self.articles[slug]

    def save(self, slug, data, expected, editor):
        self.articles[slug] = data
        return {'etag': 'e1'}

    def action(self, slug, action, expected, editor):
        self.published.append((slug, action, editor))


ROW = {'id': 'r1', 'day': '2026-11-16', 'title': '台積電法說後的判斷', 'content': '今天先看總經。再看個股。',
       'reading': '## 總經\n\n今天先看總經，利率維持不變。\n\n## 個股\n\n再看個股。', 'sources': ['stock:2330:2', 'https://example.com/a']}


def test_slug_is_one_per_day():
    assert drb.slug_for('2026-11-16') == 'daily-reading-2026-11-16'


def test_draft_uses_the_reader_layout_title_sources_and_taipei_morning():
    d = drb.to_draft(ROW)
    assert d['title'] == '台積電法說後的判斷' and d['content'].startswith('## 總經')
    assert '## 資料來源' in d['content'] and '- <https://example.com/a>' in d['content'] and '- stock:2330:2' in d['content']
    assert d['publishDate'] == '2026-11-16T09:00:00+08:00' and d['tags'][0] == 'Quant Finance'


def test_without_a_reading_layout_the_spoken_text_is_split_into_paragraphs():
    d = drb.to_draft({**ROW, 'reading': None})
    assert '今天先看總經。\n\n再看個股。' in d['content']


def test_missing_title_falls_back_to_the_dated_default():
    assert drb.to_draft({**ROW, 'title': None})['title'] == '每日市場精讀｜2026/11/16'


def test_publish_creates_then_publishes_and_a_second_run_does_nothing():
    blog = FakeBlog()
    assert drb.publish_to_blog(ROW, blog) == 'created'
    assert blog.published == [('daily-reading-2026-11-16', 'publish', 'daily-maya')]
    assert drb.publish_to_blog(ROW, blog) == 'exists' and len(blog.published) == 1


def test_backfill_counts_and_one_failure_does_not_stop_the_rest():
    blog = FakeBlog()
    bad = {**ROW, 'day': '2026-11-15', 'title': None, 'content': '', 'reading': '', 'sources': []}
    counts = drb.sync_published([ROW, bad, ROW], blog)
    assert counts['created'] == 1 and counts['exists'] == 1 and counts['failed'] == 1
