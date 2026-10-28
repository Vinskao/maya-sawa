"""Report this Claude Code session's token use to the dashboard (stdlib only; run by a scheduled routine as its last step).

The cloud session keeps a transcript (~/.claude/projects/*/<session>.jsonl) with usage on every assistant message. This sums
it per model and POSTs the totals; the network proxy adds the agent key, so no secret is read or printed here.
It never fails the routine: any problem is printed and the exit code stays 0.

    python3 report_routine_usage.py "萃取主張"
"""
import glob
import json
import os
import sys
import urllib.request

URL = os.environ.get("ROUTINE_USAGE_URL", "https://peoplesystem.tatdvsonorth.com/maya-sawa/market/routine-usage")
ROOTS = [os.path.expanduser("~/.claude/projects")]
FIELDS = (("input_tokens", "input"), ("output_tokens", "output"),
          ("cache_creation_input_tokens", "cacheCreation"), ("cache_read_input_tokens", "cacheRead"))


def summarize(lines) -> dict:
    """Per-model totals. A streamed message appears several times with growing usage, so each message id counts once (its last line)."""
    last = {}
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        message = row.get("message") if isinstance(row, dict) else None
        if not isinstance(message, dict) or row.get("type") != "assistant" or not isinstance(message.get("usage"), dict):
            continue
        last[message.get("id") or row.get("uuid")] = (message.get("model") or "unknown", message["usage"])
    totals = {}
    for model, usage in last.values():
        if model.startswith("<"):  # <synthetic>: Claude Code's own placeholder messages, not model calls
            continue
        bucket = totals.setdefault(model, {"input": 0, "output": 0, "cacheCreation": 0, "cacheRead": 0, "calls": 0})
        for source, key in FIELDS:
            bucket[key] += int(usage.get(source) or 0)
        bucket["calls"] += 1
    return totals


def latest_transcript(roots):
    files = [path for root in roots for path in glob.glob(os.path.join(root, "*", "*.jsonl"))]
    return None if not files else __import__("pathlib").Path(max(files, key=os.path.getmtime))


def build_payload(path, label: str) -> dict:
    with open(path, encoding="utf-8", errors="replace") as handle:
        totals = summarize(handle)
    return {"sessionId": path.stem, "label": label[:100],
            "models": [{"model": model, **{key: value for key, value in bucket.items() if key != "calls"}} for model, bucket in totals.items()]}


def post(body: dict) -> int:
    request = urllib.request.Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status


def main(argv) -> int:
    label = argv[0] if argv else "routine"
    path = latest_transcript(ROOTS)
    if path is None:
        print("usage not reported: no transcript found")
        return 0
    body = build_payload(path, label)
    if not body["models"]:
        print("usage not reported: transcript has no usage")
        return 0
    try:
        status = post(body)
        tokens = sum(sum(item[key] for key in ("input", "output", "cacheCreation", "cacheRead")) for item in body["models"])
        print(f"usage reported: HTTP {status}, {len(body['models'])} model(s), {tokens} tokens")
    except Exception as error:  # a routine must not fail because the dashboard could not be told
        print(f"usage not reported: {type(error).__name__}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
