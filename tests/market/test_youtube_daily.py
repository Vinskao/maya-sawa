"""2026-11-16: approved daily readings go from the database's audio to YouTube, once each, with only the newest MP4 kept."""
import json
import shutil
import subprocess
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import create_engine

from maya_sawa.databases.youtube_db import YoutubeDatabase
from maya_sawa.services import youtube_daily as yd


def row(day, title="標題", status="approved", **extra):
    return {"id": f"id-{day}", "day": day, "title": title, "status": status, "content": "朗讀稿。", "reading": "## 小節\n\n閱讀版內容",
            "sources": ["https://example.com/a", "stock:2330:2"], **extra}


class Audio:
    def __init__(self, ready):
        self.ready = ready

    def audio(self, product_type, code, revision):
        return (b"MP3:" + code.encode(), "audio/mpeg") if code in self.ready else None


class Client:
    def __init__(self):
        self.calls = []

    def upload(self, mp4, meta, privacy):
        self.calls.append((mp4, meta["title"], privacy))
        return f"vid{len(self.calls)}"


@pytest.fixture
def db():
    return YoutubeDatabase(create_engine("sqlite://"))


def daily(db, ready, client=None, **kw):
    return yd.YoutubeDaily(db, Audio(ready), client or Client(), builder=lambda mp3: b"MP4(" + mp3 + b")", **kw)


ROWS = [row("2026-11-14"), row("2026-11-15"), row("2026-11-16"), row("2026-11-13")]
ALL = {r["id"] for r in ROWS}


def test_configured_only_with_all_credentials_and_the_switch():
    env = {"YOUTUBE_CLIENT_ID": "a", "YOUTUBE_CLIENT_SECRET": "b", "YOUTUBE_REFRESH_TOKEN": "c"}
    assert not yd.configured(env) and not yd.configured({**env, "YOUTUBE_UPLOAD_ENABLED": "false"})
    assert yd.configured({**env, "YOUTUBE_UPLOAD_ENABLED": "true"}) and not yd.configured({"YOUTUBE_UPLOAD_ENABLED": "true"})


def test_privacy_defaults_to_private_and_a_typo_never_publishes():
    assert yd.privacy({}) == "private" and yd.privacy({"YOUTUBE_PRIVACY": "Public"}) == "public" and yd.privacy({"YOUTUBE_PRIVACY": "pubic"}) == "private"


def test_metadata_title_description_and_site_link():
    meta = yd.metadata(row("2026-11-16", title="折現率壓力"))
    assert meta["title"] == "11/16｜折現率壓力" and "閱讀版內容" in meta["description"]
    assert "https://tymultiverse.cc/work/daily-reading-2026-11-16" in meta["description"] and "https://example.com/a" in meta["description"]
    assert "stock:2330" not in meta["description"] and "不構成投資建議" in meta["description"]
    assert len(yd.metadata(row("2026-11-16", title="長" * 300))["title"]) == 100


def test_first_run_uploads_only_the_newest_three_oldest_first_and_records_each(db):
    client = Client()
    job = daily(db, ALL, client)
    out = [job.process_one(ROWS) for _ in range(4)]
    assert out == [("2026-11-14", "vid1"), ("2026-11-15", "vid2"), ("2026-11-16", "vid3"), None]
    assert db.uploaded() == {"2026-11-14": "vid1", "2026-11-15": "vid2", "2026-11-16": "vid3"} and len(client.calls) == 3


def test_a_day_is_never_uploaded_twice_across_restarts(db):
    daily(db, ALL).process_one(ROWS)
    again = daily(db, ALL)
    assert [again.process_one(ROWS) for _ in range(3)][-1] is None and len(db.uploaded()) == 3


def test_only_the_latest_episodes_mp4_is_kept_in_the_database(db):
    job = daily(db, ALL)
    for _ in range(3):
        job.process_one(ROWS)
    assert db.latest() == ("2026-11-16", b"MP4(MP3:id-2026-11-16)")


def test_audio_not_ready_yet_is_retried_later_and_unapproved_days_are_ignored(db):
    rows = ROWS + [row("2026-11-17", status="pending")]
    job = daily(db, {"id-2026-11-14"})
    assert job.process_one(rows) == ("2026-11-14", "vid1")      # only this one has narration yet
    assert job.process_one(rows) is None                          # the others wait for their audio
    assert set(db.uploaded()) == {"2026-11-14"}                   # and the pending (unapproved) day never uploads


def test_mp4_build_uses_ffmpeg_and_fails_loudly_when_it_does_not_produce_a_video():
    fake = lambda cmd, **kw: SimpleNamespace(returncode=1)
    with pytest.raises(RuntimeError):
        yd.build_mp4(b"x", run=fake)
    assert yd.ffmpeg_command("a.mp3", "c.png", "o.mp4")[:2] == ["ffmpeg", "-y"] and "libx264" in yd.ffmpeg_command("a", "c", "o")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_real_ffmpeg_turns_audio_and_the_cover_into_an_h264_aac_mp4(tmp_path):
    mp3 = tmp_path / "t.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(mp3)], capture_output=True, check=True)
    mp4 = yd.build_mp4(mp3.read_bytes())
    (tmp_path / "o.mp4").write_bytes(mp4)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height", "-of", "json", str(tmp_path / "o.mp4")],
                           capture_output=True, text=True).stdout
    codecs = {s["codec_name"] for s in json.loads(probe)["streams"]}
    assert {"h264", "aac"} <= codecs


def test_client_refreshes_the_token_then_uploads_with_the_resumable_protocol():
    seen = []

    def handler(request: httpx.Request):
        seen.append((request.method, str(request.url).split("?")[0], request.headers.get("authorization")))
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "tok"})
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False}
            return httpx.Response(200, headers={"Location": "https://upload.example/session1"})
        return httpx.Response(200, json={"id": "abc123"})
    client = yd.YouTubeClient("id", "secret", "refresh", http=httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.upload(b"mp4bytes", {"title": "t", "description": "d"}, "private") == "abc123"
    assert [s[0] for s in seen] == ["POST", "POST", "PUT"] and seen[1][2] == "Bearer tok"
