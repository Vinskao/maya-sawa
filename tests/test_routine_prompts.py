"""The scheduled routines' instructions live in routines/*.md; each routine's own prompt is a short pointer to its file.

Why: on 2026-11-02 the retired host peoplesystem.tatdvsonorth.com was blocked in the routines' cloud environment while ten
prompts still named it. Updating a routine means re-sending its whole prompt (6-7 KB echoed back twice), so a host change took
ten large edits. With the instructions in the repository a change is one reviewed commit that these tests can check.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "routines").glob("*.md")) if (ROOT / "routines").is_dir() else []
EXPECTED = {
    "market-us-macro-sonnet.md", "market-us-macro-opus.md", "market-taiwan-sonnet.md", "market-taiwan-opus.md",
    "weekly-maintenance-frontend.md", "weekly-maintenance-maya-sawa.md", "weekly-maintenance-backend.md",
    "report-claim-extraction.md",
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


def test_the_usage_report_step_is_kept_where_a_routine_had_one():
    for name in ("market-us-macro-sonnet.md", "market-us-macro-opus.md", "market-taiwan-sonnet.md", "market-taiwan-opus.md",
                 "report-claim-extraction.md"):
        assert "report_routine_usage.py" in (ROOT / "routines" / name).read_text(encoding="utf-8"), name
