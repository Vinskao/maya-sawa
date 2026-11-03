"""Check the first 200 characters of an AI analysis before saving it (stdlib only; a routine runs it on its save body).

The opening 200 characters are taken on their own (Threads accepts 200), so they must say which new report, earnings
figure or macro number changed or kept the rating. They must not open with the data-cutoff header or with price action
(price, moving averages, RSI, volume, support/resistance, flows): those are timing and belong after the opening.

    python3 check_analysis_lead.py body.json [--kind stock|macro]

body.json is the save body {"model", "content", "expectedRevision"}. Prints OK (exit 0) or NG with each problem (exit 1);
exit 2 when the file cannot be read. See docs/ANALYSIS_LEAD.md.
"""
import json
import re
import sys

LIMIT = 200
RATINGS = ("買", "中立", "賣")
# What counts as new evidence: a report, a company result, or a macro figure.
EVIDENCE = ("報告", "財報", "季報", "營收", "毛利", "營業利益", "獲利", "EPS", "指引", "訂單", "資本支出", "出貨", "產能", "良率", "法說",
            "公告", "新聞稿", "10-Q", "10-K", "8-K", "決算", "月營收", "CPI", "PCE", "PPI", "PMI", "GDP", "利率", "通膨", "失業",
            "非農", "FOMC", "殖利率", "總經", "公布")
# The decision: kept or changed, and from what to what.
STANCE = ("維持", "改變", "上調", "下調", "升級", "降級", "由", "→", "改為", "轉為", "調升", "調降")
# Stock-price and technical action. Product prices ("DRAM 合約價上漲") and records ("營收創新高") are evidence, so they are not listed.
PRICE = (r"股價", r"收盤", r"均線", r"\bMA\s?\d+", r"\bRSI\b", r"成交量", r"量能", r"支撐", r"壓力位", r"K\s?線", r"跌破", r"站上",
         r"回測", r"回檔", r"籌碼", r"買賣超", r"融資", r"借券", r"單日\s?[-+−]?\d", r"\d\s?日\s?[-+−]\d")
HEADER = ("資料截點", "研究期間", "敘事主軸", "單位：")


def opening(content: str) -> str:
    return (content or "")[:LIMIT]


def check_lead(content: str, kind: str = "stock") -> list[str]:
    """Problems with the opening 200 characters (empty list = fine). kind 'macro' skips the rating-line rule."""
    head = opening(content)
    problems: list[str] = []
    lines = [line for line in head.splitlines() if line.strip()]
    if kind == "stock":
        first = lines[0] if lines else ""
        match = re.match(r"【結論】\s*(買|中立|賣)", first)
        if not match:
            problems.append("第一行必須是【結論】買／【結論】中立／【結論】賣之一")
        # The insight is the paragraph right after the rating line (or the rest of that line); a data-cutoff header
        # after it is fine, a header or price action in its place is not.
        body = lines[1] if len(lines) > 1 else (first[match.end():] if match else first)
        stance_text = "\n".join(lines[:2])
    else:  # macro commentary has no rating line: its first 200 characters are the insight
        body = head
        stance_text = head
    headers = [word for word in HEADER if word in body]
    if headers:
        problems.append(f"前 200 字不可放資料截點等標題（出現：{'、'.join(headers)}），標題行移到重點之後")
    prices = []
    for pattern in PRICE:
        found = re.search(pattern, body)
        if found:
            prices.append(found.group(0).strip())
    if prices:
        problems.append(f"前 200 字不可先講股價與技術面（出現：{'、'.join(prices)}），這些是進場時機，放到第二段之後")
    if not any(word in body for word in EVIDENCE):
        problems.append("前 200 字要寫出新證據：哪一份報告、財報或總經數字（缺少報告／財報／總經用語）")
    if not re.search(r"\d", body):
        problems.append("前 200 字的證據要附數字（含期間或日期）")
    if not any(word in stance_text for word in STANCE):
        problems.append("前 200 字要寫明這個證據讓建議「維持」或「改變」（含由舊結論到新結論）")
    return problems


def _read_content(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        raw = handle.read()
    try:
        data = json.loads(raw)
        return data.get("content", "") if isinstance(data, dict) else raw
    except ValueError:
        return raw


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):  # Chinese output must survive a legacy console code page (Windows)
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    kind = "stock"
    paths = []
    args = iter(argv)
    for arg in args:
        if arg == "--kind":
            kind = next(args, "stock")
        else:
            paths.append(arg)
    if not paths:
        print("usage: check_analysis_lead.py body.json [--kind stock|macro]")
        return 2
    try:
        content = _read_content(paths[0])
    except OSError as error:
        print(f"cannot read {paths[0]}: {type(error).__name__}")
        return 2
    problems = check_lead(content, kind)
    if not problems:
        print(f"OK: 前 {LIMIT} 字有新證據、數字與建議；開頭是：{opening(content)[:60]!r}…")
        return 0
    print("NG: 前 200 字需要重寫")
    for problem in problems:
        print(f"- {problem}")
    print(f"目前前 {LIMIT} 字：{opening(content)!r}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
