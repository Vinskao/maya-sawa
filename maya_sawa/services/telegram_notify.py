"""Owner-only Telegram notifications from the scheduled routines.

The bot token and the owner's chat id live in the deployment environment (Jenkins credentials), never in a routine.
Routines call POST /market/notify with the agent key; this module formats the text and sends it to that one chat.
Sending is one-way (no webhook, no reading messages), and without both settings it does nothing.
"""
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

MAX_LENGTH = 3500  # Telegram allows 4096; leave room for the header
PREFIX = {"update": "✅ ", "attention": "⚠️ 需要處理 · "}
_SECRET = re.compile(r"\d{6,}:[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_.-]+")


def _mask(text: str) -> str:
    return _SECRET.sub("［已遮蔽］", text)


def format_message(kind: str, title: str, body: str = "") -> str:
    if kind not in PREFIX:
        raise ValueError("kind must be 'update' or 'attention'")
    text = f"{PREFIX[kind]}{title.strip()}" + (f"\n{body.strip()}" if body and body.strip() else "")
    return _mask(text)[:MAX_LENGTH]


def send(kind: str, title: str, body: str = "", client: httpx.Client | None = None) -> dict:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(), os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return {"sent": False, "reason": "not configured"}
    text = format_message(kind, title, body)
    try:
        own = client is None
        client = client or httpx.Client(timeout=10)
        try:
            response = client.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                   json={"chat_id": chat, "text": text, "disable_web_page_preview": True})
        finally:
            if own:
                client.close()
        if response.status_code != 200:
            return {"sent": False, "reason": f"telegram returned {response.status_code}"}
        return {"sent": True}
    except Exception as exc:
        logger.warning("Telegram notification failed: %s", type(exc).__name__)
        return {"sent": False, "reason": type(exc).__name__}
