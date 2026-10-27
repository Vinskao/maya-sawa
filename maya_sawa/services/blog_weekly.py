"""Least-privilege writer for one technical article per ISO week; never grants admin CRUD."""
import hashlib
import hmac
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import Header, HTTPException


def weekly_slug(now=None):
    local = (now or datetime.now(ZoneInfo('Asia/Taipei'))).astimezone(ZoneInfo('Asia/Taipei'))
    year, week, _ = local.isocalendar()
    return f'weekly-tech-{year}-w{week:02d}'


def require_weekly_agent(x_blog_agent_key: str | None = Header(default=None)):
    expected = os.getenv('BLOG_WEEKLY_AGENT_KEY_SHA256', '')
    if not expected:
        raise HTTPException(503, 'Weekly article writer is not configured')
    if not x_blog_agent_key:
        raise HTTPException(401, 'Weekly article key required')
    actual = hashlib.sha256(x_blog_agent_key.encode()).hexdigest()
    if not hmac.compare_digest(actual, expected):
        raise HTTPException(403, 'Invalid weekly article key')
    return {'sub': 'agent:weekly-tech'}
