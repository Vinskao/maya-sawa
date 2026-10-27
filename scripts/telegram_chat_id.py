"""Print the chat id of whoever last messaged your bot (run once, locally, after sending the bot a message).

    TELEGRAM_BOT_TOKEN=... python scripts/telegram_chat_id.py

The token is read from the environment so it never lands in shell history arguments or the repo.
"""
import os
import sys

import httpx

token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not token:
    sys.exit("Set TELEGRAM_BOT_TOKEN in the environment first.")
data = httpx.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15).json()
chats = {(m["chat"]["id"], m["chat"].get("type")) for u in data.get("result", []) if (m := u.get("message"))}
print("\n".join(f"chat id: {cid} ({kind})" for cid, kind in sorted(chats)) or "No messages yet: send your bot a message first.")
