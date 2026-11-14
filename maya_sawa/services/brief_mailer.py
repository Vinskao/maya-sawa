"""Sends the approved daily reading to confirmed subscribers, and the confirmation link to new ones.

Mail is off until SMTP is configured (BRIEF_MAIL_SMTP_HOST / _USERNAME / _PASSWORD / BRIEF_MAIL_FROM);
sign-ups are still stored, and their confirmation mail goes out once it is.
"""
import json
import logging
import os
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path

from .daily_maya_reading import reading_blocks

logger = logging.getLogger(__name__)

DISCLAIMER = '內容由 AI 整理，僅供參考，不構成投資建議。'
SUBSCRIPTION_PATH = '/api/market/subscriptions'
MAX_PER_RUN = 100  # a stuck provider or a huge list must not hold the loop; the rest go out on the next run


def connect_links():
    """The Connect links repeated in every mail; same list as the site footer."""
    path = Path(__file__).resolve().parents[2] / 'config' / 'connect-links.json'
    return json.loads(path.read_text(encoding='utf-8'))


def _message(to, subject, body, sender):
    message = EmailMessage()
    message['From'], message['To'], message['Subject'] = sender, to, subject
    message.set_content(body)
    return message


def confirmation_message(email, token, *, sender, site):
    link = f'{site}{SUBSCRIPTION_PATH}/confirm?token={token}'
    return _message(email, '請確認訂閱 Birch Investments 每日市場精讀', '\n'.join([
        '你（或有人用這個地址）在 tymultiverse.cc 訂閱了每日市場精讀。',
        '', '點這個連結確認，之後每天會收到當日精讀的文字稿：', link,
        '', '如果不是你本人，不用理會這封信，我們不會再寄信給你。',
    ]), sender)


def daily_message(brief, email, token, *, sender, site, links):
    unsubscribe = f'{site}{SUBSCRIPTION_PATH}/unsubscribe?token={token}'
    title = (brief.get('title') or '').strip() or '每日市場精讀'
    reading = (brief.get('reading') or '').strip()
    body = '\n\n'.join(text for _, text in reading_blocks(reading)) if reading else brief['content'].strip()
    message = _message(email, f"{title}｜{brief['day']} 每日市場精讀", '\n'.join([
        title, brief['day'], '', body, '',
        '收聽與追蹤', f'網站與語音：{site}/learn/',
        *[f"{link['label']}：{link['href']}" for link in links], '',
        DISCLAIMER, f'取消訂閱：{unsubscribe}',
    ]), sender)
    message['List-Unsubscribe'] = f'<{unsubscribe}>'
    message['List-Unsubscribe-Post'] = 'List-Unsubscribe=One-Click'
    return message


def smtp_configured():
    return all(os.getenv(name) for name in ('BRIEF_MAIL_SMTP_HOST', 'BRIEF_MAIL_SMTP_USERNAME', 'BRIEF_MAIL_SMTP_PASSWORD', 'BRIEF_MAIL_FROM'))


def smtp_send(message):
    with smtplib.SMTP(os.environ['BRIEF_MAIL_SMTP_HOST'], int(os.getenv('BRIEF_MAIL_SMTP_PORT', '587')), timeout=30) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(os.environ['BRIEF_MAIL_SMTP_USERNAME'], os.environ['BRIEF_MAIL_SMTP_PASSWORD'])
        smtp.send_message(message)


class BriefMailer:
    def __init__(self, db, *, send=smtp_send, configured=smtp_configured, sender=None, site=None, links=None, now=None):
        self.db, self.send, self.configured = db, send, configured
        self.sender = sender or os.getenv('BRIEF_MAIL_FROM', '')
        self.site = (site or os.getenv('PUBLIC_SITE_URL', 'https://tymultiverse.cc')).rstrip('/')
        self.links = connect_links() if links is None else links
        self.now = now or (lambda: datetime.now(timezone.utc))

    def run_once(self, brief):
        """brief: today's approved reading, or None. Logs counts only, never addresses."""
        if not self.configured():
            return {'confirmations': 0, 'daily': 0}
        budget = MAX_PER_RUN
        confirmations = daily = 0
        for row in self.db.awaiting_confirmation_mail(limit=budget):
            if not self.db.claim_confirmation_mail(row['id'], self.now()):
                continue
            try:
                self.send(confirmation_message(row['email'], row['token'], sender=self.sender, site=self.site))
                confirmations += 1
            except Exception as exc:
                self.db.release_confirmation_mail(row['id'])
                logger.warning('Brief confirmation mail failed error_type=%s', type(exc).__name__)
            budget -= 1
        if brief:
            for row in self.db.confirmed():
                if budget <= 0:
                    break
                claimed, previous = self.db.claim_daily(row['id'], brief['day'])
                if not claimed:
                    continue
                try:
                    self.send(daily_message(brief, row['email'], row['token'], sender=self.sender, site=self.site, links=self.links))
                    daily += 1
                except Exception as exc:
                    self.db.release_daily(row['id'], brief['day'], previous)
                    logger.warning('Brief daily mail failed day=%s error_type=%s', brief['day'], type(exc).__name__)
                budget -= 1
        if confirmations or daily:
            logger.info('Brief mail sent confirmations=%s daily=%s', confirmations, daily)
        return {'confirmations': confirmations, 'daily': daily}
