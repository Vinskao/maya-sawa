import base64
import json
from pathlib import Path

from maya_sawa.services.job_alerts.poller import poll_once

HTML = (Path(__file__).parents[1] / 'fixtures' / 'cake_job_alert.html').read_text(encoding='utf-8')


def _b64(text):
    return base64.urlsafe_b64encode(text.encode()).decode()


class FakeGmail:
    """Mimics the slice of googleapiclient used by the poller."""
    def __init__(self, messages):
        self.store = messages
        self.queries = []
        self.gets = []

    def users(self):
        return self

    # users().messages().list(...).execute() / .get(...).execute()
    def messages(self):
        outer = self

        class M:
            def list(self, userId, q, maxResults=50):
                outer.queries.append(q)
                return type('R', (), {'execute': lambda s: {'messages': [{'id': i} for i in outer.store]}})()

            def get(self, userId, id, format):
                outer.gets.append(id)
                m = outer.store[id]
                return type('R', (), {'execute': lambda s: m})()
        return M()


def _msg(sender, html=HTML):
    return {
        'id': 'x', 'payload': {
            'headers': [{'name': 'From', 'value': sender}, {'name': 'Subject', 'value': 'jobs'}],
            'mimeType': 'multipart/alternative',
            'parts': [{'mimeType': 'text/html', 'body': {'data': _b64(html)}}],
        },
    }


def test_poll_extracts_decisions_and_is_idempotent(tmp_path):
    gmail = FakeGmail({'m1': _msg('Cake <notifications@no-reply.cake.me>')})
    state = tmp_path / 'state.json'
    first = poll_once(gmail, state)
    assert [(j.title, j.decision.verdict.value) for j in first][2] == ('Cloud Service Staff Backend Engineer - TL', 'passed')
    assert len(first) == 5
    assert 'from:notifications@no-reply.cake.me' in gmail.queries[0]
    assert json.loads(state.read_text())['seen'] == ['m1']
    assert poll_once(gmail, state) == []          # same message never re-processed


def test_spoofed_sender_is_ignored_but_remembered(tmp_path):
    gmail = FakeGmail({'m2': _msg('notifications@no-reply.cake.me.evil.com')})
    state = tmp_path / 'state.json'
    assert poll_once(gmail, state) == []
    assert 'm2' in json.loads(state.read_text())['seen']
