from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Callable

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, f1_score, log_loss,
                             precision_score, recall_score, roc_auc_score)
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .feature_services import FeatureStore
from .horizons import future_timestamp, horizon_bar_count, supported_horizons, target_indices, utc_timestamps
from .indicators import calculate_indicators
from .model_manager import ModelManager

CLASSES = np.array([-1, 0, 1])
FEATURES = ["return_1", "return_3", "return_5", "rsi", "macd", "macd_signal", "atr", "volume_change",
            "volatility", "ma5_gap", "ma20_gap", "boll_position", "flow_pressure", "sentiment_score"]
FEATURE_LABELS = {
    "return_1": "短期价格动量", "return_3": "3 周期动量", "return_5": "5 周期动量",
    "rsi": "RSI 强弱", "macd": "MACD 趋势", "macd_signal": "MACD 信号线", "atr": "ATR 波动",
    "volume_change": "成交量变化", "volatility": "历史波动率", "ma5_gap": "价格与 MA5 偏离",
    "ma20_gap": "价格与 MA20 偏离", "boll_position": "布林带位置",
    "flow_pressure": "量价资金压力", "sentiment_score": "市场情绪得分",
}


def feature_frame(candles: list[dict]) -> pd.DataFrame:
    frame = calculate_indicators(candles)
    frame["timestamp_utc"] = utc_timestamps(frame["timestamp"].tolist())
    frame["ma5_gap"] = frame["close"] / frame["ma5"] - 1
    frame["ma20_gap"] = frame["close"] / frame["ma20"] - 1
    width = (frame["boll_upper"] - frame["boll_lower"]).replace(0, np.nan)
    frame["boll_position"] = (frame["close"] - frame["boll_lower"]) / width
    return FeatureStore().enrich(frame).replace([np.inf, -np.inf], np.nan)


def _asset_profile(asset_type: str, symbol: str, frame: pd.DataFrame) -> dict:
    if asset_type == "stock":
        return {"name":"A_SHARE","max_depth":7,"min_leaf":5,"subsample":.82,"confidence_factor":1.0,"slippage_factor":1.0}
    clean=symbol.upper().replace("/USDT","").replace("-USDT","")
    if clean=="BTC": name,factor="BTC",1.0
    elif clean=="ETH": name,factor="ETH",.97
    elif clean in {"SOL","BNB","XRP","ADA","DOGE","AVAX","LINK","DOT"}: name,factor="MAJOR_ALTCOIN",.9
    else: name,factor="LOW_LIQUIDITY_TOKEN",.75
    turnover=(frame["close"]*frame["volume"]).tail(100).median()
    return {"name":name,"max_depth":8 if name in {"BTC","ETH"} else 7,"min_leaf":3 if name in {"BTC","ETH"} else 6,
            "subsample":.85 if name in {"BTC","ETH"} else .75,"confidence_factor":factor,
            "slippage_factor":1.0 if name in {"BTC","ETH"} else 1.5 if name=="MAJOR_ALTCOIN" else 2.5,
            "median_turnover":round(float(turnover),2)}


