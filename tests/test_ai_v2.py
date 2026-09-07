from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import timedelta

from backend.ai_engine import (_PlattCalibrator, _aligned_dataset, _model_factories,
                               feature_frame)
from backend.feature_services import FeatureStore
from backend.horizons import (add_stock_trading_minutes, future_timestamp,
                              horizon_bar_count, supported_horizons, target_indices)
from backend.model_manager import ModelManager


def candles(count=420, frequency="15min", seed=7):
    rng = np.random.default_rng(seed)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, .006, count)))
    timestamps = pd.date_range("2025-01-01", periods=count, freq=frequency, tz="UTC")
    result = []
    for index, close in enumerate(closes):
        opened = closes[index - 1] if index else close
        result.append({"timestamp": timestamps[index].isoformat(), "open": opened,
                       "high": max(opened, close) * 1.002, "low": min(opened, close) * .998,
                       "close": close, "volume": float(rng.integers(100, 10000)), "amount": 0.0})
    return result


def test_horizon_5m(): assert supported_horizons("5m") == {"1H": 12, "4H": 48, "1D": 288}
def test_horizon_15m(): assert supported_horizons("15m") == {"1H": 4, "4H": 16, "1D": 96}
def test_horizon_30m(): assert supported_horizons("30m") == {"1H": 2, "4H": 8, "1D": 48}
def test_horizon_1h(): assert supported_horizons("1h") == {"1H": 1, "4H": 4, "1D": 24}


def test_stock_daily_bar_count(): assert horizon_bar_count("stock", "15m", "1D") == 16


def test_stock_trading_hours():
    # Friday 11:15 Shanghai + 60 trading minutes crosses lunch into 13:45.
    start = pd.Timestamp("2025-01-03 11:15", tz="Asia/Shanghai")
    assert add_stock_trading_minutes(start, 60).tz_convert("Asia/Shanghai").strftime("%F %R") == "2025-01-03 13:45"
    # Friday 14:45 + 60 trading minutes crosses the weekend into Monday.
    assert add_stock_trading_minutes(pd.Timestamp("2025-01-03 14:45", tz="Asia/Shanghai"), 60).tz_convert(
        "Asia/Shanghai").strftime("%F %R") == "2025-01-06 10:15"
    assert future_timestamp(pd.Timestamp("2025-01-03 06:45", tz="UTC"), "stock", "15m", "1D").tz_convert(
        "Asia/Shanghai").strftime("%F %R") == "2025-01-06 14:45"


def test_crypto_24_7():
    timestamps = pd.date_range("2025-01-01", periods=20, freq="15min", tz="UTC")
    indices = target_indices(timestamps, "crypto", "15m", "1H")
    assert np.array_equal(indices[:16], np.arange(4, 20))
    assert np.all(indices[16:] == -1)


def test_no_lookahead_bias():
    source = candles()
    frame = feature_frame(source)
    x, _, alignment = _aligned_dataset(frame, "crypto", "15m", "4H")
    assert (alignment["target_time"] > alignment["feature_time"]).all()
    # Every model input is derived at the feature timestamp; no future column is present.
    assert "future_return" not in x.columns and "target_time" not in x.columns
    changed = [dict(row) for row in source]
    for row in changed[-50:]: row["close"] *= 1.5
    original_features = frame.iloc[:300][x.columns].reset_index(drop=True)
    changed_features = feature_frame(changed).iloc[:300][x.columns].reset_index(drop=True)
    pd.testing.assert_frame_equal(original_features, changed_features)


def test_probability_calibration():
    raw = np.array([[.7, .2, .1], [.1, .8, .1], [.1, .2, .7], [.6, .3, .1], [.1, .3, .6]])
    target = pd.Series([-1, 0, 1, -1, 1])
    calibrated = _PlattCalibrator().fit(raw, target).transform(raw)
    assert calibrated.shape == raw.shape
    assert np.allclose(calibrated.sum(axis=1), 1)
    assert np.all((calibrated >= 0) & (calibrated <= 1))


def test_feature_missing_fallback():
    frame = feature_frame(candles())
    status = FeatureStore().availability(frame, "crypto")
    assert status["features"]["market"] and status["features"]["technical"]
    assert not status["features"]["news"] and status["data_status"] == "PARTIAL_DATA"


def test_model_ensemble():
    factories, unavailable = _model_factories()
    assert {"RandomForest", "XGBoost", "LightGBM"}.issubset(factories)
    assert "LSTM" in unavailable and "Transformer" in unavailable


def test_data_timestamp_alignment():
    start = pd.Timestamp("2025-02-01 12:00", tz="UTC")
    assert future_timestamp(start, "crypto", "15m", "1H") == start + timedelta(hours=1)
    assert future_timestamp(start, "crypto", "15m", "1D") == start + timedelta(days=1)


def test_walk_forward_validation():
    frame = feature_frame(candles())
    x, _, alignment = _aligned_dataset(frame, "crypto", "15m", "1H")
    split = int(len(x) * .65)
    assert alignment.iloc[:split]["target_time"].max() < alignment.iloc[-1]["feature_time"]


def test_prediction_confidence():
    status = FeatureStore().availability(feature_frame(candles()), "crypto")
    assert 0 <= status["feature_coverage"] <= 1


def test_model_manager_asset_isolation_and_rollback(tmp_path):
    manager = ModelManager(tmp_path)
    paths = {manager.path(symbol, "15m", "1H") for symbol in ("BTCUSDT", "ETHUSDT", "600519")}
    assert len(paths) == 3
    manager.save("BTCUSDT", "15m", "1H", {"fingerprint": "one"})
    manager.save("BTCUSDT", "15m", "1H", {"fingerprint": "two"})
    assert manager.rollback("BTCUSDT", "15m", "1H")
    assert manager.load("BTCUSDT", "15m", "1H", "one") == {"fingerprint": "one"}


def test_model_manager_requires_holdout_improvement(tmp_path):
    manager=ModelManager(tmp_path)
    old={"fingerprint":"old","version":"4.0","ensemble_metrics":{"accuracy":.55,"brier_score":.62}}
    manager.save("BTC","1h","1H",old)
    weaker={"fingerprint":"new","version":"4.0","ensemble_metrics":{"accuracy":.54,"brier_score":.615},"trained_at":"now"}
    selected,status=manager.promote_if_better("BTC","1h","1H",weaker)
    assert status=="RETAINED_PREVIOUS_MODEL_NO_SIGNIFICANT_IMPROVEMENT" and selected["ensemble_metrics"]["accuracy"]==.55
    assert manager.load("BTC","1h","1H","new") is not None
