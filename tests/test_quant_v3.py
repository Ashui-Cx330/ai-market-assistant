from __future__ import annotations

from datetime import datetime, timezone

from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from backend.quant_v3 import (build_panel, dataset_audit, model_drift,
                              run_research)
from tests.test_ai_v2 import candles


def universe(count: int = 520) -> dict:
    return {"AAA": candles(count, "1D", 11), "BBB": candles(count, "1D", 12),
            "CCC": candles(count, "1D", 13), "DDD": candles(count, "1D", 14),
            "EEE": candles(count, "1D", 15)}


def test_dataset_and_temporal_audits_are_real():
    rows = universe(430)
    audit = dataset_audit(rows, "US")
    assert audit["status"] == "PASSED"
    assert audit["totals"]["candles"] == 430 * 5
    panel, contract = build_panel(rows, "US", "1d", "T+5")
    assert contract["temporal_audit"]["status"] == "PASSED"
    assert (panel["timestamp_utc"] < panel["target_time"]).all()
    assert {"alpha_target", "future_max_drawdown", "z_return_5"} <= set(panel)


def test_dataset_audit_rejects_invalid_ohlc_and_future_rows():
    rows = candles(20, "1D")
    rows[0]["high"] = rows[0]["low"] - 1
    rows[-1]["timestamp"] = "2100-01-01T00:00:00+00:00"
    audit = dataset_audit({"BAD": rows}, "US")
    assert audit["status"] == "FAILED"
    assert audit["totals"]["ohlc_invalid"] == 1
    assert audit["totals"]["future_rows"] == 1


def test_five_window_research_never_auto_promotes(monkeypatch):
    monkeypatch.setattr("backend.quant_v3._classifier_factories", lambda: ({
        "LogisticRegression": lambda: make_pipeline(StandardScaler(), LogisticRegression(
            C=.5, class_weight="balanced", max_iter=1000, random_state=42))}, {}))
    monkeypatch.setattr("backend.quant_v3._regressor_factories", lambda: ({
        "Ridge": lambda: make_pipeline(StandardScaler(), Ridge(alpha=5.0))}, {}))
    result = run_research(universe(), "US", "1d", "T+5", 5)
    assert len(result["walk_forward"]["windows"]) == 5
    assert result["temporal_leakage_audit"]["status"] == "PASSED"
    assert result["production_model"] is None
    assert not result["automatic_retraining"]
    assert result["news"]["production_probability_weight"] == 0
    assert result["model_tournament"]["risk_classification"]["windows"]


def test_model_drift_is_observational_and_never_retrains():
    now = datetime(2026, 9, 12, tzinfo=timezone.utc)
    records = []
    for index in range(220):
        age = index
        records.append({"actual": "UP", "resolved_at": (now.replace(tzinfo=None) - __import__("datetime").timedelta(days=age)).isoformat(),
                        "correct": int(age > 30), "prob_down": .1, "prob_flat": .1, "prob_up": .8})
    result = model_drift(records, now)
    assert result["time_coverage_days"] >= 219
    assert result["action"] == "DOWNGRADE_TO_EXPERIMENTAL"
    assert result["automatic_retraining"] is False
