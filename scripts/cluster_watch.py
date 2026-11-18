#!/usr/bin/env python3
"""Tell the owner on Telegram when the cluster is stuck (2026-11-17). Runs as a CronJob on the OTHER worker (10.0.159.167),
so a stuck 10.0.158.183 (where maya-sawa lives) cannot silence it. Standard library only: it runs in python:3.12-alpine.

Problems it reports: a pod stuck creating, pending or terminating for 10+ minutes, a node that is not Ready, FailedKillPod
events in the last 15 minutes (the container runtime hanging), and the maya-sawa health check / the public site failing for
10+ minutes (a deploy restarts maya-sawa for a few minutes, which is not reported).
One message when the set of problems changes, a reminder each hour, one message when everything is fine again.
"""
import hashlib
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

STUCK_MINUTES = 10
EVENT_MINUTES = 15
PROBE_GRACE_MINUTES = 10   # a deploy restarts maya-sawa (Recreate) and the health check fails for a few minutes: not an outage
REMIND_MINUTES = 60
BAD_WAITING = {"CreateContainerError", "CreateContainerConfigError", "ContainerCreating", "ImagePullBackOff", "ErrImagePull",
               "CrashLoopBackOff", "RunContainerError", "InvalidImageName"}
ENDPOINTS = {"maya-sawa 健康檢查": "http://maya-sawa/healthz", "tymultiverse.cc 首頁": "https://tymultiverse.cc/"}
STATE_MAP = "cluster-watch-state"


def _time(text: str | None) -> datetime | None:
    if not text: return None
    try: return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError: return None


def find_problems(pods: list[dict], events: list[dict], nodes: list[dict], now: datetime) -> list[str]:
    problems: list[str] = []
    for item in nodes:
        ready = next((c for c in item["status"].get("conditions", []) if c.get("type") == "Ready"), None)
        if not ready or ready.get("status") != "True":
            problems.append(f"節點 {item['metadata']['name']} NotReady")
    for item in pods:
        meta, status = item["metadata"], item.get("status", {})
        name = f"{meta.get('namespace', 'default')}/{meta['name']}"
        age = lambda ts: (now - ts).total_seconds() / 60 if ts else 0
        if status.get("phase") in ("Succeeded", "Failed"): continue
        if meta.get("deletionTimestamp"):
            if age(_time(meta["deletionTimestamp"])) >= STUCK_MINUTES: problems.append(f"pod {name} 卡在 Terminating")
            continue
        if age(_time(meta.get("creationTimestamp"))) < STUCK_MINUTES: continue
        waiting = [c["state"]["waiting"].get("reason") for c in status.get("containerStatuses", []) if c.get("state", {}).get("waiting")]
        bad = [reason for reason in waiting if reason in BAD_WAITING]
        if bad: problems.append(f"pod {name} 卡在 {bad[0]}")
        elif status.get("phase") == "Pending": problems.append(f"pod {name} 一直 Pending")
    stale = [e for e in events if e.get("reason") == "FailedKillPod" and (_time(e.get("lastTimestamp") or e.get("eventTime")) or now - timedelta(days=1)) >= now - timedelta(minutes=EVENT_MINUTES)]
    if stale:
        names = ", ".join(sorted({e.get("involvedObject", {}).get("name", "?") for e in stale})[:3])
        problems.append(f"容器執行環境可能卡住：近 {EVENT_MINUTES} 分鐘有 {len(stale)} 筆 FailedKillPod（{names}）")
    return problems


def probe_endpoints(endpoints: dict[str, str], fetch=None, pause=time.sleep) -> dict[str, str]:
    """{label: message} for every endpoint that failed twice in a row right now."""
    fetch = fetch or (lambda url: urllib.request.urlopen(url, timeout=10).status)
    failing = {}
    for label, url in endpoints.items():
        for attempt in range(2):
            try:
                if fetch(url) < 500: break
            except urllib.error.HTTPError as error:
                if error.code < 500: break
            except Exception:
                pass
            if attempt == 0: pause(5)
        else:
            failing[label] = f"{label} 連兩次失敗（{url}）"
    return failing


