import json

from backend import database
from backend.market_intelligence import (build_snapshot_from_prediction,
                                         intelligence_view, track_record)
from backend.news_intelligence import EventExtractionEngine, SOURCE_REGISTRY
from backend.main import app


def _prediction():
    return {"engine_version":"5.0","data_time":"2026-09-12T02:00:00+00:00","predicted_at":"2026-09-12T02:00:01+00:00",
      "predictions":{"1D":{"prediction":"UP","trend":"偏多","probabilities":{"down":.2,"flat":.25,"up":.55},"confidence_score":68,
        "walk_forward_samples":80,"sample_count":600,"model_advantage":.02,"probability_type":"calibrated_model_probability",
        "future_timestamp":"2026-09-13T02:00:00+00:00","validation_scheme":{"leakage_check":True},
        "top_factors":[{"feature":"rsi","label":"RSI","importance":.17,"direction":"positive"}]}},
      "decision_center":{"technical_strategy":{"market_regime":{"primary":"Bull"},"confluence":{"score":61},
        "risk_plan":{"entry":100,"stop_loss":95,"take_profits":[]}}}}


def test_event_contract_separates_sentiment_impact_and_probability():
    item={"id":"x","title":"NVDA earnings beat expectations","summary":"revenue growth","url":"https://example.test/x",
          "provider":"CNBCMarketsProvider","source":"CNBC","market":"美股","published_at":"2026-09-12T01:00:00+00:00","collected_at":"2026-09-12T01:01:00+00:00","symbols":[]}
    result=EventExtractionEngine().analyze(item,"NVDA","NVIDIA")
    assert result["event"]["event_type"] == "Earnings"
    assert result["fingerprint"] and result["freshness"]["label"] in {"Breaking","Recent","Aging","Old"}
    assert set(result["impact"]["components"]) == {"source_reliability","event_severity","asset_relevance","novelty","market_sensitivity","historical_similarity","market_regime"}
    assert "probability" not in result["impact"] and "probability" not in result["sentiment"]
    assert any(x["provider"]=="CNBCMarketsProvider" for x in SOURCE_REGISTRY)


def test_immutable_snapshot_and_truthful_model_boundary(tmp_path,monkeypatch):
    monkeypatch.setenv("TRADING_AI_DATA_DIR",str(tmp_path));database.init_db()
    first=build_snapshot_from_prediction("NVDA","stock",_prediction(),"unit_test")
    view=intelligence_view("NVDA","stock")
    assert first["snapshot_id"] and view["immutable_snapshot_count"] == 1
    assert view["periods"][0]["horizon"] == "T+1"
    assert view["periods"][0]["up"] == 55.0
    assert view["news_context"]["included_in_probability"] is False
    assert view["information_cutoff_enforced"] is True
    assert view["track_record"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert track_record("NVDA","stock")["event_breakdown_status"] == "NOT_AVAILABLE"


def test_snapshot_store_is_append_only(tmp_path,monkeypatch):
    monkeypatch.setenv("TRADING_AI_DATA_DIR",str(tmp_path));database.init_db()
    a=build_snapshot_from_prediction("BTC","crypto",_prediction(),"news_event")
    b=build_snapshot_from_prediction("BTC","crypto",_prediction(),"manual")
    assert a["snapshot_id"] != b["snapshot_id"]
    assert intelligence_view("BTC","crypto")["immutable_snapshot_count"] == 2


def test_api_routes_do_not_shadow_background_job_status():
    paths={route.path for route in app.routes}
    assert "/api/market-intelligence/{asset_type}/{symbol}" in paths
    assert "/api/intelligence-jobs/{job_id}" in paths
    assert "/api/intelligence-track-record" in paths
