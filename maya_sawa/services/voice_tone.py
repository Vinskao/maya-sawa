"""Tone of the daily narration, decided by what the market did on the last trading day (docs/MARKET_AUDIO.md, 2026-11-16).

Pure rule, no AI: the TAIEX fell 2% or more -> angry, rose 2% or more -> cheerful, anything else -> normal. Azure speaking styles
(`mstts:express-as`) are only applied to episodes synthesized from now on; episodes already stored are never redone.
"""
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)
TAIPEI = ZoneInfo("Asia/Taipei")
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
THRESHOLD = 2.0  # percent, the last completed trading day's change of the TAIEX
STYLE_DEGREE = "1.5"  # Azure: 0.01-2, default 1; a voice that does not support it simply ignores it
STYLES = ("angry", "cheerful")  # both are in the style lists Azure returns for zh-CN-XiaoyiNeural and zh-CN-Xiaoqi:DragonHDFlashLatestNeural


def tone_for_change(pct: float | None) -> str:
    if pct is None:
        return "normal"
    if pct <= -THRESHOLD:
        return "angry"
    if pct >= THRESHOLD:
        return "cheerful"
    return "normal"


def last_session_change(closes: list, today: date) -> float | None:
    """Percent change of the latest completed day against the day before it. `closes` is [(date, close)], today's unfinished bar excluded."""
    rows = sorted((d, float(c)) for d, c in closes if d < today and c)
    if len(rows) < 2 or rows[-2][1] <= 0:
        return None
    return round((rows[-1][1] / rows[-2][1] - 1) * 100, 2)


def fetch_taiex_closes() -> list:
    with httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT}) as client:
        response = client.get(CHART_URL, params={"range": "1mo", "interval": "1d"})
        response.raise_for_status()
        result = response.json()["chart"]["result"][0]
    return [(datetime.fromtimestamp(t, TAIPEI).date(), c) for t, c in zip(result["timestamp"], result["indicators"]["quote"][0]["close"]) if c]


def current_tone(today: date | None = None, fetch=fetch_taiex_closes) -> tuple[str, float | None]:
    """(tone, last session's change). Any failure means a normal voice: a missing quote must never stop the episode."""
    today = today or datetime.now(TAIPEI).date()
    try:
        pct = last_session_change(fetch(), today)
    except Exception:
        logger.warning("TAIEX change unavailable for the narration tone; using the normal voice", exc_info=True)
        return "normal", None
    return tone_for_change(pct), pct
