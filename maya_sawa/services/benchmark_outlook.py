"""The annual AI long-term outlook set from the benchmark line-up (productType=outlook, code AI).

Benchmark annual reports set the year's structural view; daily readings and holding analyses then read their
short-term data against it. The outlook is plain text with a fixed shape so readers can cite a theme by its id:

    【年度格局】2026
    一句話：...
    T1 標題
    依據：...（benchmark 年報主張）
    環節：...（benchmark 圖上的環節）
    短線印證指標：...（哪些月營收、季報、指引會印證它）
    反證：...（看到什麼就要改寫）
"""
import re

FIELDS = ("依據：", "環節：", "短線印證指標：", "反證：")
_HEADER = re.compile(r"^【年度格局】(20\d{2})\s*$", re.M)
_THEME = re.compile(r"^(T\d{1,2})\s+\S.*$", re.M)


def validate_outlook_content(content: str) -> dict:
    if not isinstance(content, str) or len(content) > 20000:
        raise ValueError("Outlook must be text up to 20000 characters")
    header = _HEADER.search(content)
    if not header:
        raise ValueError("Outlook must start with 【年度格局】YYYY")
    starts = list(_THEME.finditer(content))
    if not starts:
        raise ValueError("Outlook needs numbered themes T1, T2, ...")
    themes = []
    for index, match in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(content)
        body = content[match.end():end]
        missing = [field for field in FIELDS if not re.search(rf"^{field}\s*\S", body, re.M)]
        if missing:
            raise ValueError(f"{match[1]} is missing {', '.join(missing)}")
        themes.append(match[1])
    if len(set(themes)) != len(themes):
        raise ValueError("Theme ids must be unique")
    return {"year": int(header[1]), "themes": themes}
