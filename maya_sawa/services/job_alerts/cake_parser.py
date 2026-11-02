"""Parse CakeResume job-alert emails (HTML body) into jobs with a salary verdict."""
import re
from dataclasses import dataclass
from email.utils import parseaddr
from html.parser import HTMLParser

from .salary import SalaryDecision, evaluate_salary

CAKE_SENDER = 'notifications@no-reply.cake.me'


@dataclass(frozen=True)
class CakeJob:
    section: str
    title: str
    url: str
    salary_text: str | None
    decision: SalaryDecision


def is_cake_alert(sender):
    return parseaddr(sender or '')[1].lower() == CAKE_SENDER


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.items = []
        self.section = ''
        self._in_h3 = False
        self._in_li = False
        self._li = None
        self._in_a = False
        self._salary_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'h3':
            self._in_h3 = True
            self.section = ''
        elif tag == 'li':
            self._in_li = True
            self._li = {'section': self.section, 'title': '', 'url': '', 'salary': ''}
        elif tag == 'a' and self._in_li and not self._li['url']:
            self._in_a = True
            self._li['url'] = attrs.get('href') or ''
        elif tag == 'span' and self._in_li:
            if self._salary_depth:
                self._salary_depth += 1
            elif 'job-salary' in (attrs.get('class') or ''):
                self._salary_depth = 1

    def handle_endtag(self, tag):
        if tag == 'h3':
            self._in_h3 = False
        elif tag == 'a':
            self._in_a = False
        elif tag == 'span' and self._salary_depth:
            self._salary_depth -= 1
        elif tag == 'li' and self._in_li:
            self._in_li = False
            self.items.append(self._li)
            self._li = None

    def handle_data(self, data):
        if self._in_h3:
            self.section += data
        elif self._in_li and self._in_a:
            self._li['title'] += data
        elif self._in_li and self._salary_depth:
            self._li['salary'] += data


def _clean(text):
    return re.sub(r'\s+', ' ', text).strip()


def parse_cake_alert(html):
    collector = _Collector()
    collector.feed(html or '')
    jobs = []
    for item in collector.items:
        title = _clean(item['title'])
        if not title or not item['url']:
            continue
        salary = _clean(item['salary']) or None
        jobs.append(CakeJob(_clean(item['section']), title, item['url'], salary, evaluate_salary(salary)))
    return jobs
