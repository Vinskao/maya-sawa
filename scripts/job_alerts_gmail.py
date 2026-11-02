"""Gmail job-alert CLI (read-only).

  poetry run python scripts/job_alerts_gmail.py auth   # one-time browser consent
  poetry run python scripts/job_alerts_gmail.py poll   # list new Cake alerts + salary verdicts

Secrets live in ~/.maya-sawa/gmail/ (client_secret.json, token.json); never in the repo.
"""
import sys
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from maya_sawa.services.job_alerts.poller import SCOPES, poll_once

HOME = Path.home() / '.maya-sawa' / 'gmail'
SECRET, TOKEN, STATE = HOME / 'client_secret.json', HOME / 'token.json', HOME / 'state.json'


def credentials(interactive):
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif interactive:
        creds = InstalledAppFlow.from_client_secrets_file(str(SECRET), SCOPES).run_local_server(port=0)
    else:
        sys.exit('No valid token: run `auth` first.')
    TOKEN.write_text(creds.to_json(), encoding='utf-8')
    return creds


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ''
    if cmd == 'auth':
        credentials(interactive=True)
        print('Authorized (gmail.readonly). Token saved outside the repo.')
    elif cmd == 'poll':
        gmail = build('gmail', 'v1', credentials=credentials(False), cache_discovery=False)
        for job in poll_once(gmail, STATE):
            d = job.decision
            print(f'[{d.verdict.value:12}] {job.title} | {job.salary_text or "n/a"} | {d.reason}')
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv)