def _model_factories(profile: dict | None = None) -> tuple[dict[str, Callable[[], object]], dict[str, str]]:
    profile=profile or {"max_depth":8,"min_leaf":3,"subsample":.85}
    factories: dict[str, Callable[[], object]] = {
        "LogisticRegression": lambda: make_pipeline(
            StandardScaler(), LogisticRegression(C=.75, class_weight="balanced", max_iter=1200,
                                                  random_state=42)
        ),
        "RandomForest": lambda: RandomForestClassifier(n_estimators=180, max_depth=profile["max_depth"], min_samples_leaf=profile["min_leaf"],
                                                        class_weight="balanced", random_state=42, n_jobs=1)
    }
    unavailable: dict[str, str] = {
        "LSTM": "disabled: deep model is not justified for the current per-asset sample size",
        "Transformer": "disabled: deep model is not justified for the current per-asset sample size",
    }
    try:
        from xgboost import XGBClassifier
        factories["XGBoost"] = lambda: XGBClassifier(n_estimators=180, max_depth=max(3,profile["max_depth"]-3), learning_rate=.045,
                                                       subsample=profile["subsample"], colsample_bytree=.85, objective="multi:softprob",
                                                       eval_metric="mlogloss", random_state=42, n_jobs=2)
    except Exception as exc:
        unavailable["XGBoost"] = type(exc).__name__
    try:
        from lightgbm import LGBMClassifier
        factories["LightGBM"] = lambda: LGBMClassifier(n_estimators=220, max_depth=profile["max_depth"], num_leaves=31,
                                                         learning_rate=.04, class_weight="balanced", random_state=42,
                                                         n_jobs=2, verbosity=-1)
    except Exception as exc:
        unavailable["LightGBM"] = type(exc).__name__
    try:
        from catboost import CatBoostClassifier
        factories["CatBoost"] = lambda: CatBoostClassifier(iterations=180, depth=max(4, profile["max_depth"]-2),
                                                              learning_rate=.045, loss_function="MultiClass",
                                                              auto_class_weights="Balanced", random_seed=42,
                                                              verbose=False, thread_count=2)
    except Exception as exc:
        unavailable["CatBoost"] = f"optional dependency unavailable: {type(exc).__name__}"
    return factories, unavailable


class _LabelAdapter:
    def __init__(self, estimator): self.estimator = estimator
    def fit(self, x, y): self.estimator.fit(x, np.asarray(y, dtype=int) + 1); return self
    def predict(self, x): return np.asarray(self.estimator.predict(x), dtype=int) - 1
    def predict_proba(self, x):
        raw = self.estimator.predict_proba(x)
        output = np.zeros((len(x), 3), dtype=float)
        for source, cls in enumerate(np.asarray(self.estimator.classes_, dtype=int) - 1):
            output[:, int(cls) + 1] = raw[:, source]
        return output
    @property
    def feature_importances_(self): return getattr(self.estimator, "feature_importances_", np.zeros(len(FEATURES)))


class _PlattCalibrator:
    def __init__(self): self.models: list[LogisticRegression | float] = []
    def fit(self, probabilities: np.ndarray, target: pd.Series):
        labels = np.asarray(target)
        self.models = []
        for index, cls in enumerate(CLASSES):
            binary = (labels == cls).astype(int)
            if np.unique(binary).size < 2:
                self.models.append(float(binary.mean()))
            else:
                model = LogisticRegression(C=1.0, solver="lbfgs", random_state=42)
                model.fit(probabilities[:, [index]], binary)
                self.models.append(model)
        return self
    def transform(self, probabilities: np.ndarray) -> np.ndarray:
        columns = []
        for index, model in enumerate(self.models):
            columns.append(np.full(len(probabilities), model) if isinstance(model, float)
                           else model.predict_proba(probabilities[:, [index]])[:, 1])
        result = np.column_stack(columns)
        return result / np.maximum(result.sum(axis=1, keepdims=True), 1e-12)


def _aligned_dataset(frame: pd.DataFrame, asset_type: str, interval: str, horizon: str):
    indices = target_indices(pd.DatetimeIndex(frame["timestamp_utc"]), asset_type, interval, horizon)
    future = np.full(len(frame), np.nan)
    valid_target = indices >= 0
    current = frame["close"].to_numpy(float)
    future[valid_target] = current[indices[valid_target]] / current[valid_target] - 1
    # Every threshold is calculated from information available strictly before
    # that row. The future return is used only for the label.
    atr_pct = frame["atr"] / frame["close"]
    threshold = (atr_pct.shift(1).rolling(180, min_periods=30).median() * .28).clip(.001, .018)
    target = pd.Series(np.where(future > threshold, 1, np.where(future < -threshold, -1, 0)), index=frame.index)
    valid = frame[FEATURES].notna().all(axis=1) & pd.Series(valid_target, index=frame.index) & threshold.notna()
    meta = pd.DataFrame({"feature_time": frame["timestamp_utc"],
                         "target_time": [pd.NaT if i < 0 else frame["timestamp_utc"].iloc[i] for i in indices],
                         "threshold": threshold, "future_return": future}, index=frame.index)
    return frame.loc[valid, FEATURES], target.loc[valid], meta.loc[valid]


