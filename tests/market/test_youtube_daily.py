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

    def voice(self, product_type, code, revision):
        return "duo:uiobbeci:maya-pending" if code.endswith("15") else "maya"


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
    return yd.YoutubeDaily(db, Audio(ready), client or Client(), builder=lambda mp3, voice="": b"MP4(" + mp3 + b"," + voice.encode() + b")", **kw)


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
    assert {d: v[0] for d, v in db.uploaded().items()} == {"2026-11-14": "vid1", "2026-11-15": "vid2", "2026-11-16": "vid3"} and len(client.calls) == 3


def test_a_day_is_never_uploaded_twice_across_restarts(db):
    daily(db, ALL).process_one(ROWS)
    again = daily(db, ALL)
    assert [again.process_one(ROWS) for _ in range(3)][-1] is None and len(db.uploaded()) == 3


def test_only_the_latest_episodes_mp4_is_kept_in_the_database(db):
    job = daily(db, ALL)
    for _ in range(3):
        job.process_one(ROWS)
    assert db.latest() == ("2026-11-16", b"MP4(MP3:id-2026-11-16,maya)")


def test_audio_not_ready_yet_is_retried_later_and_unapproved_days_are_ignored(db):
    rows = ROWS + [row("2026-11-17", status="pending")]
    job = daily(db, {"id-2026-11-14"})
    assert job.process_one(rows) == ("2026-11-14", "vid1")      # only this one has narration yet
    assert job.process_one(rows) is None                          # the others wait for their audio
    assert set(db.uploaded()) == {"2026-11-14"}                   # and the pending (unapproved) day never uploads


def test_clip_order_and_names_follow_the_learn_page_player():
    assert [yd.clip_order(i) for i in range(10)] == [0, 1, 2, 0, 3, 4, 0, 5, 6, 0]
    assert [yd.clip_name("maya", i) for i in range(4)] == ["reporter.mp4", "reporter2.mp4", "reporter3.mp4", "reporter.mp4"]
    assert yd.clip_name("duo:uiobbeci:maya-pending", 3) == "reporterDuoUiobbeci.mp4"
    assert yd.fallback_clip("duo") == "reporterDuo.mp4" and yd.fallback_clip("maya") == "reporter.mp4"


def test_only_the_public_presenter_clips_are_ever_requested():
    names = {yd.clip_name(v, i) for v in ("maya", "duo:x") for i in range(60)}
    assert all(n.startswith("reporter") and "prison" not in n for n in names)


def test_an_episode_uploaded_with_an_older_video_version_is_uploaded_again(db):
    db.record("2026-11-16", "old", "private", "t", version="cover")
    job = daily(db, ALL)
    assert job.process_one(ROWS)[0] == "2026-11-14"           # the cover-era upload of 11/16 is redone too, in order
    assert [job.process_one(ROWS) for _ in range(3)][1][0] == "2026-11-16"
    assert db.uploaded()["2026-11-16"][1] == yd.VIDEO_VERSION


def test_mp4_build_fails_loudly_when_ffmpeg_does_not_produce_a_video():
    fake = lambda cmd, **kw: SimpleNamespace(returncode=1, stdout="3")
    with pytest.raises(RuntimeError):
        yd.build_mp4(b"x", "maya", fetch=lambda name: b"clip", run=fake)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")
def test_real_ffmpeg_plays_the_presenter_clips_in_order_under_the_audio(tmp_path):
    mp3 = tmp_path / "t.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=5", str(mp3)], capture_output=True, check=True)
    asked = []

    def clip(name):
        asked.append(name)
        out = tmp_path / f"{name}"
        subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=640x480:d=2:r=15", "-pix_fmt", "yuv420p", str(out)], capture_output=True, check=True)
        return out.read_bytes()
    mp4 = yd.build_mp4(mp3.read_bytes(), "maya", fetch=clip)
    assert asked == ["reporter.mp4", "reporter2.mp4", "reporter3.mp4"]      # 3 x 2 s covers the 5 s narration, in the site's order
    (tmp_path / "o.mp4").write_bytes(mp4)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,width,height", "-of", "json", str(tmp_path / "o.mp4")],
                           capture_output=True, text=True).stdout
    streams = json.loads(probe)["streams"]
    assert {s["codec_name"] for s in streams} >= {"h264", "aac"} and any(s.get("width") == 1280 and s.get("height") == 720 for s in streams)


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
