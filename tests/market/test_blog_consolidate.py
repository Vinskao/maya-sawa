"""2026-11-16: overlapping /work articles are merged mechanically into one URL; empty ones go to the recoverable bin."""
from maya_sawa.services import blog_consolidate as bc
from maya_sawa.services.blog import Missing


class FakeBlog:
    def __init__(self, articles):
        self.articles, self.log = articles, []

    def read(self, slug, admin=False):
        if slug not in self.articles:
            raise Missing()
        a = self.articles[slug]
        return {'draft': a['draft'], 'published': a.get('published'), 'deleted': a.get('deleted', False), 'etag': a.get('etag', 'e')}

    def save(self, slug, data, expected, editor):
        self.articles[slug]['draft'] = data
        self.log.append(('save', slug))
        return {'etag': 'e2'}

    def action(self, slug, action, expected, editor):
        self.log.append((action, slug))
        if action == 'delete':
            self.articles[slug]['deleted'] = True
        return {'etag': 'e3'}


def art(title, content, published=True):
    return {'draft': {'title': title, 'description': 'd', 'content': content}, 'published': 'rev' if published else None}


GROUP = {'into': 'a', 'from': ['b'], 'title': '合併後標題', 'description': '合併後摘要'}


def test_demote_pushes_headings_down_but_leaves_code_fences_alone():
    text = '# 標題\n\n## 小節\n\n```python\n# comment\n```\n\n### 更小'
    assert bc.demote(text) == '\n'.join(['## 小節'.replace('## ', '### '), '', '```python', '# comment', '```', '', '#### 更小']).strip()


def test_merge_appends_the_body_under_its_title_republishes_and_bins_the_absorbed_article():
    blog = FakeBlog({'a': art('A 原標題', '## 主文\n\n內容 A'), 'b': art('B 標題', '## 細節\n\n內容 B')})
    assert bc.merge_group(GROUP, blog) == {'merged': 1, 'skipped': 0}
    draft = blog.articles['a']['draft']
    assert draft['title'] == '合併後標題' and draft['description'] == '合併後摘要'
    assert draft['content'].startswith('## 主文') and '## B 標題' in draft['content'] and '### 細節' in draft['content'] and '內容 B' in draft['content']
    assert blog.log == [('save', 'a'), ('publish', 'a'), ('delete', 'b')]


def test_a_draft_target_stays_a_draft():
    blog = FakeBlog({'a': art('A', 'x', published=False), 'b': art('B', 'y')})
    bc.merge_group(GROUP, blog)
    assert ('publish', 'a') not in blog.log


def test_running_twice_does_nothing_the_second_time():
    blog = FakeBlog({'a': art('A', 'x'), 'b': art('B', 'y')})
    bc.merge_group(GROUP, blog)
    before = list(blog.log)
    assert bc.merge_group(GROUP, blog) == {'merged': 0, 'skipped': 1} and blog.log == before


def test_a_body_already_inside_the_target_is_not_appended_again():
    blog = FakeBlog({'a': art('A', 'x\n\n## B\n\n同一段內容'), 'b': art('B', '同一段內容')})
    bc.merge_group(GROUP, blog)
    assert blog.articles['a']['draft']['content'].count('同一段內容') == 1


def test_missing_target_skips_the_group_and_keeps_the_absorbed_article():
    blog = FakeBlog({'b': art('B', 'y')})
    assert bc.merge_group(GROUP, blog) == {'merged': 0, 'skipped': 1} and blog.log == []


def test_consolidate_merges_deletes_and_survives_a_failing_group():
    class Flaky(FakeBlog):
        def save(self, slug, *a):
            if slug == 'x':
                raise RuntimeError('db')
            return super().save(slug, *a)
    blog = Flaky({'a': art('A', 'x'), 'b': art('B', 'y'), 'x': art('X', 'x'), 'y': art('Y', 'y'), 'gone': art('G', 'g')})
    plan = {'merge': [{**GROUP, 'into': 'x', 'from': ['y']}, GROUP], 'delete': ['gone', 'never-existed']}
    assert bc.consolidate(blog, plan) == {'merged': 1, 'deleted': 1, 'skipped': 1, 'conflict': 0, 'failed': 1}
    assert blog.articles['gone']['deleted'] and not blog.articles['y'].get('deleted')


def test_the_real_plan_is_consistent():
    plan = bc.load_plan()
    removed = plan['delete'] + [s for g in plan['merge'] for s in g['from']]
    targets = [g['into'] for g in plan['merge']]
    assert len(removed) == len(set(removed)) == 20 and not set(removed) & set(targets) and len(targets) == len(set(targets))
    assert all(12 <= len(g['title']) <= 90 and 25 <= len(g['description']) <= 220 for g in plan['merge'])
