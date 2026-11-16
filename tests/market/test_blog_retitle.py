"""2026-11-16: articles titled by their slug get descriptive titles and summaries; hand-edited titles are never overwritten."""
import json
import re
from pathlib import Path

import yaml

from maya_sawa.services import blog_retitle as br
from maya_sawa.services.blog import Conflict, Missing
from maya_sawa.services.blog_markdown import parse_markdown


class FakeBlog:
    def __init__(self, articles):
        self.articles, self.calls = articles, []

    def read(self, slug, admin=False):
        if slug not in self.articles:
            raise Missing()
        return {**self.articles[slug], 'etag': 'e1'}

    def save(self, slug, data, expected, editor):
        self.calls.append(('save', slug, data['title'], expected))
        self.articles[slug]['draft'] = data
        return {'etag': 'e2'}

    def action(self, slug, action, expected, editor):
        self.calls.append((action, slug, expected))


def article(title, published=True):
    return {'draft': {'title': title, 'description': '2024/03/16', 'content': 'body'}, 'published': 'rev' if published else None}


def test_slug_titled_article_gets_the_new_title_and_is_republished_with_the_new_etag():
    blog = FakeBlog({'redis': article('redis')})
    assert br.retitle('redis', '新標題', '新摘要', blog) == 'updated'
    assert blog.calls == [('save', 'redis', '新標題', 'e1'), ('publish', 'redis', 'e2')]
    assert blog.articles['redis']['draft']['content'] == 'body'           # the body is never touched
    assert br.retitle('redis', '新標題', '新摘要', blog) == 'skipped'      # second run does nothing


def test_a_date_only_title_counts_as_a_placeholder():
    blog = FakeBlog({'redis': article('2024/03/16')})
    assert br.retitle('redis', 't', 'd', blog) == 'updated'


def test_unpublished_draft_stays_a_draft():
    blog = FakeBlog({'redis': article('redis', published=False)})
    assert br.retitle('redis', 't', 'd', blog) == 'updated' and [c[0] for c in blog.calls] == ['save']


def test_hand_edited_title_and_missing_articles_are_left_alone():
    blog = FakeBlog({'redis': article('我自己改的標題')})
    assert br.retitle('redis', 't', 'd', blog) == 'skipped' and br.retitle('nope', 't', 'd', blog) == 'skipped' and blog.calls == []


def test_a_busy_article_is_a_conflict_and_one_failure_does_not_stop_the_rest():
    class Busy(FakeBlog):
        def save(self, slug, *a):
            if slug == 'a':
                raise Conflict()
            if slug == 'b':
                raise RuntimeError('db')
            return super().save(slug, *a)
    blog = Busy({'a': article('a'), 'b': article('b'), 'c': article('c')})
    counts = br.sync_titles(blog, {'a': ['t', 'd'], 'b': ['t', 'd'], 'c': ['t', 'd']})
    assert counts == {'updated': 1, 'skipped': 0, 'conflict': 1, 'failed': 1}


def test_every_new_title_describes_the_article_and_is_not_its_slug():
    titles = br.load_titles()
    assert len(titles) >= 60
    for slug, (title, description) in titles.items():
        assert title.lower() != slug and 12 <= len(title) <= 80, slug
        assert 25 <= len(description) <= 220 and not re.fullmatch(r'[\d/ -]+', description), slug


def test_archived_markdown_carries_the_same_titles_and_still_imports():
    archive = Path(__file__).resolve().parents[2] / 'docs' / 'blog-import'
    for slug, (title, description) in br.load_titles().items():
        _, draft = parse_markdown((archive / f'{slug}.md').read_text(encoding='utf-8'), slug)
        assert draft['title'] == title and draft['description'] == description, slug
