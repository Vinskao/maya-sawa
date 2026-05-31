"""Parser for pasted git log --stat output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from ..config.config import Config


HASH_RE = re.compile(r"^HASH:\s*([0-9a-fA-F]{40})\s*$", re.MULTILINE)
DATE_RE = re.compile(r"^DATE:\s*(.+?)\s*$", re.MULTILINE)
MSG_RE = re.compile(r"^MSG:\s*(.*)$", re.MULTILINE)
REPO_RE = re.compile(r"^REPO:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
STAT_LINE_RE = re.compile(r"^\s*(\d+)\s+files?\s+changed(?:,\s*(\d+)\s+insertions?\(\+\))?(?:,\s*(\d+)\s+deletions?\(-\))?", re.MULTILINE)
RENAME_ONLY_RE = re.compile(r"rename .+\(100%\)", re.IGNORECASE)


@dataclass
class ParsedCommit:
    commit_hash: str
    git_url: str
    commit_time: datetime
    commit_message: str
    changed_files_summary: str
    is_trivial: bool = False


def _truncate(value: str, max_chars: int) -> str:
    value = value.strip()
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 15)].rstrip() + "\n... (truncated)"


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _first_match(pattern: re.Pattern[str], text: str) -> Optional[str]:
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def _changed_line_count(summary: str) -> Optional[int]:
    match = STAT_LINE_RE.search(summary)
    if not match:
        return None
    insertions = int(match.group(2) or 0)
    deletions = int(match.group(3) or 0)
    return insertions + deletions


def is_trivial(parsed: ParsedCommit) -> bool:
    summary = parsed.changed_files_summary
    message = parsed.commit_message.lower()
    changed_lines = _changed_line_count(summary)

    if RENAME_ONLY_RE.search(summary) and (changed_lines is None or changed_lines == 0):
        return True

    keyword_hit = any(keyword in message for keyword in Config.GIT_COMMIT_TRIVIAL_KEYWORDS)
    if keyword_hit and (changed_lines is None or changed_lines < Config.GIT_COMMIT_TRIVIAL_MIN_LINES):
        return True

    if changed_lines is not None and changed_lines < Config.GIT_COMMIT_TRIVIAL_MIN_LINES:
        return True

    return False


def parse_paste(text: str) -> List[ParsedCommit]:
    git_url = _first_match(REPO_RE, text) or ""
    chunks = [chunk.strip() for chunk in text.split("===COMMIT===") if chunk.strip()]
    commits: List[ParsedCommit] = []

    for chunk in chunks:
        commit_hash = _first_match(HASH_RE, chunk)
        date_value = _first_match(DATE_RE, chunk)
        msg_match = MSG_RE.search(chunk)
        files_marker = chunk.find("---FILES---")
        if not commit_hash or not date_value or not msg_match or files_marker == -1:
            continue

        message_start = msg_match.start(1)
        message_end = files_marker
        commit_message = chunk[message_start:message_end].strip()
        commit_message = re.sub(r"^MSG:\s*", "", commit_message, count=1).strip()
        files_summary = _truncate(chunk[files_marker + len("---FILES---") :], Config.GIT_COMMIT_SUMMARY_MAX_CHARS)

        parsed = ParsedCommit(
            commit_hash=commit_hash.lower(),
            git_url=git_url,
            commit_time=_parse_datetime(date_value),
            commit_message=commit_message,
            changed_files_summary=files_summary,
        )
        parsed.is_trivial = is_trivial(parsed)
        commits.append(parsed)

    return commits
