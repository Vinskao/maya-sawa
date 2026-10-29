"""Taiwan event automation must deploy even when no US trigger credential exists."""
import re
from pathlib import Path


def test_optional_market_trigger_credentials_are_not_bound_as_one_required_pair():
    pipeline = (Path(__file__).resolve().parents[1] / "Jenkinsfile").read_text(encoding="utf-8")
    optional = {"MARKET_ROUTINE_TAIWAN_TOKEN", "MARKET_ROUTINE_US_TOKEN"}
    assert all(name in pipeline for name in optional)
    bindings = re.findall(r"withCredentials\(\[(.*?)\]\)", pipeline, flags=re.S)
    assert bindings
    for binding in bindings:
        requested = set(re.findall(r"credentialsId:\s*'([^']+)'", binding))
        assert not optional <= requested, "A missing US token must not disable Taiwan event updates"
