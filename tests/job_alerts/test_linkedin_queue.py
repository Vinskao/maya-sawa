import base64

import httpx
from sqlalchemy import create_engine

from maya_sawa.services.job_alerts import linkedin_gmail
from maya_sawa.services.job_alerts.linkedin import JobQueue, parse_alert


def test_linkedin_alert_and_duplicate_import():
    body = """
    <a href="https://www.linkedin.com/comm/jobs/view/4491491158/?trk=email">Java Cloud Engineer / Tech Lead</a>
    <a href="https://linkedin.com.evil.example/jobs/view/123">Ignore</a>
    <a href="https://www.linkedin.com/jobs/view/4491491158/">Repeat</a>
    """
    jobs = parse_alert(body)
    assert jobs == [{"id": "4491491158", "title": "Java Cloud Engineer / Tech Lead"}]
    queue = JobQueue(create_engine("sqlite://"))
    queue.ingest("mail1", jobs)
    assert queue.transition("4491491158", "pending", "approved")
    queue.ingest("mail2", jobs)
    assert queue.list()[0]["status"] == "approved"


def test_only_approved_jobs_can_be_claimed_once_and_ats_identity_is_unique():
    queue = JobQueue(create_engine("sqlite://"))
    queue.ingest("mail1", [{"id": "1", "title": "One"}, {"id": "2", "title": "Two"}])
    assert queue.claim() is None
    for job_id in ("1", "2"):
        assert queue.transition(job_id, "pending", "approved")
    first = queue.claim()["id"]
    second = queue.claim()["id"]
    assert queue.claim() is None
    assert queue.transition(first, "claimed", "submitting", identity="example.com:job-1")
    assert not queue.transition(second, "claimed", "submitting", identity="example.com:job-1")
    assert not queue.transition(first, "approved", "claimed")
    assert queue.transition(first, "submitting", "submitted", note="receipt")
def test_gmail_collector_paginates_and_prefers_plain_job_details(monkeypatch):
    text = """-----
Java Cloud Engineer / Tech Lead
HiTRUST
Taipei
Apply with resume & profile
View job: https://www.linkedin.com/comm/jobs/view/4491491158/?trk=email
-----
"""
    data = base64.urlsafe_b64encode(text.encode()).decode()
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "fixture"})
        if request.url.path.endswith("/messages"):
            if "pageToken" in request.url.params:
                return httpx.Response(200, json={"messages": [{"id": "mail1"}]})
            return httpx.Response(200, json={"nextPageToken": "next"})
        return httpx.Response(200, json={"internalDate": "1795064978000", "payload": {
            "headers": [{"name": "From", "value": "LinkedIn <jobs-noreply@linkedin.com>"}],
            "mimeType": "text/plain", "body": {"data": data},
        }})

    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(linkedin_gmail.httpx, "Client", lambda **_: client)
    queue = JobQueue(create_engine("sqlite://"))
    linkedin_gmail.collect(queue, {"refresh_token": "fixture"})
    assert len(requests) == 4
    assert queue.seen("mail1")
    assert queue.list()[0]["company"] == "HiTRUST"
    assert queue.list()[0]["id"] == "4491491158"