def _probabilities(model, x) -> np.ndarray:
    raw = model.predict_proba(x)
    if raw.shape[1] == 3: return raw
    output = np.zeros((len(x), 3))
    for index, cls in enumerate(model.classes_): output[:, int(cls) + 1] = raw[:, index]
    return output


def _metrics(y_true, probabilities: np.ndarray) -> dict:
    predicted = CLASSES[np.argmax(probabilities, axis=1)]
    one_hot = np.column_stack([(np.asarray(y_true) == cls).astype(float) for cls in CLASSES])
    result = {
        "accuracy": accuracy_score(y_true, predicted),
        "f1_macro": f1_score(y_true, predicted, average="macro", zero_division=0),
        "precision_macro": precision_score(y_true, predicted, average="macro", zero_division=0),
        "recall_macro": recall_score(y_true, predicted, average="macro", zero_division=0),
        "log_loss": log_loss(y_true, probabilities, labels=CLASSES),
        "brier_score": float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))),
    }
    try:
        result["auc_ovr"] = (roc_auc_score(one_hot, probabilities, average="macro", multi_class="ovr")
                             if len(set(np.asarray(y_true).tolist())) == 3 else None)
    except ValueError: result["auc_ovr"] = None
    return {key: None if value is None else round(float(value), 4) for key, value in result.items()}


def _performance_weight(metrics: dict) -> float:
    skill = (metrics["accuracy"] + metrics["f1_macro"]) / 2
    calibration = max(.05, 1 - metrics["brier_score"])
    loss = max(.05, 1 - metrics["log_loss"] / 2.5)
    return max(.01, skill * calibration * loss)


def _regime_labels(x: pd.DataFrame, reference: pd.DataFrame) -> pd.Series:
    vol_cut=float(reference["volatility"].dropna().quantile(.75))
    labels=np.where(x["volatility"]>=vol_cut,"HIGH_VOL",
                    np.where(x["ma20_gap"]>.005,"BULL",np.where(x["ma20_gap"]<-.005,"BEAR","SIDEWAYS")))
    return pd.Series(labels,index=x.index)


def _fit_models(x_train, y_train, x_cal, y_cal, x_validation, y_validation, x_test, y_test, profile=None):
    factories, unavailable = _model_factories(profile)
    fitted = {}; details = {}; test_probabilities = []
    validation_regimes=_regime_labels(x_validation,x_train)
    for name, factory in factories.items():
        estimator = factory()
        model = _LabelAdapter(estimator) if name == "XGBoost" else estimator
        try:
            model.fit(x_train, y_train)
            raw_cal = _probabilities(model, x_cal)
            calibrator = _PlattCalibrator().fit(raw_cal, y_cal)
            calibrated_validation = calibrator.transform(_probabilities(model, x_validation))
            calibrated_test = calibrator.transform(_probabilities(model, x_test))
            validation_metrics = _metrics(y_validation, calibrated_validation)
            test_metrics = _metrics(y_test, calibrated_test)
            # Model selection is based only on the validation interval. The final
            # test interval remains untouched until the ensemble has been fixed.
            weight = _performance_weight(validation_metrics)
            regime_weights={}
            regime_metrics={}
            for regime in ("BULL","BEAR","SIDEWAYS","HIGH_VOL"):
                mask=(validation_regimes==regime).to_numpy()
                if mask.sum()>=20 and pd.Series(np.asarray(y_validation)[mask]).nunique()>=2:
                    subgroup=_metrics(np.asarray(y_validation)[mask],calibrated_validation[mask])
                    regime_metrics[regime]={"samples":int(mask.sum()),**subgroup}
                    regime_weights[regime]=_performance_weight(subgroup)
            fitted[name] = {"model": model, "calibrator": calibrator, "weight": weight,"regime_weights":regime_weights}
            details[name] = {"status": "available", "validation_metrics": validation_metrics,
                             "metrics": test_metrics, "weight": weight, "weight_source": "purged_validation",
                             "regime_validation":regime_metrics,
                             "sample_count": len(x_train),
                             "direction": None, "probabilities": None}
            test_probabilities.append((weight, calibrated_test))
        except Exception as exc:
            unavailable[name] = f"training failed: {type(exc).__name__}"
    if not fitted: raise ValueError("没有可用的模型完成训练")
    total = sum(weight for weight, _ in test_probabilities)
    ensemble_test = sum(weight * values for weight, values in test_probabilities) / total
    return fitted, details, unavailable, ensemble_test


