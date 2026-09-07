from __future__ import annotations

import numpy as np
import pandas as pd

from backend.ai_engine import _metrics
from backend.strategy_engine import (CausalSwingDetector, SIGNAL_KEYS,
                                     StrategyEngine, detect_fvgs,
                                     detect_structure, extended_indicators,
                                     strategy_backtest, walk_forward_strategy,
                                     ml_ict_incremental_experiment)


def candles(count=260, scale=1.0):
    # Deterministic test fixture; production signals never consume this data.
    time = pd.date_range("2025-01-01", periods=count, freq="15min", tz="UTC")
    values = 100 + np.arange(count) * .025 + np.sin(np.arange(count) / 6) * 2
    rows = []
    for index, close in enumerate(values * scale):
        opened = (values[index - 1] if index else values[index]) * scale
        rows.append({"timestamp": time[index].isoformat(), "open": opened,
                     "high": max(opened, close) + .35 * scale,
                     "low": min(opened, close) - .35 * scale, "close": close,
                     "volume": 1000 + (index % 17) * 31, "amount": 0.0})
    return rows


def test_technical_strategy_registry_and_unavailable_external_data():
    result = StrategyEngine().analyze(candles(), "15m", "deterministic OHLCV fixture")
    assert len(SIGNAL_KEYS) == 30
    assert len(result["signals"]) == 30
    assert result["unavailable"]["order_flow"] == "ORDER_FLOW_DATA_UNAVAILABLE"
    assert result["unavailable"]["options"] == "OPTIONS_DATA_UNAVAILABLE"
    assert result["strategy_count"] == 30


def test_causal_swings_have_delayed_availability_and_structure_respects_it():
    frame = extended_indicators(candles())
    swings = CausalSwingDetector(left=3, right=3).detect(frame)
    assert swings and all(s["available_index"] == s["pivot_index"] + 3 for s in swings)
    structure = detect_structure(frame, swings)
    by_id = {s["swing_id"]: s for s in swings}
    assert all(by_id[event["swing_id"]]["available_index"] < event["break_index"] for event in structure["events"])


def test_fvg_is_three_candle_and_not_available_early():
    rows = candles(80)
    rows[40].update({"open": 100, "close": 100.5, "low": 99.8, "high": 100.7})
    rows[41].update({"open": 101, "close": 102, "low": 100.9, "high": 102.2})
    rows[42].update({"open": 102, "close": 102.5, "low": 101.2, "high": 102.7})
    prefix = extended_indicators(rows[:42])
    assert not any(gap["creation_index"] == 42 for gap in detect_fvgs(prefix))
    frame = extended_indicators(rows[:43]); gap = next(g for g in detect_fvgs(frame) if g["creation_index"] == 42)
    assert gap["direction"] == "BULLISH" and gap["bottom"] == 100.7 and gap["top"] == 101.2
    assert gap["creation_time"] == gap["available_at"]


def test_fibonacci_extensions_project_in_trend_direction():
    result = StrategyEngine().analyze(candles(), "15m")
    fib = result["fibonacci"]
    assert fib["status"] == "AVAILABLE"
    if fib["direction"] == "UP":
        assert fib["levels"]["1.618"] > fib["swing_high"]["price"]
    else:
        assert fib["levels"]["1.618"] < fib["swing_low"]["price"]


def test_risk_levels_scale_with_market_and_are_not_fixed_percentages():
    normal = StrategyEngine().analyze(candles(scale=1), "15m")
    scaled = StrategyEngine().analyze(candles(scale=10), "15m")
    distance_a = abs(normal["risk_plan"]["entry"] - normal["risk_plan"]["stop_loss"])
    distance_b = abs(scaled["risk_plan"]["entry"] - scaled["risk_plan"]["stop_loss"])
    assert 9.5 < distance_b / distance_a < 10.5
    assert normal["risk_plan"]["stop_sources"]["atr_buffer"] > 0
    assert normal["risk_plan"]["historical_samples"] > 100


def test_backtest_executes_next_open_and_walk_forward_is_embargoed():
    rows = candles(225)
    result = strategy_backtest(rows, "trend", "15m", horizon_bars=8)
    assert result["mock_count"] == 0 and result["random_signal_count"] == 0
    assert all(t["execution_index"] == t["signal_index"] + 1 for t in result["trades"])
    walk = walk_forward_strategy(rows, "trend", "15m", folds=2)
    assert walk["purged"] and walk["embargo"]
    assert all(fold["embargo_bars"] == 8 for fold in walk["folds"])


def test_probability_metrics_report_ece_and_reliability():
    y = np.asarray([-1, 0, 1, 1, 0, -1])
    probabilities = np.asarray([[.8, .1, .1], [.1, .8, .1], [.1, .1, .8],
                                [.2, .1, .7], [.1, .7, .2], [.7, .2, .1]])
    metrics = _metrics(y, probabilities)
    assert 0 <= metrics["ece"] <= 1
    assert metrics["reliability"] and sum(x["samples"] for x in metrics["reliability"]) == len(y)


def test_causal_ml_features_do_not_change_when_future_changes():
    from backend.ai_engine import feature_frame
    rows = candles(260); original = feature_frame(rows)
    changed = [dict(item) for item in rows]
    for item in changed[210:]:
        item["open"] *= 1.4; item["close"] *= 1.4; item["high"] *= 1.4; item["low"] *= 1.4
    modified = feature_frame(changed)
    columns = ["causal_bos", "fvg_imbalance", "fib_0618_distance"]
    pd.testing.assert_frame_equal(original.loc[:209, columns], modified.loc[:209, columns])


def test_multi_timeframe_conflict_reduces_confidence():
    up = candles(240)
    down = [dict(item) for item in reversed(candles(240))]
    for index, item in enumerate(down): item["timestamp"] = up[index]["timestamp"]
    result = StrategyEngine().analyze_multi_timeframe({"4h": up, "15m": down})
    assert result["confidence_factor"] <= 1
    assert set(result["matrix"]) == {"4h", "15m"}


def test_ml_ict_ablation_uses_purged_untouched_test():
    result = ml_ict_incremental_experiment(candles(520), "15m", "crypto", "4H")
    assert result["status"] in {"PASS", "INCREMENTAL_VALUE_NOT_TRADEABLE", "NO_INCREMENTAL_VALUE"}
    assert result["slices"]["embargo_rows"] == 16
    assert result["before"]["test_samples"] == result["after"]["test_samples"]
