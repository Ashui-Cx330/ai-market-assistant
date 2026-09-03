from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score

from .indicators import calculate_indicators

FEATURES = ["return_1", "return_3", "return_5", "rsi", "macd", "macd_signal", "atr", "volume_change",
            "volatility", "ma5_gap", "ma20_gap", "boll_position"]


def feature_frame(candles: list[dict]) -> pd.DataFrame:
    df = calculate_indicators(candles)
    df["ma5_gap"] = df["close"] / df["ma5"] - 1
    df["ma20_gap"] = df["close"] / df["ma20"] - 1
    df["boll_position"] = (df["close"] - df["boll_lower"]) / (df["boll_upper"] - df["boll_lower"]).replace(0, np.nan)
    return df.replace([np.inf, -np.inf], np.nan)


def _model() -> RandomForestClassifier:
    return RandomForestClassifier(n_estimators=140, max_depth=7, min_samples_leaf=3, class_weight="balanced",
                                  random_state=42, n_jobs=-1)


def _dataset(df: pd.DataFrame, steps: int) -> tuple[pd.DataFrame, pd.Series, float]:
    future_return = df["close"].shift(-steps) / df["close"] - 1
    atr_pct = (df["atr"] / df["close"]).dropna()
    threshold = float(max(0.001, min(0.012, atr_pct.median() * 0.22 if len(atr_pct) else 0.002)))
    target = pd.Series(np.where(future_return > threshold, 1, np.where(future_return < -threshold, -1, 0)), index=df.index)
    valid = df[FEATURES].notna().all(axis=1) & future_return.notna()
    return df.loc[valid, FEATURES], target.loc[valid], threshold


def _probabilities(model: RandomForestClassifier, row: pd.DataFrame) -> dict:
    raw = model.predict_proba(row)[0]
    mapped = {-1: 0.0, 0: 0.0, 1: 0.0}
    for cls, probability in zip(model.classes_, raw): mapped[int(cls)] = float(probability)
    total = sum(mapped.values()) or 1
    return {"up": round(mapped[1] / total * 100, 2), "flat": round(mapped[0] / total * 100, 2),
            "down": round(mapped[-1] / total * 100, 2)}


def _walk_forward_accuracy(x: pd.DataFrame, y: pd.Series) -> tuple[float, int]:
    start = max(80, int(len(x) * 0.6)); chunk = max(15, int(len(x) * 0.1)); predicted=[]; actual=[]
    for begin in range(start, len(x), chunk):
        end=min(begin+chunk,len(x))
        train_y=y.iloc[:begin]
        if train_y.nunique()<2:continue
        model=_model();model.fit(x.iloc[:begin],train_y)
        predicted.extend(model.predict(x.iloc[begin:end]).tolist());actual.extend(y.iloc[begin:end].tolist())
    return (round(accuracy_score(actual,predicted)*100,2),len(actual)) if actual else (0.0,0)


def predict(candles: list[dict], interval: str = "1h") -> dict:
    df=feature_frame(candles)
    if len(df)<120:raise ValueError("历史数据不足，至少需要 120 根 K线")
    horizon_steps={"1h":1,"4h":4,"1d":24} if interval in {"1m","5m","15m","30m","1h"} else {"1h":1,"4h":1,"1d":1}
    results={}; status_samples=0; latest_accuracy=0.0
    latest_features=df[FEATURES].iloc[[-1]]
    if latest_features.isna().any(axis=None):
        latest_features=df[FEATURES].dropna().iloc[[-1]]
    for horizon,steps in horizon_steps.items():
        x,y,threshold=_dataset(df,steps)
        if len(x)<80 or y.nunique()<2:raise ValueError(f"{horizon} 可用训练样本不足或只有单一方向")
        train_end=int(len(x)*.70);val_end=int(len(x)*.85)
        model=_model();model.fit(x.iloc[:train_end],y.iloc[:train_end])
        validation_accuracy=accuracy_score(y.iloc[train_end:val_end],model.predict(x.iloc[train_end:val_end]))*100 if val_end>train_end else 0
        test_accuracy=accuracy_score(y.iloc[val_end:],model.predict(x.iloc[val_end:]))*100 if len(x)>val_end else 0
        walk_accuracy,walk_samples=_walk_forward_accuracy(x,y)
        final_model=_model();final_model.fit(x,y)
        probabilities=_probabilities(final_model,latest_features)
        trend=max(probabilities,key=probabilities.get)
        results[horizon]={"prob_up":probabilities["up"],"prob_flat":probabilities["flat"],"prob_down":probabilities["down"],
                          "trend":{"up":"偏多","flat":"震荡","down":"偏空"}[trend],"threshold_percent":round(threshold*100,3),
                          "validation_accuracy":round(validation_accuracy,2),"test_accuracy":round(test_accuracy,2),
                          "walk_forward_accuracy":walk_accuracy,"test_samples":len(x)-val_end,"walk_forward_samples":walk_samples}
        status_samples=max(status_samples,len(x));latest_accuracy=results[horizon]["walk_forward_accuracy"]
    return {"model":{"name":"RandomForestClassifier","training_status":"已训练","training_samples":status_samples,
                     "split":"时间顺序 70% Train / 15% Validation / 15% Test；禁止随机打乱",
                     "walk_forward":True,"historical_accuracy":latest_accuracy,"trained_at":datetime.now(timezone.utc).isoformat()},
            "predictions":results,"predicted_at":datetime.now(timezone.utc).isoformat(),"data_time":candles[-1]["timestamp"],
            "risk_notice":"概率来自历史数据训练与样本外检验，不代表未来必然走势。"}


def out_of_sample_probabilities(candles: list[dict]) -> tuple[pd.DataFrame, pd.Series]:
    df=feature_frame(candles);x,y,_=_dataset(df,1);prob=pd.Series(index=df.index,dtype=float)
    start=max(80,int(len(x)*.55));chunk=max(15,int(len(x)*.08))
    for begin in range(start,len(x),chunk):
        end=min(begin+chunk,len(x));train_y=y.iloc[:begin]
        if train_y.nunique()<2:continue
        model=_model();model.fit(x.iloc[:begin],train_y);raw=model.predict_proba(x.iloc[begin:end])
        idx=list(model.classes_).index(1) if 1 in model.classes_ else None
        prob.loc[x.index[begin:end]]=raw[:,idx] if idx is not None else 0.0
    return df,prob