def _baseline_metrics(x_test: pd.DataFrame, y_train: pd.Series, y_test: pd.Series) -> dict:
    majority = int(y_train.value_counts().idxmax())
    majority_pred = np.full(len(y_test), majority)
    random_pred = np.random.default_rng(42).choice(CLASSES, len(y_test))
    technical_pred = np.where((x_test["macd"] > x_test["macd_signal"]) & (x_test["ma20_gap"] > 0), 1,
                              np.where((x_test["macd"] < x_test["macd_signal"]) & (x_test["ma20_gap"] < 0), -1, 0))
    def scores(pred):
        probabilities = np.full((len(pred), 3), .025)
        probabilities[np.arange(len(pred)), np.asarray(pred, dtype=int) + 1] = .95
        return _metrics(y_test, probabilities)
    return {"majority_class": scores(majority_pred), "random": scores(random_pred),
            "technical_strategy": scores(technical_pred),
            "buy_and_hold": {"return": round(float((1 + x_test["return_1"].fillna(0)).prod() - 1), 4)}}


def _purged_train_end(meta: pd.DataFrame, validation_start: int, embargo_rows: int) -> int:
    """Return an exclusive train boundary whose labels end before validation."""
    if validation_start <= 0:
        return 0
    feature_start = pd.Timestamp(meta["feature_time"].iloc[validation_start])
    safe = np.flatnonzero((pd.to_datetime(meta["target_time"].iloc[:validation_start]) < feature_start).to_numpy())
    boundary = int(safe[-1] + 1) if len(safe) else 0
    return max(0, min(boundary, validation_start - max(1, embargo_rows)))


def _purged_slices(meta: pd.DataFrame, fractions=(.56, .70, .84), embargo_rows: int = 1) -> dict:
    n = len(meta)
    cal_start, validation_start, test_start = [int(n * value) for value in fractions]
    train_end = _purged_train_end(meta, cal_start, embargo_rows)
    cal_end = _purged_train_end(meta, validation_start, embargo_rows)
    validation_end = _purged_train_end(meta, test_start, embargo_rows)
    return {"train": (0, train_end), "calibration": (cal_start, cal_end),
            "validation": (validation_start, validation_end), "test": (test_start, n),
            "embargo_rows": embargo_rows}


def _walk_forward(x: pd.DataFrame, y: pd.Series, meta: pd.DataFrame, profile=None) -> tuple[dict, int]:
    factories, _ = _model_factories(profile)
    start = max(100, int(len(x) * .55)); chunk = max(30, int(len(x) * .1))
    predicted: list[int] = []; actual: list[int] = []
    for begin in range(start, len(x), chunk):
        end = min(begin + chunk, len(x)); fold_predictions = []
        train_end = _purged_train_end(meta, begin, 1)
        if train_end < 80:
            continue
        for name, factory in factories.items():
            try:
                model = _LabelAdapter(factory()) if name == "XGBoost" else factory()
                model.fit(x.iloc[:train_end], y.iloc[:train_end])
                fold_predictions.append(_probabilities(model, x.iloc[begin:end]))
            except Exception: continue
        if fold_predictions:
            predicted.extend(CLASSES[np.argmax(np.mean(fold_predictions, axis=0), axis=1)].tolist())
            actual.extend(y.iloc[begin:end].tolist())
    if not actual: return {"accuracy": 0.0, "f1_macro": 0.0}, 0
    return {"accuracy": round(float(accuracy_score(actual, predicted)), 4),
            "f1_macro": round(float(f1_score(actual, predicted, average="macro", zero_division=0)), 4)}, len(actual)


