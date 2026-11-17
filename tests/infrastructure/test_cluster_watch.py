"""scripts/cluster_watch.py: a CronJob on the other worker that tells the owner when the cluster is stuck (2026-11-17)."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("cluster_watch", Path(__file__).parents[2] / "scripts" / "cluster_watch.py")
cw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cw)

NOW = datetime(2026, 11, 17, 5, 0, tzinfo=timezone.utc)
ago = lambda minutes: (NOW - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pod(name, age=60, phase="Running", waiting=None, deleting=None, ns="default"):
    meta = {"name": name, "namespace": ns, "creationTimestamp": ago(age)}
    if deleting is not None: meta["deletionTimestamp"] = ago(deleting)
    states = [{"state": {"waiting": {"reason": waiting}}}] if waiting else [{"state": {"running": {}}}]
    return {"metadata": meta, "status": {"phase": phase, "containerStatuses": states}}


def node(name, ready="True"):
    return {"metadata": {"name": name}, "status": {"conditions": [{"type": "Ready", "status": ready}]}}


def test_a_healthy_cluster_has_no_problems():
    assert cw.find_problems([pod("a"), pod("b", phase="Succeeded")], [], [node("n1")], NOW) == []


def test_a_container_stuck_creating_for_ten_minutes_is_a_problem_but_a_new_one_is_not():
    stuck = cw.find_problems([pod("maya-sawa-x", age=30, waiting="CreateContainerError")], [], [], NOW)
    assert len(stuck) == 1 and "maya-sawa-x" in stuck[0] and "CreateContainerError" in stuck[0]
    assert cw.find_problems([pod("fresh", age=3, waiting="ContainerCreating")], [], [], NOW) == []


def test_a_pod_stuck_terminating_and_a_pending_pod_are_problems():
    problems = cw.find_problems([pod("old", deleting=20), pod("waiting", age=25, phase="Pending")], [], [], NOW)
    assert any("old" in text and "Terminating" in text for text in problems)
    assert any("waiting" in text and "Pending" in text for text in problems)
    assert cw.find_problems([pod("leaving", deleting=2)], [], [], NOW) == []


def test_a_node_that_is_not_ready_and_recent_failed_kill_events_are_problems():
    events = [{"reason": "FailedKillPod", "lastTimestamp": ago(5), "involvedObject": {"name": "p1"}},
              {"reason": "FailedKillPod", "lastTimestamp": ago(120), "involvedObject": {"name": "p2"}}]
    problems = cw.find_problems([], events, [node("10.0.158.183", ready="Unknown")], NOW)
    assert any("10.0.158.183" in text and "NotReady" in text for text in problems)
    assert sum("FailedKillPod" in text for text in problems) == 1 and any("p1" in text for text in problems)


def test_the_first_report_is_sent_then_the_same_problem_is_quiet_until_an_hour_has_passed():
    problems = ["pod a stuck"]
    send, state = cw.decide(problems, {}, NOW)
    assert send and "pod a stuck" in send and state["signature"]
    again, state2 = cw.decide(problems, state, NOW + timedelta(minutes=10))
    assert again is None
    reminder, _ = cw.decide(problems, state2, NOW + timedelta(minutes=61))
    assert reminder and "pod a stuck" in reminder
    changed, _ = cw.decide(problems + ["pod b stuck"], state2, NOW + timedelta(minutes=11))
    assert changed and "pod b stuck" in changed


def test_a_recovery_is_reported_once_and_a_quiet_cluster_stays_quiet():
    _, state = cw.decide(["pod a stuck"], {}, NOW)
    done, cleared = cw.decide([], state, NOW + timedelta(minutes=5))
    assert done and "恢復" in done and not cleared.get("signature")
    assert cw.decide([], cleared, NOW + timedelta(minutes=10))[0] is None


def test_an_endpoint_that_fails_twice_is_a_problem():
    calls = []
    def fetch(url):
        calls.append(url); raise OSError("down")
    problems = cw.probe_endpoints({"site": "https://example.test/"}, fetch=fetch, pause=lambda s: None)
    assert problems and "site" in problems[0] and len(calls) == 2
    assert cw.probe_endpoints({"site": "https://example.test/"}, fetch=lambda url: 200, pause=lambda s: None) == []