def settle_probes(failing: dict[str, str], first_seen: dict[str, str], now: datetime) -> tuple[list[str], dict[str, str]]:
    """Report an endpoint only after it has been failing for PROBE_GRACE_MINUTES; an answer resets its clock."""
    kept, reported = {}, []
    for label, message in failing.items():
        started = _time(first_seen.get(label)) or now
        kept[label] = started.isoformat()
        if now - started >= timedelta(minutes=PROBE_GRACE_MINUTES): reported.append(message)
    return reported, kept


def decide(problems: list[str], state: dict, now: datetime) -> tuple[str | None, dict]:
    """(message to send or None, new state). Quiet while nothing changed; a reminder each hour; one message on recovery."""
    signature = hashlib.sha256("\n".join(sorted(problems)).encode()).hexdigest()[:16] if problems else ""
    body = "\n".join(f"• {text}" for text in problems)
    last = _time(state.get("lastSent"))
    if not problems:
        if state.get("signature"): return "叢集已恢復正常，剛才回報的問題都消失了。", {"signature": "", "lastSent": now.isoformat()}
        return None, {"signature": "", "lastSent": state.get("lastSent", "")}
    due = not last or (now - last) >= timedelta(minutes=REMIND_MINUTES)
    if signature != state.get("signature") or due:
        return f"偵測到叢集異常：\n{body}\n（上次出事是節點容器環境卡住，可能要從 OCI 主控台重開節點，見 skill oke-node-recovery）", {"signature": signature, "lastSent": now.isoformat()}
    return None, state


# --- in-cluster glue (not unit tested: needs the API server) ---
SA = "/var/run/secrets/kubernetes.io/serviceaccount"


def _api(path: str, method: str = "GET", body: dict | None = None):
    request = urllib.request.Request(f"https://{os.environ['KUBERNETES_SERVICE_HOST']}:{os.environ.get('KUBERNETES_SERVICE_PORT', '443')}{path}",
                                     method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Bearer " + open(f"{SA}/token").read().strip(), "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20, context=ssl.create_default_context(cafile=f"{SA}/ca.crt")) as response:
        return json.load(response)


def _load_state() -> dict:
    try: return _api(f"/api/v1/namespaces/default/configmaps/{STATE_MAP}").get("data", {})
    except urllib.error.HTTPError: return {}


def _save_state(state: dict) -> None:
    body = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": STATE_MAP}, "data": state}
    try: _api(f"/api/v1/namespaces/default/configmaps/{STATE_MAP}", "PUT", body)
    except urllib.error.HTTPError: _api("/api/v1/namespaces/default/configmaps", "POST", body)


def _telegram(text: str) -> None:
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("telegram not configured; message was:", text)
        return
    data = json.dumps({"chat_id": chat, "text": "⚠️ " + text}).encode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data, headers={"Content-Type": "application/json"}), timeout=15)


def main() -> int:
    now = datetime.now(timezone.utc)
    problems = find_problems(_api("/api/v1/pods")["items"], _api("/api/v1/events?fieldSelector=reason%3DFailedKillPod")["items"], _api("/api/v1/nodes")["items"], now)
    saved = _load_state()
    try: first_seen = json.loads(saved.get("probeFirst") or "{}")
    except ValueError: first_seen = {}
    waited, first_seen = settle_probes(probe_endpoints(ENDPOINTS), first_seen, now)
    problems += waited
    message, state = decide(problems, saved, now)
    state["probeFirst"] = json.dumps(first_seen)
    if message:
        try: _telegram(message)
        except Exception as error:   # keep the state unsaved so the next run tries again
            print("telegram failed:", type(error).__name__)
            return 1
    _save_state(state)
    print("problems:", problems or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