def _quality(frame: pd.DataFrame, asset_type: str, interval: str) -> float:
    feature_complete = float(frame[FEATURES].notna().mean().mean())
    if asset_type == "crypto" and len(frame) > 1:
        differences = pd.DatetimeIndex(frame["timestamp_utc"]).to_series().diff().dropna()
        expected = pd.to_timedelta({"1m":1,"5m":5,"15m":15,"30m":30,"1h":60,"4h":240,"1d":1440}[interval], unit="min")
        time_complete = float((differences <= expected * 1.1).mean())
    else: time_complete = 1.0
    return round(.65 * feature_complete + .35 * time_complete, 4)


def _top_factors(models: dict, latest: pd.DataFrame, history: pd.DataFrame) -> list[dict]:
    importance = np.zeros(len(FEATURES)); total = 0.0
    for item in models.values():
        values = np.asarray(getattr(item["model"], "feature_importances_", np.zeros(len(FEATURES))))
        if len(values) == len(FEATURES): importance += item["weight"] * values; total += item["weight"]
    if total: importance /= total
    median = history[FEATURES].median(); spread = history[FEATURES].std().replace(0, np.nan)
    standardized = ((latest.iloc[0] - median) / spread).fillna(0)
    factors = []
    for index in np.argsort(importance)[::-1][:5]:
        feature = FEATURES[int(index)]; direction = "positive" if standardized[feature] >= 0 else "negative"
        factors.append({"feature": feature, "label": FEATURE_LABELS[feature], "importance": round(float(importance[index]), 4),
                        "direction": direction, "value": round(float(latest.iloc[0][feature]), 6)})
    return factors


def _fingerprint(frame: pd.DataFrame, interval: str, horizon: str, profile: str) -> str:
    latest = pd.Timestamp(frame["timestamp_utc"].iloc[-1])
    refresh = "1h" if interval in {"1m", "5m"} else "4h" if interval != "1d" else "1d"
    training_bucket = latest.floor(refresh)
    value = f"v4.0-purged-regime|{profile}|{interval}|{horizon}|{training_bucket}"
    return hashlib.sha256(value.encode()).hexdigest()


