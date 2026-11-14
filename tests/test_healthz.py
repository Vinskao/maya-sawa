"""2026-11-14: kubelet probes on /paprika/articles (DB, 1 s timeout) killed the pod under load."""
from pathlib import Path

from fastapi.testclient import TestClient

from maya_sawa.main import app


def test_healthz_answers_without_database():
    assert TestClient(app).get("/healthz").json() == {"status": "ok"}


def test_probes_use_healthz():
    manifest = Path("k8s/deployment.yaml").read_text(encoding="utf-8")
    probes = manifest.split("startupProbe")[1].split("volumes")[0]
    assert probes.count("path: /healthz") == 3 and "timeoutSeconds: 5" in probes
