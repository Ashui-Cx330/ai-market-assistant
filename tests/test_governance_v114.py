from backend.governance_v4 import GATES, news_feature_eligibility, production_gate


def test_future_or_unknown_news_never_enters_feature():
    assert news_feature_eligibility({},"2026-01-01T00:00:00Z")["value"] is None
    assert news_feature_eligibility({"published_at":"2026-01-02T00:00:00Z","sentiment":1},"2026-01-01T00:00:00Z")["reason"]=="FUTURE_NEWS"
    assert news_feature_eligibility({"published_at":"2025-12-31T00:00:00Z","sentiment":1},"2026-01-01T00:00:00Z")["eligible"]


def test_governance_fails_closed_and_never_auto_promotes():
    failed=production_gate({})
    assert failed["decision"]=="NO_EDGE" and failed["champion"] is None
    passed=production_gate({gate:True for gate in GATES})
    assert passed["qualified"] and passed["decision"]=="MANUAL_REVIEW_REQUIRED" and passed["champion"] is None
