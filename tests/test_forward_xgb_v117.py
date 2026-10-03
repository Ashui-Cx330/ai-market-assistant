from __future__ import annotations

import numpy as np
import pandas as pd

from backend.ai_engine import _asset_profile, _model_factories, predict


def _candles(count: int = 650) -> list[dict]:
    rng = np.random.default_rng(1717)
    closes = 100 * np.exp(np.cumsum(rng.normal(.0001, .012, count)))
    stamps = pd.date_range("2023-01-01", periods=count, freq="D", tz="UTC")
    result = []
    for index, close in enumerate(closes):
        opened = closes[index - 1] if index else close
        result.append({"timestamp": stamps[index].isoformat(), "open": float(opened),
                       "high": float(max(opened, close) * 1.002),
                       "low": float(min(opened, close) * .998), "close": float(close),
                       "volume": float(rng.integers(1000, 10000))})
    return result


def test_forward_model_replaces_interactive_ensemble(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_AI_DATA_DIR", str(tmp_path))
    candles = _candles()
    profile = _asset_profile("crypto", "BTC", pd.DataFrame(candles))
    profile["forward_direction"] = True
    factories, _ = _model_factories(profile)
    assert list(factories) == ["XGBoost"]
    result = predict(candles, "1d", "crypto", "BTC")
    assert result["model"]["models"] == ["XGBoost"]
    assert result["model"]["walk_forward"] is True
    for forecast in result["predictions"].values():
        if not forecast.get("prediction"):
            continue
        assert forecast["model_level"] == "EXPERIMENTAL"
        assert forecast["validation_scheme"]["leakage_check"] is True
        assert abs(sum(forecast["probabilities"].values()) - 1) < .001
