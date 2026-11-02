"""Poll Gmail (read-only) for CakeResume alerts, apply the salary gate. Never sends or modifies mail."""
import base64
import json
from pathlib import Path

from .cake_parser import CAKE_SENDER, is_cake_alert, parse_cake_alert

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
QUERY = f'from:{CAKE_SENDER} newer_than:14d'
MAX_SEEN = 500


def _header(message, name):
    for h in message.get('payload', {}).get('headers', []):
        if h.get('name', '').lower() == name.lower():
            return h.get('value', '')
    return ''


def _html_body(part):
    if part.get('mimeType') == 'text/html' and part.get('body', {}).get('data'):
        return base64.urlsafe_b64decode(part['body']['data'] + '==').decode('utf-8', 'replace')
    for sub in part.get('parts', []) or []:
        found = _html_body(sub)
        if found:
            return found
    return ''


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8')).get('seen', [])
    except (OSError, ValueError):
        return []


def poll_once(gmail, state_path):
    """Return CakeJob list for messages not seen before; remember every message id examined."""
    seen = _load(state_path)
    listed = gmail.users().messages().list(userId='me', q=QUERY, maxResults=50).execute()
    jobs = []
    for ref in listed.get('messages', []) or []:
        mid = ref['id']
        if mid in seen:
            continue
        message = gmail.users().messages().get(userId='me', id=mid, format='full').execute()
        if is_cake_alert(_header(message, 'From')):
            jobs.extend(parse_cake_alert(_html_body(message.get('payload', {}))))
        seen.append(mid)
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    Path(state_path).write_text(json.dumps({'seen': seen[-MAX_SEEN:]}), encoding='utf-8')
    return jobs
