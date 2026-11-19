"""Read LinkedIn job alerts from Gmail using a read-only OAuth refresh grant."""
import base64
from datetime import datetime, timezone
from email.utils import parseaddr

import httpx

from .linkedin import parse_alert
from .poller import _header

SENDER = "jobs-noreply@linkedin.com"
QUERY = f"from:{SENDER} newer_than:30d -in:spam -in:trash"
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"


def text_parts(part):
    for child in part.get("parts", []):
        yield from text_parts(child)
    media = part.get("mimeType")
    data = part.get("body", {}).get("data")
    if data and media in {"text/plain", "text/html"}:
        yield media, base64.urlsafe_b64decode(data + "==").decode("utf-8", "replace")


def checked_json(response):
    response.raise_for_status()
    return response.json()


def collect(queue, credentials):
    with httpx.Client(timeout=25) as client:
        token = checked_json(client.post("https://oauth2.googleapis.com/token", data={
            **credentials, "grant_type": "refresh_token",
        }))["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        params = {"q": QUERY, "maxResults": "50"}
        while True:
            page = checked_json(client.get(f"{GMAIL}/messages", params=params, headers=headers))
            for ref in page.get("messages", []):
                mail_id = ref["id"]
                if queue.seen(mail_id):
                    continue
                mail = checked_json(client.get(f"{GMAIL}/messages/{mail_id}", headers=headers, params={"format": "full"}))
                if parseaddr(_header(mail, "From"))[1].lower() != SENDER:
                    continue
                entries = {}
                for media, body in sorted(text_parts(mail["payload"]), key=lambda part: part[0]):
                    entries.update((job["id"], job) for job in parse_alert(body, html=media == "text/html"))
                received = datetime.fromtimestamp(int(mail["internalDate"]) / 1000, timezone.utc).isoformat()
                queue.ingest(mail_id, list(entries.values()), received)
            if not page.get("nextPageToken"):
                return
            params["pageToken"] = page["nextPageToken"]
