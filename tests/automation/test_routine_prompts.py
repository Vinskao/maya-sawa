"""The scheduled routines' instructions live in routines/*.md; each routine's own prompt is a short pointer to its file.

Why: on 2026-11-02 the retired host peoplesystem.tatdvsonorth.com was blocked in the routines' cloud environment while ten
prompts still named it. Updating a routine means re-sending its whole prompt (6-7 KB echoed back twice), so a host change took
ten large edits. With the instructions in the repository a change is one reviewed commit that these tests can check.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = sorted((ROOT / "routines").glob("*.md")) if (ROOT / "routines").is_dir() else []
EXPECTED = {
    "market-us-macro-sonnet.md", "market-us-macro-opus.md", "market-taiwan-sonnet.md", "market-taiwan-opus.md",
    "weekly-maintenance-frontend.md", "weekly-maintenance-maya-sawa.md", "weekly-maintenance-backend.md",
    "report-claim-extraction.md", "maya-daily-fallback.md", "maya-daily-review.md",
}


def test_every_migrated_routine_has_its_instruction_file():
    assert {path.name for path in FILES} == EXPECTED


def test_no_instruction_file_names_the_retired_host_except_to_say_it_is_retired():
    """The one allowed mention is a sentence telling the routine not to use it."""
    for path in FILES:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "peoplesystem" in line:
                assert "已棄用" in line and "https://peoplesystem" not in line, f"{path.name}:{number}: {line[:120]}"


def test_api_calls_go_to_the_current_site():
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        assert "https://tymultiverse.cc/maya-sawa/" in text, path.name
        assert not re.search(r"https?://[^\s\"')]*tatdvsonorth", text), path.name


def test_instruction_files_hold_no_secret_and_never_ask_the_routine_to_set_one():
    secret_like = re.compile(r"(?i)(x-market-agent-key\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{20,}|bearer\s+[A-Za-z0-9_\-]{20,}|sk-[A-Za-z0-9]{20,})")
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        assert not secret_like.search(text), path.name
        assert "-H \"X-Market-Agent-Key" not in text and "-H 'X-Market-Agent-Key" not in text, path.name


def test_the_files_that_write_say_the_proxy_adds_the_key_for_the_current_host():
    for name in ("market-us-macro-sonnet.md", "market-us-macro-opus.md", "market-taiwan-sonnet.md", "market-taiwan-opus.md",
                 "report-claim-extraction.md"):
        text = (ROOT / "routines" / name).read_text(encoding="utf-8")
        assert "tymultiverse.cc/maya-sawa/" in text and ("network secret" in text or "代理" in text), name


def test_market_analysis_routines_check_the_opening_200_characters_before_every_save():
    """2026-11-03: the opening 200 characters become the Threads post, so they lead with the new evidence, not price action."""
    for name in ("market-us-macro-sonnet.md", "market-us-macro-opus.md", "market-taiwan-sonnet.md", "market-taiwan-opus.md"):
        text = (ROOT / "routines" / name).read_text(encoding="utf-8")
        assert "check_analysis_lead.py" in text and "前 200 字" in text, name
        script_at, put_at = text.index("check_analysis_lead.py"), text.index("curl -sS -X PUT")
        assert text.index("前 200 字") < put_at or script_at < put_at + 2000, name
    assert (ROOT / "maya_sawa" / "public_scripts" / "check_analysis_lead.py").is_file()


def test_the_usage_report_step_is_kept_where_a_routine_had_one():
    for name in ("market-us-macro-sonnet.md", "market-us-macro-opus.md", "market-taiwan-sonnet.md", "market-taiwan-opus.md",
                 "report-claim-extraction.md"):
        assert "report_routine_usage.py" in (ROOT / "routines" / name).read_text(encoding="utf-8"), name


def test_daily_fallback_routine_skips_when_today_is_already_approved_and_self_reviews_before_approving():
    text = (ROOT / "routines" / "maya-daily-fallback.md").read_text(encoding="utf-8")
    assert text.index("已有 day == D 的已核准稿") < text.index("POST /market/daily-maya/proposals")
    assert "備援自審" in text and "嚴格審稿" in text and "不得核准" in text
    assert "PushNotification" in text and "/market/audio" in text


def test_daily_reading_routines_ask_for_a_reader_version_beside_the_speech_script():
    """2026-11-11: the speech script is one glued block on a page, so every draft also carries a laid-out reading version."""
    for name in ("maya-daily-review.md", "maya-daily-fallback.md"):
        text = (ROOT / "routines" / name).read_text(encoding="utf-8")
        assert "reading" in text and "閱讀版" in text and "## 小標" in text, name
    fallback = (ROOT / "routines" / "maya-daily-fallback.md").read_text(encoding="utf-8")
    assert '"reading":' in fallback
    draft = (ROOT / "docs" / "GPT_DAILY_DRAFT_PROMPT.md").read_text(encoding="utf-8")
    assert '"reading"' in draft and "閱讀版" in draft and '"title"' in draft


def test_market_routines_create_a_missing_research_map_and_cover_overseas_holdings():
    """2026-11-11: 6834-JP had an AI analysis but no research map: no routine was told to create a missing one,
    the Taiwan routine declared Japan and Korea out of scope, and the US routine was forbidden to write maps."""
    for name in ("market-taiwan-sonnet.md", "market-taiwan-opus.md"):
        text = (ROOT / "routines" / name).read_text(encoding="utf-8")
        assert "日本、韓國、美國標的與總經評論不在本例程範圍" not in text, name
        assert "6857-JP" in text and "000660-KR" in text, name
        assert "沒有研究圖" in text and "research-guide.md" in text, name
    for name in ("market-us-macro-sonnet.md", "market-us-macro-opus.md"):
        text = (ROOT / "routines" / name).read_text(encoding="utf-8")
        assert "排程不能寫" not in text, name
        assert "沒有研究圖" in text and "research-guide.md" in text, name


def test_benchmark_outlook_is_written_by_opus_and_read_by_every_analysis_and_daily_reading():
    """2026-11-11: the benchmark sets the year's AI long-term outlook; short-term analyses read their data against it."""
    writer = (ROOT / "routines" / "market-us-macro-opus.md").read_text(encoding="utf-8")
    assert "年度 AI 長線格局" in writer and "productType=outlook" in writer and "benchmark/versions" in writer
    assert "check_outlook" in writer or "【年度格局】" in writer
    for name in ("market-us-macro-sonnet.md", "market-taiwan-sonnet.md", "market-taiwan-opus.md"):
        assert "不得寫入年度格局" in (ROOT / "routines" / name).read_text(encoding="utf-8"), name
    readers = ["market-us-macro-sonnet.md", "market-us-macro-opus.md", "market-taiwan-sonnet.md", "market-taiwan-opus.md",
               "maya-daily-review.md", "maya-daily-fallback.md"]
    for name in readers:
        text = (ROOT / "routines" / name).read_text(encoding="utf-8")
        assert "analysis/AI?productType=outlook" in text and "長線格局對照" in text, name
    for name in ("maya-daily-review.md", "maya-daily-fallback.md"):
        assert "outlook:AI:" in (ROOT / "routines" / name).read_text(encoding="utf-8"), name
    draft = (ROOT / "docs" / "GPT_DAILY_DRAFT_PROMPT.md").read_text(encoding="utf-8")
    assert "productType=outlook" in draft and "outlook:AI:" in draft
