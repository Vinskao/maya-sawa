"""GPT proposals must be backed by public report claims, not just plausible tickers."""
from datetime import datetime, timezone
import pytest
from maya_sawa.services.weekly_opportunities import validate_proposals, week_key

NOW = datetime(2026, 11, 2, tzinfo=timezone.utc)
CLAIMS = [{"report_id": "r1", "codes": ["3711"], "published_at": "2026-10-28"},
          {"report_id": "r2", "codes": ["3711"], "published_at": "2026-10-29"}]
PROPOSAL = {"code": "3711", "reportIds": ["r1", "r2"], "reason": "Advanced packaging capacity supports earnings growth",
            "risk": "Demand may weaken", "macroReason": "Rates affect capital spending", "macroSourceIds": ["US_FED"]}

def validate(items, held=(), claims=CLAIMS):
    return validate_proposals(items, claims, set(held), {"US_FED"}, NOW)

def test_accepts_evidence_and_combines_macro_and_risk_in_public_reason():
    result = validate([PROPOSAL])
    assert result[0]["code"] == "3711"
    assert result[0]["conviction"] == "normal"
    assert "Demand may weaken" in result[0]["reason"]
    assert "Rates affect" in result[0]["reason"]

@pytest.mark.parametrize("change", [
    {"code": "2330"}, {"code": "6857-JP"}, {"reportIds": ["invented"]},
    {"reportIds": ["r1", "r1"]}, {"macroSourceIds": ["invented"]}, {"risk": ""}, {"macroReason": ""},
])
def test_rejects_unverified_or_incomplete_proposals(change):
    with pytest.raises(ValueError):
        validate([{**PROPOSAL, **change}])

def test_excludes_holdings_stale_reports_duplicates_and_too_many():
    for items, held, claims in [([PROPOSAL], {"3711"}, CLAIMS), ([PROPOSAL, PROPOSAL], set(), CLAIMS),
        ([PROPOSAL], set(), [{**c, "published_at": "2025-01-01"} for c in CLAIMS]),
        ([PROPOSAL]*4, set(), CLAIMS)]:
        with pytest.raises(ValueError):
            validate(items, held, claims)

def test_empty_pool_is_valid_and_week_uses_taipei_not_utc():
    assert validate([]) == []
    assert week_key(datetime(2026, 11, 1, 17, tzinfo=timezone.utc)) == "2026-W45"