def predict(candles: list[dict], interval: str = "1h", asset_type: str = "crypto", symbol: str = "UNKNOWN") -> dict:
    frame = feature_frame(candles)
    if len(frame) < 180: raise ValueError("历史数据不足，V2 至少需要 180 根 K 线")
    horizons = supported_horizons(interval)
    if not horizons: raise ValueError(f"{interval} 无法严格表达 1H/4H/1D 中的任一目标")
    availability = FeatureStore().availability(frame, asset_type)
    asset_profile = _asset_profile(asset_type, symbol, frame)
    data_completeness = _quality(frame, asset_type, interval)
    latest = frame[FEATURES].dropna().iloc[[-1]]
    manager = ModelManager()
    predictions = {}; all_models = set(); any_retrained = False
    for horizon in horizons:
        nominal_steps = horizon_bar_count(asset_type, interval, horizon)
        x, y, alignment = _aligned_dataset(frame, asset_type, interval, horizon)
        if len(x) < 120 or y.nunique() < 2:
            predictions[horizon] = {"status": "INSUFFICIENT_DATA", "sample_count": len(x),
                                    "message": "训练样本不足或标签只有单一方向"}
            continue
        fingerprint = _fingerprint(frame, interval, horizon, asset_profile["name"])
        artifact = manager.load(symbol, interval, horizon, fingerprint)
        if artifact is None:
            slices = _purged_slices(alignment, embargo_rows=max(1, nominal_steps))
            tr0,tr1=slices["train"]; ca0,ca1=slices["calibration"]
            va0,va1=slices["validation"]; te0,te1=slices["test"]
            if min(tr1-tr0,ca1-ca0,va1-va0,te1-te0) < 20:
                predictions[horizon] = {"status":"INSUFFICIENT_DATA","sample_count":len(x),
                                        "message":"Purge/Embargo 后有效训练或验证样本不足"}
                continue
            fitted, details, unavailable, ensemble_test = _fit_models(
                x.iloc[tr0:tr1], y.iloc[tr0:tr1], x.iloc[ca0:ca1], y.iloc[ca0:ca1],
                x.iloc[va0:va1], y.iloc[va0:va1], x.iloc[te0:te1], y.iloc[te0:te1], asset_profile)
            ensemble_metrics = _metrics(y.iloc[te0:te1], ensemble_test)
            walk_metrics, walk_samples = _walk_forward(x, y, alignment, asset_profile)
            baselines = _baseline_metrics(x.iloc[te0:te1], y.iloc[tr0:tr1], y.iloc[te0:te1])
            candidate = {"fingerprint": fingerprint, "version": "4.0", "models": fitted, "model_details": details,
                        "unavailable_models": unavailable, "ensemble_metrics": ensemble_metrics,
                        "walk_forward_metrics": walk_metrics, "walk_forward_samples": walk_samples,
                        "baselines": baselines, "sample_count": len(x), "validation_scheme": {
                            "name":"purged_embargo_train_calibration_validation_test", "slices":slices,
                            "leakage_check": bool(pd.Timestamp(alignment["target_time"].iloc[tr1-1]) < pd.Timestamp(alignment["feature_time"].iloc[ca0])
                                                   and pd.Timestamp(alignment["target_time"].iloc[ca1-1]) < pd.Timestamp(alignment["feature_time"].iloc[va0])
                                                   and pd.Timestamp(alignment["target_time"].iloc[va1-1]) < pd.Timestamp(alignment["feature_time"].iloc[te0]))},
                        "trained_at": datetime.now(timezone.utc).isoformat()}
            artifact,promotion=manager.promote_if_better(symbol,interval,horizon,candidate)
            artifact["promotion_decision"]=promotion
            any_retrained = True
        model_probabilities = []; directions = []
        current_regime=str(_regime_labels(latest,x).iloc[0])
        for name, item in artifact["models"].items():
            calibrated = item["calibrator"].transform(_probabilities(item["model"], latest))[0]
            direction = int(CLASSES[np.argmax(calibrated)]); directions.append(direction); all_models.add(name)
            artifact["model_details"][name]["direction"] = {-1:"DOWN",0:"FLAT",1:"UP"}[direction]
            artifact["model_details"][name]["probabilities"] = {"down":round(float(calibrated[0]),4),
                                                                  "flat":round(float(calibrated[1]),4),
                                                                  "up":round(float(calibrated[2]),4)}
            selected_weight=item.get("regime_weights",{}).get(current_regime,item["weight"])
            artifact["model_details"][name]["selected_weight"]=selected_weight
            artifact["model_details"][name]["selected_for_regime"]=current_regime if current_regime in item.get("regime_weights",{}) else "GLOBAL_FALLBACK"
            model_probabilities.append((selected_weight, calibrated))
        total_weight = sum(weight for weight, _ in model_probabilities)
        probabilities = sum(weight * values for weight, values in model_probabilities) / total_weight
        consensus = max(directions.count(value) for value in set(directions)) / len(directions)
        baseline_accuracy = max(artifact["baselines"]["majority_class"]["accuracy"], artifact["baselines"]["random"]["accuracy"],
                                artifact["baselines"]["technical_strategy"]["accuracy"])
        advantage = artifact["ensemble_metrics"]["accuracy"] - baseline_accuracy
        sample_score = min(1.0, len(x) / 5000)
        calibration_score = max(0.0, 1 - artifact["ensemble_metrics"]["brier_score"])
        confidence_score = round(100 * (.25*artifact["walk_forward_metrics"]["accuracy"] + .15*sample_score +
                                        .2*data_completeness + .15*availability["feature_coverage"] +
                                        .15*consensus + .1*calibration_score) * asset_profile["confidence_factor"])
        confidence = "A" if confidence_score >= 85 else "B" if confidence_score >= 70 else "C" if confidence_score >= 55 else "D"
        predicted_class = int(CLASSES[np.argmax(probabilities)])
        target = future_timestamp(frame["timestamp_utc"].iloc[-1], asset_type, interval, horizon)
        predictions[horizon] = {
            "status": availability["data_status"], "horizon": horizon, "target_duration": horizon,
            "bar_interval": interval, "nominal_bar_count": nominal_steps, "prediction_time": frame["timestamp_utc"].iloc[-1].isoformat(),
            "future_timestamp": target.isoformat(), "prediction": {-1:"DOWN",0:"FLAT",1:"UP"}[predicted_class],
            "trend": {-1:"偏空",0:"震荡",1:"偏多"}[predicted_class],
            "probabilities": {"down":round(float(probabilities[0]),4), "flat":round(float(probabilities[1]),4), "up":round(float(probabilities[2]),4)},
            "prob_down":round(float(probabilities[0]*100),2), "prob_flat":round(float(probabilities[1]*100),2), "prob_up":round(float(probabilities[2]*100),2),
            "probability_type":"calibrated_model_probability", "confidence":confidence, "confidence_score":confidence_score,
            "sample_count":len(x), "data_completeness":data_completeness, "model_consensus":round(consensus,4),
            "consensus_label":"高" if consensus>=.8 else "中" if consensus>=.6 else "低", "models":list(artifact["models"]),
            "model_details":artifact["model_details"], "unavailable_models":artifact["unavailable_models"],
            "model_selector":{"current_regime":current_regime,"method":"validation-derived regime weight with global fallback",
                              "minimum_regime_samples":20},
            "model_metrics":artifact["ensemble_metrics"], "walk_forward":{**artifact["walk_forward_metrics"],"samples":artifact["walk_forward_samples"]},
            "validation_scheme":artifact.get("validation_scheme", {"name":"legacy_artifact","leakage_check":False}),
            "walk_forward_accuracy":round(artifact["walk_forward_metrics"]["accuracy"]*100,2), "walk_forward_samples":artifact["walk_forward_samples"],
            "baselines":artifact["baselines"], "model_advantage":round(advantage,4),
            "advantage_message":"模型显示样本外优势" if advantage>=.03 else "当前模型暂无明显优势",
            "features":availability["features"], "feature_status":availability["feature_status"],
            "feature_coverage":availability["feature_coverage"], "top_factors":_top_factors(artifact["models"], latest, x),
            "explanation_method":"validation-weighted tree feature importance", "shap_status":"NOT_AVAILABLE",
            "threshold_percent":round(float(alignment["threshold"].iloc[-1])*100,3), "trained_at":artifact["trained_at"],
            "promotion_decision":artifact.get("promotion_decision","LOADED_CURRENT_MODEL"),
        }
    if not any(item.get("prediction") for item in predictions.values()): raise ValueError("所有严格时间目标的样本均不足")
    return {"engine_version":"4.0", "model":{"name":"PerformanceWeightedEnsemble","models":sorted(all_models),
             "asset_profile":asset_profile,
             "training_status":"retrained" if any_retrained else "loaded_from_disk", "split":"Purged Train / Calibration / Validation / untouched Test + horizon embargo",
             "walk_forward":True, "purged_cv":True, "embargo":True}, "predictions":predictions, "feature_availability":availability,
            "data_time":frame["timestamp_utc"].iloc[-1].isoformat(), "predicted_at":datetime.now(timezone.utc).isoformat(),
            "risk_notice":"这是经校准的模型概率，不是现实世界保证，不构成投资建议。"}


def out_of_sample_probabilities(candles: list[dict], interval: str = "1h", asset_type: str = "crypto") -> tuple[pd.DataFrame, pd.Series]:
    frame = feature_frame(candles); horizons=supported_horizons(interval)
    horizon="1H" if "1H" in horizons else next(iter(horizons))
    x,y,meta=_aligned_dataset(frame,asset_type,interval,horizon);prob=pd.Series(index=frame.index,dtype=float)
    start=max(100,int(len(x)*.55));chunk=max(30,int(len(x)*.1))
    for begin in range(start,len(x),chunk):
        end=min(begin+chunk,len(x));train_end=_purged_train_end(meta,begin,1)
        if train_end<80: continue
        profile=_asset_profile(asset_type,"UNKNOWN",frame);model=RandomForestClassifier(n_estimators=120,max_depth=profile["max_depth"],min_samples_leaf=profile["min_leaf"],class_weight="balanced",random_state=42,n_jobs=1)
        model.fit(x.iloc[:train_end],y.iloc[:train_end]);raw=_probabilities(model,x.iloc[begin:end]);prob.loc[x.index[begin:end]]=raw[:,2]
    return frame,prob
