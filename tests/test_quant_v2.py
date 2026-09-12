from __future__ import annotations

from backend.quant_v2 import ablation, benchmark, feature_catalog
from backend.ai_engine import feature_frame, _asset_profile
from backend.horizons import supported_horizons
from tests.test_ai_v2 import candles


def test_feature_catalog_is_versioned_and_point_in_time():
    result=feature_catalog(candles(420),"test OHLCV")
    assert result["feature_count"] >= 50
    assert {"price","technical","volume","structure","regime"} == set(result["groups"])
    assert all({"name","value","timestamp","source","lookback","version"} <= set(row) for row in result["features"])
    assert result["information_cutoff"] == result["timestamp"]


def test_future_mutation_does_not_change_past_v2_features():
    original=candles(420);changed=[dict(x) for x in original]
    for row in changed[-40:]:row["close"]*=1.7;row["high"]*=1.7;row["low"]*=1.7
    a=feature_frame(original).iloc[:300];b=feature_frame(changed).iloc[:300]
    assert a.equals(b)


def test_market_profiles_and_crypto_7d():
    frame=feature_frame(candles())
    assert _asset_profile("stock","600519.SH",frame)["name"] == "CN_EQUITY"
    assert _asset_profile("stock","NVDA",frame)["name"] == "US_EQUITY"
    assert supported_horizons("1d")["7D"] == 7


def test_benchmark_and_ablation_are_chronological():
    rows=candles(520,"1D")
    result=benchmark(rows,"stock","NVDA","1d","1D",2)
    assert result["validation"]["leakage_check"] and not result["validation"]["random_split"]
    assert result["production_model"] is None
    assert "MajorityBaseline" in result["models"] and "BuyAndHold" in result["models"]
    assert "NewsOnly" in result["unavailable_models"]
    study=ablation(rows,"stock","NVDA")
    assert study["news"].startswith("NOT_TESTED") and len(study["results"]) == 4
