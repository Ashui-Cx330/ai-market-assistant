"""Strict, point-in-time Quant Research Pipeline V3.

This module deliberately separates research from the interactive prediction
engine.  It may produce a challenger, but never promotes a model by itself.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import Lasso, LinearRegression, LogisticRegression, Ridge
from sklearn.metrics import (accuracy_score, balanced_accuracy_score, f1_score,
                             log_loss, matthews_corrcoef)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .ai_engine import (CLASSES, FEATURES, FEATURE_GROUPS, _LabelAdapter,
                        _PlattCalibrator, _probabilities, feature_frame)
from .horizons import supported_horizons, target_indices, utc_timestamps

LEGACY_EXPERIMENTAL_MODELS = [
    "LogisticRegression", "LightGBM", "XGBoost", "CatBoost", "RandomForest",
    "LSTM", "GRU", "Transformer", "TFT", "NewsModel", "Ensemble",
]

MARKET_COSTS = {
    "CN": {"commission": .0003, "stamp_duty_sell": .0005, "slippage": .0005},
    "US": {"commission": .0001, "stamp_duty_sell": 0.0, "slippage": .0005},
    "CRYPTO": {"commission": .0006, "stamp_duty_sell": 0.0, "slippage": .0005},
}


def _safe_float(value: Any) -> float | None:
    try:
        result = float(value)
        return result if np.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def dataset_audit(universe: dict[str, list[dict]], market: str, interval: str = "1d") -> dict:
    """Audit raw candles before any model or label is constructed."""
    now = pd.Timestamp.now(tz="UTC")
    assets: list[dict] = []
    totals = {"candles": 0, "missing": 0, "duplicates": 0, "ohlc_invalid": 0,
              "negative_volume": 0, "future_rows": 0, "suspension_or_gap_rows": 0}
    for symbol, candles in universe.items():
        frame = pd.DataFrame(candles).copy()
        required = ["timestamp", "open", "high", "low", "close", "volume"]
        missing_columns = [name for name in required if name not in frame]
        if missing_columns:
            assets.append({"symbol": symbol, "status": "FAILED", "rows": len(frame),
                           "missing_columns": missing_columns})
            continue
        stamps = utc_timestamps(frame["timestamp"].tolist())
        numeric = frame[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
        missing = int(numeric.isna().sum().sum())
        duplicates = int(pd.Series(stamps).duplicated().sum())
        invalid = int(((numeric["high"] < numeric[["open", "close"]].max(axis=1)) |
                       (numeric["low"] > numeric[["open", "close"]].min(axis=1)) |
                       (numeric["high"] < numeric["low"]) |
                       (numeric[["open", "high", "low", "close"]] <= 0).any(axis=1)).sum())
        negative_volume = int((numeric["volume"] < 0).sum())
        future_rows = int((stamps.asi8 > now.value + 300_000_000_000).sum())
        ordered = pd.Series(stamps).sort_values().reset_index(drop=True)
        if interval == "1d":
            gaps = ordered.diff().dt.days.fillna(1)
            gap_rows = int((gaps > (4 if market in {"CN", "US"} else 2)).sum())
        else:
            minutes = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240}.get(interval, 1440)
            gap_rows = int((ordered.diff() > pd.Timedelta(minutes=minutes * 2.1)).sum())
        row = {"symbol": symbol, "status": "PASSED" if not (missing or duplicates or invalid or negative_volume or future_rows) else "FAILED",
               "rows": len(frame), "start": ordered.iloc[0].isoformat() if len(ordered) else None,
               "end": ordered.iloc[-1].isoformat() if len(ordered) else None, "timezone": "UTC_NORMALIZED",
               "missing_values": missing, "duplicate_timestamps": duplicates, "ohlc_invalid": invalid,
               "negative_volume": negative_volume, "future_rows": future_rows,
               "suspension_or_gap_rows": gap_rows,
               "market_closure_policy": "Observed bars only; weekends/holidays are not synthesized."}
        assets.append(row)
        totals["candles"] += len(frame)
        for key in totals:
            if key != "candles": totals[key] += int(row.get({"missing": "missing_values", "duplicates": "duplicate_timestamps"}.get(key, key), 0))
    passed = bool(assets) and all(row["status"] == "PASSED" for row in assets)
    fingerprint = hashlib.sha256(json.dumps(assets, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    return {"audit": "Dataset Audit V3", "market": market, "interval": interval,
            "status": "PASSED" if passed else "FAILED", "dataset_version": f"{market}-{interval}-{fingerprint}",
            "assets": assets, "totals": totals, "generated_at": datetime.now(timezone.utc).isoformat()}


def _future_path(frame: pd.DataFrame, indices: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    close = frame["close"].to_numpy(float)
    low = frame["low"].to_numpy(float)
    returns = np.full(len(frame), np.nan)
    drawdown = np.full(len(frame), np.nan)
    for index, target in enumerate(indices):
        if target <= index:
            continue
        returns[index] = close[target] / close[index] - 1
        drawdown[index] = low[index + 1:target + 1].min() / close[index] - 1
    return returns, drawdown


def build_panel(universe: dict[str, list[dict]], market: str, interval: str, horizon: str) -> tuple[pd.DataFrame, dict]:
    rows: list[pd.DataFrame] = []
    asset_type = "crypto" if market == "CRYPTO" else "stock"
    bars = supported_horizons(interval)
    if horizon not in bars:
        raise ValueError(f"{market}/{interval} cannot express {horizon}")
    for symbol, candles in universe.items():
        frame = feature_frame(candles).copy()
        targets = target_indices(pd.DatetimeIndex(frame["timestamp_utc"]), asset_type, interval, horizon, market)
        future_return, future_drawdown = _future_path(frame, targets)
        frame["symbol"] = symbol
        stamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
        frame["session_date"] = (stamps.dt.date.astype(str) if interval == "1d"
                                 else stamps.dt.floor(interval).astype(str))
        frame["target_time"] = [pd.NaT if index < 0 else frame["timestamp_utc"].iloc[index] for index in targets]
        frame["future_return"] = future_return
        frame["future_max_drawdown"] = future_drawdown
        frame["atr_normalized"] = frame["atr"] / frame["close"]
        rows.append(frame)
    if not rows:
        raise ValueError("No market data available")
    panel = pd.concat(rows, ignore_index=True)
    panel = panel.dropna(subset=FEATURES + ["future_return", "future_max_drawdown", "target_time"])
    panel = panel.sort_values(["session_date", "symbol"]).reset_index(drop=True)
    # Cross-sectional values use only assets observable in the same session.
    for name in FEATURES:
        grouped = panel.groupby("session_date")[name]
        mean = grouped.transform("mean")
        std = grouped.transform("std").replace(0, np.nan)
        panel[f"z_{name}"] = ((panel[name] - mean) / std).fillna(0).clip(-5, 5)
    panel["relative_return_5"] = panel["return_5"] - panel.groupby("session_date")["return_5"].transform("median")
    panel["relative_return_20"] = panel["return_20"] - panel.groupby("session_date")["return_20"].transform("median")
    panel["alpha_target"] = panel["future_return"] - panel.groupby("session_date")["future_return"].transform("mean")
    feature_cols = [f"z_{name}" for name in FEATURES] + ["relative_return_5", "relative_return_20"]
    temporal = temporal_leakage_audit(panel)
    return panel, {"feature_columns": feature_cols, "horizon_bars": bars[horizon], "temporal_audit": temporal}


def temporal_leakage_audit(panel: pd.DataFrame) -> dict:
    feature_time = pd.to_datetime(panel["timestamp_utc"], utc=True)
    label_time = pd.to_datetime(panel["target_time"], utc=True)
    invalid_order = int((feature_time >= label_time).sum())
    future_feature = int((feature_time.astype("int64") > pd.Timestamp.now(tz="UTC").value + 300_000_000_000).sum())
    duplicate_keys = int(panel.duplicated(["symbol", "timestamp_utc"]).sum())
    status = "PASSED" if invalid_order == 0 and future_feature == 0 and duplicate_keys == 0 else "FAILED"
    return {"audit": "Temporal Leakage Audit V3", "status": status,
            "prediction_timestamp": "feature row timestamp",
            "feature_cutoff_rule": "feature_timestamp <= prediction_timestamp",
            "label_rule": "label_timestamp > prediction_timestamp",
            "news_rule": "News is excluded until point-in-time N>=30 and walk-forward/ablation pass.",
            "invalid_feature_label_order": invalid_order, "future_feature_rows": future_feature,
            "duplicate_asset_timestamps": duplicate_keys, "random_split": False,
            "test_parameter_tuning": False}


def _folds(panel: pd.DataFrame, count: int = 5) -> list[dict]:
    dates = np.asarray(sorted(panel["session_date"].unique()))
    if len(dates) < 180:
        raise ValueError("At least 180 distinct sessions are required for five-window walk-forward")
    start = max(100, int(len(dates) * .5))
    chunk = max(15, (len(dates) - start) // count)
    result = []
    for begin in range(start, len(dates), chunk):
        end = min(len(dates), begin + chunk)
        validation_size = max(20, int(begin * .15))
        result.append({"train_dates": dates[:begin - validation_size],
                       "validation_dates": dates[begin - validation_size:begin],
                       "test_dates": dates[begin:end]})
        if len(result) == count:
            break
    if len(result) < count:
        raise ValueError("Five complete walk-forward windows could not be formed")
    return result


def _classification_metrics(y: np.ndarray, probabilities: np.ndarray) -> dict:
    predicted = CLASSES[np.argmax(probabilities, axis=1)]
    one_hot = np.column_stack([(y == cls).astype(float) for cls in CLASSES])
    return {"samples": int(len(y)), "accuracy": round(float(accuracy_score(y, predicted)), 4),
            "balanced_accuracy": round(float(balanced_accuracy_score(y, predicted)), 4),
            "macro_f1": round(float(f1_score(y, predicted, average="macro", zero_division=0)), 4),
            "mcc": round(float(matthews_corrcoef(y, predicted)), 4),
            "brier": round(float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))), 4),
            "log_loss": round(float(log_loss(y, np.clip(probabilities, 1e-12, 1), labels=CLASSES)), 4)}


def _correlation(a: np.ndarray, b: np.ndarray, rank: bool = False) -> float | None:
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 3:
        return None
    left, right = a[mask], b[mask]
    if rank:
        left, right = pd.Series(left).rank().to_numpy(), pd.Series(right).rank().to_numpy()
    if np.std(left) == 0 or np.std(right) == 0:
        return None
    return round(float(np.corrcoef(left, right)[0, 1]), 4)


def _classifier_factories() -> tuple[dict[str, Callable[[], Any]], dict[str, str]]:
    factories: dict[str, Callable[[], Any]] = {
        "LogisticRegression": lambda: make_pipeline(StandardScaler(), LogisticRegression(
            C=.5, class_weight="balanced", max_iter=1500, random_state=42)),
        "RandomForest": lambda: RandomForestClassifier(n_estimators=160, max_depth=7,
            min_samples_leaf=8, class_weight="balanced", random_state=42, n_jobs=2),
    }
    unavailable = {
        "LSTM": "UNQUALIFIED: insufficient identical point-in-time panel for deep model",
        "GRU": "UNQUALIFIED: insufficient identical point-in-time panel for deep model",
        "Transformer": "UNQUALIFIED: insufficient identical point-in-time panel for deep model",
        "TFT": "UNQUALIFIED: no validated multivariate exogenous history",
        "NewsModel": "EXPERIMENTAL: point-in-time event outcomes N<30",
    }
    try:
        from lightgbm import LGBMClassifier
        factories["LightGBM"] = lambda: LGBMClassifier(n_estimators=160, max_depth=6, num_leaves=25,
            learning_rate=.04, class_weight="balanced", random_state=42, n_jobs=2, verbosity=-1)
    except Exception as exc:
        unavailable["LightGBM"] = type(exc).__name__
    try:
        from xgboost import XGBClassifier
        factories["XGBoost"] = lambda: _LabelAdapter(XGBClassifier(n_estimators=140, max_depth=4,
            learning_rate=.04, subsample=.8, colsample_bytree=.8, objective="multi:softprob",
            eval_metric="mlogloss", random_state=42, n_jobs=2))
    except Exception as exc:
        unavailable["XGBoost"] = type(exc).__name__
    try:
        from catboost import CatBoostClassifier
        factories["CatBoost"] = lambda: CatBoostClassifier(iterations=120, depth=5, learning_rate=.05,
            loss_function="MultiClass", auto_class_weights="Balanced", random_seed=42,
            verbose=False, thread_count=2, allow_writing_files=False)
    except Exception as exc:
        unavailable["CatBoost"] = type(exc).__name__
    return factories, unavailable


def _regressor_factories() -> tuple[dict[str, Callable[[], Any]], dict[str, str]]:
    factories: dict[str, Callable[[], Any]] = {
        "LinearRegression": lambda: make_pipeline(StandardScaler(), LinearRegression()),
        "Ridge": lambda: make_pipeline(StandardScaler(), Ridge(alpha=5.0)),
        "Lasso": lambda: make_pipeline(StandardScaler(), Lasso(alpha=.0002, max_iter=3000)),
    }
    unavailable: dict[str, str] = {}
    try:
        from lightgbm import LGBMRegressor
        factories["LightGBM"] = lambda: LGBMRegressor(n_estimators=180, max_depth=6, num_leaves=25,
            learning_rate=.035, random_state=42, n_jobs=2, verbosity=-1)
    except Exception as exc:
        unavailable["LightGBM"] = type(exc).__name__
    try:
        from xgboost import XGBRegressor
        factories["XGBoost"] = lambda: XGBRegressor(n_estimators=150, max_depth=4, learning_rate=.04,
            subsample=.8, colsample_bytree=.8, objective="reg:squarederror", random_state=42, n_jobs=2)
    except Exception as exc:
        unavailable["XGBoost"] = type(exc).__name__
    return factories, unavailable


def _portfolio_metrics(returns: np.ndarray, periods: int, costs: float, turnover: np.ndarray) -> dict:
    net = returns - turnover * costs
    equity = np.cumprod(1 + np.nan_to_num(net))
    peak = np.maximum.accumulate(equity)
    drawdown = equity / np.maximum(peak, 1e-12) - 1
    std = float(np.std(net, ddof=1)) if len(net) > 1 else 0
    downside = net[net < 0]
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else 0
    total = float(equity[-1] - 1) if len(equity) else 0
    years = max(len(net) / periods, 1 / periods)
    annualized = (1 + total) ** (1 / years) - 1 if total > -1 else -1
    maximum_drawdown = float(drawdown.min()) if len(drawdown) else 0
    return {"observations": int(len(net)), "total_return": round(total, 4),
            "annualized_return": round(float(annualized), 4), "volatility": round(std * np.sqrt(periods), 4),
            "sharpe": round(float(np.mean(net) / std * np.sqrt(periods)), 4) if std else None,
            "sortino": round(float(np.mean(net) / downside_std * np.sqrt(periods)), 4) if downside_std else None,
            "maximum_drawdown": round(maximum_drawdown, 4),
            "calmar": round(float(annualized / abs(maximum_drawdown)), 4) if maximum_drawdown < 0 else None,
            "turnover": round(float(turnover.sum()), 4), "transaction_cost": round(float((turnover * costs).sum()), 4)}


def _stability(values: list[float | None]) -> dict:
    valid = np.asarray([value for value in values if value is not None and np.isfinite(value)], float)
    if not len(valid):
        return {"mean": None, "median": None, "std": None, "worst": None, "positive_window_ratio": None}
    deviation = float(valid.std(ddof=1)) if len(valid) > 1 else 0.0
    return {"mean": round(float(valid.mean()), 4), "median": round(float(np.median(valid)), 4),
            "std": round(deviation, 4), "icir": round(float(valid.mean() / deviation), 4) if deviation else None,
            "worst": round(float(valid.min()), 4), "positive_window_ratio": round(float((valid > 0).mean()), 4)}


def run_research(universe: dict[str, list[dict]], market: str, interval: str = "1d",
                 horizon: str = "T+5", folds: int = 5) -> dict:
    audit = dataset_audit(universe, market, interval)
    if audit["status"] != "PASSED":
        return {"engine": "Quant Research Pipeline V3", "decision": "DATA_AUDIT_FAILED", "dataset_audit": audit,
                "production_model": None, "legacy_models": {name: "EXPERIMENTAL" for name in LEGACY_EXPERIMENTAL_MODELS}}
    panel, contract = build_panel(universe, market, interval, horizon)
    split_rows = _folds(panel, folds)
    feature_cols = contract["feature_columns"]
    classifiers, unavailable_classifiers = _classifier_factories()
    regressors, unavailable_regressors = _regressor_factories()
    classification_rows: dict[str, list[dict]] = {name: [] for name in classifiers}
    regression_rows: dict[str, list[dict]] = {name: [] for name in regressors}
    risk_rows: list[dict] = []
    baseline_rows: dict[str, list[dict]] = {"MajorityClass": [], "RandomWalk": [], "NaiveMomentum": []}
    portfolio_returns = {name: {"top10_bottom10": [], "top20_bottom20": []} for name in regressors}
    portfolio_turnover = {name: {"top10_bottom10": [], "top20_bottom20": []} for name in regressors}
    regime_rows: dict[str, dict[str, list[dict]]] = {name: {} for name in regressors}
    ablation_groups = {
        "price": [f"z_{name}" for name in FEATURE_GROUPS["price"]],
        "technical": [f"z_{name}" for name in FEATURE_GROUPS["technical"]],
        "volume": [f"z_{name}" for name in FEATURE_GROUPS["volume"]],
        "structure": [f"z_{name}" for name in FEATURE_GROUPS["structure"]],
        "regime": [f"z_{name}" for name in FEATURE_GROUPS["regime"]],
        "all_observed": feature_cols,
    }
    ablation_rows: dict[str, list[float | None]] = {name: [] for name in ablation_groups}
    fold_reports = []
    latest_shap: dict = {"status": "UNAVAILABLE", "reason": "LightGBM was not fitted"}

    for fold_number, split in enumerate(split_rows, 1):
        train = panel[panel["session_date"].isin(split["train_dates"])].copy()
        validation = panel[panel["session_date"].isin(split["validation_dates"])].copy()
        test = panel[panel["session_date"].isin(split["test_dates"])].copy()
        test_start = pd.Timestamp(test["timestamp_utc"].min())
        train = train[pd.to_datetime(train["target_time"], utc=True) < pd.Timestamp(validation["timestamp_utc"].min())]
        validation = validation[pd.to_datetime(validation["target_time"], utc=True) < test_start]
        if min(len(train), len(validation), len(test)) < 30:
            continue
        threshold = float(np.clip(train["atr_normalized"].median() * .5, .001, .025))
        risk_threshold = float(min(-.01, train["future_max_drawdown"].quantile(.20)))
        for frame in (train, validation, test):
            frame["direction_label"] = np.where(frame["future_return"] > threshold, 1,
                np.where(frame["future_return"] < -threshold, -1, 0))
            frame["risk_label"] = (frame["future_max_drawdown"] <= risk_threshold).astype(int)
        x_train, x_val, x_test = train[feature_cols], validation[feature_cols], test[feature_cols]
        regime = np.where(test["regime_high_vol"] > .5, "HIGH_VOL",
                 np.where(test["regime_trend"] > .15, "BULL",
                 np.where(test["regime_trend"] < -.15, "BEAR",
                 np.where(test["volatility"] < train["volatility"].quantile(.25), "LOW_VOL", "SIDEWAYS"))))
        test["_research_regime"] = regime
        y_train, y_val, y_test = train["direction_label"], validation["direction_label"], test["direction_label"].to_numpy(int)
        class_distribution = {str(label): round(float((y_train == label).mean()), 4) for label in CLASSES}
        majority = int(y_train.value_counts().idxmax())
        majority_prob = np.full((len(test), 3), .025); majority_prob[:, majority + 1] = .95
        random_prob = np.full((len(test), 3), 1 / 3)
        naive_pred = np.sign(test["return_5"].to_numpy(float)).astype(int)
        naive_prob = np.full((len(test), 3), .15); naive_prob[np.arange(len(test)), naive_pred + 1] = .7
        baseline_rows["MajorityClass"].append(_classification_metrics(y_test, majority_prob))
        baseline_rows["RandomWalk"].append(_classification_metrics(y_test, random_prob))
        baseline_rows["NaiveMomentum"].append(_classification_metrics(y_test, naive_prob))
        risk_model = make_pipeline(StandardScaler(), LogisticRegression(
            C=.5, class_weight="balanced", max_iter=1500, random_state=42))
        risk_model.fit(x_train, train["risk_label"])
        risk_probability = risk_model.predict_proba(x_test)[:, 1]
        risk_prediction = (risk_probability >= .5).astype(int)
        risk_actual = test["risk_label"].to_numpy(int)
        risk_rows.append({"samples": len(test),
            "balanced_accuracy": round(float(balanced_accuracy_score(risk_actual, risk_prediction)), 4),
            "macro_f1": round(float(f1_score(risk_actual, risk_prediction, average="macro", zero_division=0)), 4),
            "mcc": round(float(matthews_corrcoef(risk_actual, risk_prediction)), 4),
            "brier": round(float(np.mean((risk_probability - risk_actual) ** 2)), 4),
            "log_loss": round(float(log_loss(risk_actual, np.column_stack([1-risk_probability, risk_probability]), labels=[0, 1])), 4)})
        model_probabilities = []
        for name, factory in classifiers.items():
            try:
                model = factory(); model.fit(x_train, y_train)
                calibrator = _PlattCalibrator().fit(_probabilities(model, x_val), y_val)
                probabilities = calibrator.transform(_probabilities(model, x_test))
                metrics = _classification_metrics(y_test, probabilities)
                metrics["ic"] = _correlation(probabilities[:, 2] - probabilities[:, 0], test["future_return"].to_numpy(float))
                metrics["rank_ic"] = _correlation(probabilities[:, 2] - probabilities[:, 0], test["future_return"].to_numpy(float), True)
                classification_rows[name].append(metrics); model_probabilities.append((name, probabilities))
            except Exception as exc:
                unavailable_classifiers[name] = f"fold {fold_number}: {type(exc).__name__}"
        for name, factory in regressors.items():
            try:
                model = factory(); model.fit(x_train, train["alpha_target"])
                predictions = np.asarray(model.predict(x_test), float)
                metrics = {"samples": len(test), "mae": round(float(np.mean(np.abs(predictions - test["alpha_target"]))), 5),
                           "rmse": round(float(np.sqrt(np.mean((predictions - test["alpha_target"]) ** 2))), 5),
                           "ic": _correlation(predictions, test["future_return"].to_numpy(float)),
                           "rank_ic": _correlation(predictions, test["future_return"].to_numpy(float), True)}
                regression_rows[name].append(metrics)
                for regime_name in sorted(test["_research_regime"].unique()):
                    mask = test["_research_regime"].to_numpy() == regime_name
                    regime_rows[name].setdefault(regime_name, []).append({
                        "samples": int(mask.sum()),
                        "ic": _correlation(predictions[mask], test.loc[mask, "future_return"].to_numpy(float)),
                        "rank_ic": _correlation(predictions[mask], test.loc[mask, "future_return"].to_numpy(float), True),
                    })
                ranked = test[["session_date", "symbol", "future_return"]].copy(); ranked["score"] = predictions
                selected_dates = sorted(ranked["session_date"].unique())[::max(1, contract["horizon_bars"])]
                for bucket, quantile in (("top10_bottom10", .1), ("top20_bottom20", .2)):
                    previous_long: set[str] = set(); previous_short: set[str] = set()
                    for date in selected_dates:
                        group = ranked[ranked["session_date"] == date].sort_values("score")
                        count = max(1, int(np.ceil(len(group) * quantile)))
                        long_names, short_names = set(group.tail(count)["symbol"]), set(group.head(count)["symbol"])
                        gross = float(group.tail(count)["future_return"].mean() - group.head(count)["future_return"].mean())
                        changed = len(long_names.symmetric_difference(previous_long)) + len(short_names.symmetric_difference(previous_short))
                        turnover = changed / max(2 * count, 1)
                        portfolio_returns[name][bucket].append(gross); portfolio_turnover[name][bucket].append(turnover)
                        previous_long, previous_short = long_names, short_names
                if name == "LightGBM" and fold_number == len(split_rows) and hasattr(model, "booster_"):
                    contributions = model.booster_.predict(x_test.tail(1), pred_contrib=True)[0][:-1]
                    order = np.argsort(np.abs(contributions))[::-1][:10]
                    gain = model.booster_.feature_importance(importance_type="gain")
                    gain_total = max(float(gain.sum()), 1e-12)
                    gain_order = np.argsort(gain)[::-1]
                    latest_shap = {"status": "AVAILABLE", "method": "LightGBM TreeSHAP pred_contrib",
                                   "notice": "SHAP values are feature contributions, not probabilities.",
                                   "top_factors": [{"feature": feature_cols[i].removeprefix("z_"),
                                                    "shap": round(float(contributions[i]), 6)} for i in order],
                                   "feature_importance_gain": [{"feature": feature_cols[i].removeprefix("z_"),
                                                    "importance": round(float(gain[i] / gain_total), 6)} for i in gain_order]}
            except Exception as exc:
                unavailable_regressors[name] = f"fold {fold_number}: {type(exc).__name__}"
        for group_name, columns in ablation_groups.items():
            try:
                model = make_pipeline(StandardScaler(), Ridge(alpha=5.0))
                model.fit(train[columns], train["alpha_target"])
                prediction = np.asarray(model.predict(test[columns]), float)
                ablation_rows[group_name].append(_correlation(
                    prediction, test["future_return"].to_numpy(float), True))
            except Exception:
                ablation_rows[group_name].append(None)
        disagreement = None
        if model_probabilities:
            votes = np.column_stack([CLASSES[np.argmax(item[1], axis=1)] for item in model_probabilities])
            disagreement = round(float(np.mean([len(set(row)) > 1 for row in votes])), 4)
        fold_reports.append({"window": fold_number, "train": [str(split["train_dates"][0]), str(split["train_dates"][-1])],
                             "validation": [str(split["validation_dates"][0]), str(split["validation_dates"][-1])],
                             "test": [str(split["test_dates"][0]), str(split["test_dates"][-1])],
                             "samples": {"train": len(train), "validation": len(validation), "test": len(test)},
                             "threshold_from_train": round(threshold, 6), "risk_threshold_from_train": round(risk_threshold, 6),
                             "class_distribution_train": class_distribution, "model_disagreement": disagreement,
                             "regime_counts": pd.Series(regime).value_counts().to_dict()})

    if len(fold_reports) < folds:
        raise ValueError(f"Only {len(fold_reports)} valid walk-forward windows; {folds} required")

    def summarize_class(rows: list[dict]) -> dict:
        keys = ["accuracy", "balanced_accuracy", "macro_f1", "mcc", "brier", "log_loss", "ic", "rank_ic"]
        return {key: _stability([row.get(key) for row in rows]) for key in keys} | {"windows": rows}

    def summarize_reg(rows: list[dict]) -> dict:
        return {key: _stability([row.get(key) for row in rows]) for key in ["mae", "rmse", "ic", "rank_ic"]} | {"windows": rows}

    class_summary = {name: summarize_class(rows) for name, rows in classification_rows.items() if rows}
    class_summary.update({name: summarize_class(rows) for name, rows in baseline_rows.items() if rows})
    reg_summary = {name: summarize_reg(rows) for name, rows in regression_rows.items() if rows}
    regime_summary = {model: {regime: {
        "ic": _stability([row["ic"] for row in rows]),
        "rank_ic": _stability([row["rank_ic"] for row in rows]),
        "samples": sum(row["samples"] for row in rows),
    } for regime, rows in regimes.items()} for model, regimes in regime_rows.items() if regimes}
    ablation_summary = {name: _stability(values) for name, values in ablation_rows.items()}
    cost_spec = MARKET_COSTS[market]
    round_trip_cost = cost_spec["commission"] * 2 + cost_spec["stamp_duty_sell"] + cost_spec["slippage"] * 2
    annual_entries = (365 * 24 if market == "CRYPTO" and interval == "1h" else
                      365 * 6 if market == "CRYPTO" and interval == "4h" else
                      365 if market == "CRYPTO" else 252)
    periods = annual_entries // max(1, contract["horizon_bars"])
    portfolios = {name: {bucket: _portfolio_metrics(np.asarray(values), periods, round_trip_cost,
        np.asarray(portfolio_turnover[name][bucket])) for bucket, values in buckets.items() if values}
        for name, buckets in portfolio_returns.items() if any(buckets.values())}
    best_reg = max(reg_summary, key=lambda name: reg_summary[name]["rank_ic"]["median"] or -999, default=None)
    best_class = max((name for name in class_summary if name not in baseline_rows),
                     key=lambda name: class_summary[name]["balanced_accuracy"]["median"] or -999, default=None)
    majority_balanced = class_summary.get("MajorityClass", {}).get("balanced_accuracy", {}).get("median") or 0
    candidate_metrics = reg_summary.get(best_reg, {})
    portfolio = portfolios.get(best_reg, {}).get("top20_bottom20", {})
    positive_ratio = candidate_metrics.get("rank_ic", {}).get("positive_window_ratio") or 0
    validated = bool(best_reg and (candidate_metrics["rank_ic"]["median"] or 0) > .02 and positive_ratio >= .8 and
                     (portfolio.get("sharpe") or -99) > .5 and (portfolio.get("total_return") or 0) > 0 and
                     best_class and (class_summary[best_class]["balanced_accuracy"]["median"] or 0) > majority_balanced + .03)
    uncertainty_reasons = []
    if not validated: uncertainty_reasons.append("No candidate passes every promotion gate")
    if len(panel) < 5000: uncertainty_reasons.append("Cross-sectional panel remains small")
    if any((row.get("model_disagreement") or 0) > .35 for row in fold_reports): uncertainty_reasons.append("Model disagreement is high")
    if audit["status"] != "PASSED": uncertainty_reasons.append("Dataset quality failed")
    return {"engine": "Quant Research Pipeline V3", "generated_at": datetime.now(timezone.utc).isoformat(),
            "market": market, "interval": interval, "horizon": horizon, "dataset_audit": audit,
            "label_audit": {"tasks": {"return_regression": "future relative return", "direction_classification": "ATR-adjusted UP/SIDE/DOWN",
                "risk_classification": "future path drawdown beyond train-only 20th percentile"},
                "threshold_source": "training fold only", "class_weight": "balanced", "sample_deletion": False},
            "temporal_leakage_audit": contract["temporal_audit"], "features": {"observed": len(FEATURES),
                "cross_sectional": len(feature_cols), "normalization": "same-session z-score, clipped to +/-5",
                "unavailable_real_features": ["PE", "PB", "ROE", "RevenueGrowth", "EPSGrowth", "FundingRate",
                    "OpenInterest", "Liquidations", "LongShortRatio", "BTCDominance", "VIX", "DXY", "US10Y"],
                "unavailable_policy": "Not simulated; excluded until a timestamped reliable provider exists."},
            "walk_forward": {"method": "five rolling chronological windows; purged labels; separate validation", "windows": fold_reports},
            "model_tournament": {"classification": class_summary, "regression": reg_summary,
                "risk_classification": {key: _stability([row.get(key) for row in risk_rows])
                    for key in ["balanced_accuracy", "macro_f1", "mcc", "brier", "log_loss"]} | {"windows": risk_rows},
                "unavailable": {**unavailable_classifiers, **unavailable_regressors}, "best_classifier": best_class,
                "best_regressor": best_reg, "deep_models": "Legacy Experimental Benchmark; not trained without sufficient panel."},
            "portfolio_backtest": {"method": "top/bottom 10% and 20%; non-overlapping holding dates",
                "costs": cost_spec, "round_trip_cost": round_trip_cost, "models": portfolios},
            "factor_research": {"ablation": ablation_summary,
                "interpretation": "Rank IC and gain/SHAP are out-of-sample diagnostics, not causal proof."},
            "regime_performance": regime_summary,
            "market_structure": {
                "implemented": ["same-session cross-sectional ranking", "relative returns", "observed-bar calendar"],
                "not_simulated": (["exact suspension flags", "limit-up/limit-down state", "turnover/free-float", "northbound flow"]
                    if market == "CN" else ["SPY/QQQ/SOXX benchmark", "VIX", "DXY", "US10Y", "sector-relative benchmark"]
                    if market == "US" else ["funding rate", "open interest", "liquidations", "long-short ratio", "BTC dominance"]),
            },
            "explainability": latest_shap, "news": {"status": "EXPERIMENTAL", "production_probability_weight": 0,
                "minimum_events": 30, "reason": "Point-in-time event outcomes remain below the minimum evidence threshold."},
            "uncertainty": {"level": "LOW" if validated else "HIGH", "reasons": uncertainty_reasons},
            "champion": None, "challenger": best_reg if validated else None,
            "decision": "VALIDATED_CHALLENGER_REQUIRES_SHADOW_AND_APPROVAL" if validated else "NO_EDGE",
            "production_model": None, "automatic_retraining": False,
            "legacy_models": {name: "EXPERIMENTAL" for name in LEGACY_EXPERIMENTAL_MODELS},
            "promotion_gate": ["out-of-sample", "five walk-forward windows", "baseline beat", "positive stable IC",
                "acceptable calibration", "positive after costs", "acceptable drawdown", "multiple-asset stability",
                "shadow evaluation", "manual approval"]}


def model_drift(records: list[dict], now: datetime | None = None) -> dict:
    now_stamp = pd.Timestamp(now or datetime.now(timezone.utc))
    if now_stamp.tzinfo is None:
        now_stamp = now_stamp.tz_localize("UTC")
    rows = [row for row in records if row.get("actual") and (row.get("prediction_time") or row.get("resolved_at"))]
    stamped_rows = []
    for row in rows:
        stamp = pd.Timestamp(row.get("prediction_time") or row["resolved_at"])
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
        stamped_rows.append((stamp, row))
    earliest = min((item[0] for item in stamped_rows), default=None)
    latest = max((item[0] for item in stamped_rows), default=None)
    coverage_days = (latest - earliest).total_seconds() / 86400 if earliest is not None and latest is not None else 0
    windows = {}
    for days in (30, 90, 180):
        subset = [row for stamp, row in stamped_rows if stamp.to_pydatetime() >= now_stamp.to_pydatetime() - timedelta(days=days)]
        if not subset:
            windows[str(days)] = {"samples": 0, "status": "INSUFFICIENT_DATA"}; continue
        correct = np.asarray([float(row.get("correct") or 0) for row in subset])
        confidence = np.asarray([max(float(row.get("prob_down") or 0), float(row.get("prob_flat") or 0),
                                     float(row.get("prob_up") or 0)) for row in subset])
        windows[str(days)] = {"samples": len(subset), "accuracy": round(float(correct.mean()), 4),
                              "calibration_gap": round(float(np.mean(np.abs(confidence - correct))), 4)}
    recent, long = windows["30"], windows["180"]
    sufficient_time = coverage_days >= 170
    drift = bool(sufficient_time and recent.get("samples", 0) >= 20 and long.get("samples", 0) >= 40 and
                 recent.get("accuracy", 0) < long.get("accuracy", 0) - .05)
    return {"status": "MODEL_DRIFT" if drift else "INSUFFICIENT_TIME_COVERAGE" if not sufficient_time else
                    "INSUFFICIENT_DATA" if recent.get("samples", 0) < 20 else "NO_DRIFT_DETECTED",
            "time_coverage_days": round(coverage_days, 2), "minimum_coverage_days": 170,
            "timestamp_basis": "prediction_time; resolved_at fallback",
            "windows": windows, "action": "DOWNGRADE_TO_EXPERIMENTAL" if drift else "KEEP_EXPERIMENTAL",
            "automatic_retraining": False, "retraining_candidate": drift,
            "approval_flow": "Backtest -> Validation -> Shadow -> Manual Approval"}
