"""Public sign-up for the daily reading by email. Double opt-in; tokens only ever travel inside the mails."""
import re
from datetime import timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_EMAIL = re.compile(r'^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$')


class SubscribeBody(BaseModel):
    email: str


def make_router(db, now, daily_limit=200, mail_enabled=lambda: True):
    router = APIRouter(prefix='/market/subscriptions', tags=['Daily reading subscriptions'])

    @router.post('')
    def subscribe(body: SubscribeBody):
        email = body.email.strip()
        if len(email) > 254 or not _EMAIL.fullmatch(email):
            raise HTTPException(422, '請輸入有效的 Email 地址')
        # Each new address costs one confirmation mail, so a flood of sign-ups is cut off for the day.
        if db.created_since(now() - timedelta(days=1)) >= daily_limit:
            raise HTTPException(429, '今天的訂閱申請已達上限，請明天再試')
        db.subscribe(email, now())
        # The same answer whether or not the address was already known. `mail_enabled` lets the form
        # stop promising a confirmation mail while SMTP is not configured.
        return {'status': 'pending', 'mail_enabled': bool(mail_enabled())}

    @router.get('/confirm')
    def confirm(token: str):
        row = db.confirm(token, now())
        if row is None:
            raise HTTPException(404, '連結無效或已過期')
        return {'status': row['status']}

    def _unsubscribe(token: str):
        row = db.unsubscribe(token)
        if row is None:
            raise HTTPException(404, '連結無效或已過期')
        return {'status': row['status']}

    router.get('/unsubscribe')(_unsubscribe)
    router.post('/unsubscribe')(_unsubscribe)  # RFC 8058 one-click from the mail client
    return router
