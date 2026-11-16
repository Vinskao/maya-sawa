"""Daily reading audio -> MP4 -> YouTube (docs/YOUTUBE_DAILY.md).

The approved reading's narration already sits in the database (`maya_sawa_market_audio`, product `daily`). For each approved day
that is not on YouTube yet, newest first and only the latest few: read the MP3 from the database, turn it into an MP4 with the
show cover (ffmpeg), upload it through the YouTube Data API, record the video id so it is never uploaded twice, and keep only the
newest episode's MP4 in the database. No AI is involved; the title and description come from the approved text.

Needs an OAuth refresh token for the channel (the one thing only the channel owner can grant) in YOUTUBE_CLIENT_ID,
YOUTUBE_CLIENT_SECRET and YOUTUBE_REFRESH_TOKEN; without them the service stays off.
"""
import logging
import os
import subprocess
import tempfile
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)
COVER = Path(__file__).resolve().parent.parent / "assets" / "youtube_cover.png"
TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
SITE = "https://tymultiverse.cc"
BACKFILL = 3  # on the first run only the newest three episodes are uploaded
PRIVACIES = ("private", "unlisted", "public")
CATEGORY_EDUCATION = "27"


def configured(env=os.environ) -> bool:
    return all(env.get(name) for name in ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")) \
        and env.get("YOUTUBE_UPLOAD_ENABLED", "false").lower() == "true"


def privacy(env=os.environ) -> str:
    value = (env.get("YOUTUBE_PRIVACY") or "private").lower()
    return value if value in PRIVACIES else "private"  # a typo must never publish an episode


def metadata(row: dict) -> dict:
    """Title and description for one approved daily reading, built only from its own text and sources."""
    day = row["day"]
    title = (row.get("title") or f"每日市場精讀｜{day.replace('-', '/')}").strip()
    title = f"{day[5:].replace('-', '/')}｜{title}" if not title[:1].isdigit() else title
    reading = (row.get("reading") or row.get("content") or "").strip()
    summary = " ".join(reading.replace("#", " ").split())[:300]
    sources = [s for s in row.get("sources") or [] if s.startswith("http")][:8]
    lines = [summary, "", f"文字版：{SITE}/work/daily-reading-{day}"]
    if sources:
        lines += ["", "資料來源："] + sources
    lines += ["", "以上為市場資訊整理，不構成投資建議。"]
    description = "\n".join(lines).replace("<", "").replace(">", "")
    return {"title": title[:100], "description": description[:4900], "day": day}


def ffmpeg_command(audio: str, cover: str, out: str) -> list[str]:
    return ["ffmpeg", "-y", "-loop", "1", "-framerate", "2", "-i", cover, "-i", audio, "-c:v", "libx264", "-tune", "stillimage",
            "-preset", "veryfast", "-pix_fmt", "yuv420p", "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2",
            "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart", out]


def build_mp4(mp3: bytes, cover: Path = COVER, run=subprocess.run) -> bytes:
    with tempfile.TemporaryDirectory() as folder:
        audio, out = Path(folder, "audio.mp3"), Path(folder, "episode.mp4")
        audio.write_bytes(mp3)
        result = run(ffmpeg_command(str(audio), str(cover), str(out)), capture_output=True, timeout=900)
        if result.returncode != 0 or not out.exists() or out.stat().st_size == 0:
            raise RuntimeError("ffmpeg could not build the episode video")
        return out.read_bytes()


class YouTubeClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, http=None):
        self._creds = {"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token}
        self._http = http or httpx.Client(timeout=httpx.Timeout(600, connect=20))

    def _access_token(self) -> str:
        response = self._http.post(TOKEN_URL, data={**self._creds, "grant_type": "refresh_token"})
        response.raise_for_status()
        return response.json()["access_token"]

    def upload(self, mp4: bytes, meta: dict, privacy_status: str) -> str:
        """Resumable upload; returns the new video id."""
        token = self._access_token()
        body = {"snippet": {"title": meta["title"], "description": meta["description"], "categoryId": CATEGORY_EDUCATION,
                            "defaultLanguage": "zh-TW", "defaultAudioLanguage": "zh-TW"},
                "status": {"privacyStatus": privacy_status, "selfDeclaredMadeForKids": False}}
        start = self._http.post(UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"}, json=body,
                                headers={"Authorization": f"Bearer {token}", "X-Upload-Content-Type": "video/mp4",
                                         "X-Upload-Content-Length": str(len(mp4))})
        start.raise_for_status()
        done = self._http.put(start.headers["Location"], content=mp4, headers={"Content-Type": "video/mp4"})
        done.raise_for_status()
        return done.json()["id"]


class YoutubeDaily:
    """One step of the daily job: upload the newest approved episode that is not on YouTube yet."""

    def __init__(self, youtube_db, audio_db, client, privacy_status="private", builder=build_mp4, backfill=BACKFILL):
        self.db, self.audio, self.client, self.privacy = youtube_db, audio_db, client, privacy_status
        self.builder, self.backfill = builder, backfill

    def pending(self, rows: list[dict]) -> list[dict]:
        done = self.db.uploaded()
        newest = sorted((r for r in rows if r.get("status", "approved") == "approved"), key=lambda r: r["day"], reverse=True)
        return [r for r in newest[: self.backfill] if r["day"] not in done]

    def process_one(self, rows: list[dict]):
        """Returns (day, video_id) for what it uploaded, or None when nothing was ready."""
        for row in reversed(self.pending(rows)):  # oldest of the newest few first, so the latest ends up last
            audio = self.audio.audio("daily", row["id"], 1)
            if not audio:
                continue  # narration not generated yet; try again on the next pass
            meta = metadata(row)
            mp4 = self.builder(audio[0])
            video_id = self.client.upload(mp4, meta, self.privacy)
            self.db.record(row["day"], video_id, self.privacy, meta["title"])  # recorded at once: never uploaded twice
            latest_day = max(r["day"] for r in rows)
            if row["day"] == latest_day:
                self.db.save_latest(row["day"], mp4)
            return row["day"], video_id
        return None
