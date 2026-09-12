"""Lightweight, auditable quant research workflow inspired by Qlib's separation
of data, features, models, records and evaluation.  It does not bundle Qlib and
does not claim Qlib benchmark performance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from .ai_engine import (CLASSES, FEATURE_GROUPS, FEATURES, _LabelAdapter,
                        _PlattCalibrator, _aligned_dataset, _asset_profile,
                        _model_factories, _probabilities, _purged_train_end,
                        feature_frame)


def feature_catalog(candles: list[dict], source: str, version: str = "quant-v2.0") -> dict:
    frame=feature_frame(candles); latest=frame.iloc[-1]; stamp=pd.Timestamp(frame["timestamp_utc"].iloc[-1]).isoformat()
    records=[]
    for group,names in FEATURE_GROUPS.items():
        for name in names:
            value=latest.get(name)
            records.append({"name":name,"group":group,"value":None if pd.isna(value) else round(float(value),8),
                            "timestamp":stamp,"source":source,"lookback":_lookback(name),"version":version})
    return {"version":version,"timestamp":stamp,"information_cutoff":stamp,"feature_count":len(records),
            "groups":{key:len(value) for key,value in FEATURE_GROUPS.items()},"features":records,
            "leakage_policy":"Each row uses current/past OHLCV only; labels and future news are excluded."}


def _lookback(name: str) -> int:
    for token in ("200","120","100","60","50","20","14","12","10","5","3","1"):
        if token in name:return int(token)
    return 20


def _correlation(a: np.ndarray,b: np.ndarray) -> float | None:
    mask=np.isfinite(a)&np.isfinite(b)
    if mask.sum()<3 or np.std(a[mask])==0 or np.std(b[mask])==0:return None
    return round(float(np.corrcoef(a[mask],b[mask])[0,1]),4)


def _rank_correlation(a: np.ndarray,b: np.ndarray) -> float | None:
    return _correlation(pd.Series(a).rank().to_numpy(),pd.Series(b).rank().to_numpy())


def _research_metrics(y: pd.Series, probabilities: np.ndarray, future_returns: np.ndarray,
                      cost_rate: float, periods_per_year: int, holding_bars: int=1) -> dict:
    actual=np.asarray(y,int); pred=CLASSES[np.argmax(probabilities,axis=1)]
    one_hot=np.column_stack([(actual==cls).astype(float) for cls in CLASSES])
    confidence=probabilities.max(axis=1); signal=probabilities[:,2]-probabilities[:,0]
    brier=float(np.mean(np.sum((probabilities-one_hot)**2,axis=1)))
    clipped=np.clip(probabilities,1e-12,1); logloss=float(-np.mean(np.log(clipped[np.arange(len(actual)),actual+1])))
    # Multi-bar labels overlap. Classification and IC use every OOS row, while
    # portfolio metrics use non-overlapping entry windows to prevent impossible
    # simultaneous reuse of capital and inflated compounded returns.
    trade_index=np.arange(0,len(actual),max(1,holding_bars));trade_signal=signal[trade_index]
    trade_confidence=confidence[trade_index];trade_returns=future_returns[trade_index]
    positions=np.where((trade_confidence>=.45)&(np.abs(trade_signal)>=.08),np.sign(trade_signal),0)
    turnover=np.abs(np.diff(np.r_[0,positions])); net=positions*trade_returns-turnover*cost_rate
    equity=np.cumprod(1+np.nan_to_num(net)); peak=np.maximum.accumulate(equity); drawdown=equity/np.maximum(peak,1e-12)-1
    std=float(np.std(net,ddof=1)) if len(net)>1 else 0; downside=net[net<0]
    effective_periods=periods_per_year/max(1,holding_bars)
    sharpe=float(np.sqrt(effective_periods)*np.mean(net)/std) if std>0 else None
    dstd=float(np.std(downside,ddof=1)) if len(downside)>1 else 0
    sortino=float(np.sqrt(effective_periods)*np.mean(net)/dstd) if dstd>0 else None
    total=float(equity[-1]-1) if len(equity) else 0; max_dd=float(drawdown.min()) if len(drawdown) else 0
    years=max(len(net)/effective_periods,1/effective_periods); annual=(1+total)**(1/years)-1 if total>-1 else -1
    gains=net[net>0].sum(); losses=abs(net[net<0].sum())
    return {"samples":len(actual),"strategy_samples":len(net),"directional_accuracy":round(float(np.mean(pred==actual)),4),
            "brier":round(brier,4),"log_loss":round(logloss,4),"ic":_correlation(signal,future_returns),
            "rank_ic":_rank_correlation(signal,future_returns),"sharpe":None if sharpe is None else round(sharpe,4),
            "sortino":None if sortino is None else round(sortino,4),"maximum_drawdown":round(max_dd,4),
            "calmar":round(annual/abs(max_dd),4) if max_dd<0 else None,"net_return":round(total,4),
            "turnover":round(float(turnover.sum()),4),"transaction_cost":round(float((turnover*cost_rate).sum()),4),
            "profit_factor":round(float(gains/losses),4) if losses else None}


def _fit_one(factory, name: str, x_train, y_train, x_cal, y_cal, x_test) -> np.ndarray:
    model=_LabelAdapter(factory()) if name=="XGBoost" else factory();model.fit(x_train,y_train)
    calibrator=_PlattCalibrator().fit(_probabilities(model,x_cal),y_cal)
    return calibrator.transform(_probabilities(model,x_test))


def benchmark(candles: list[dict], asset_type: str, symbol: str, interval: str = "1d",
              horizon: str | None = None, folds: int = 3) -> dict:
    frame=feature_frame(candles); available=__import__("backend.horizons",fromlist=["supported_horizons"]).supported_horizons(interval)
    if asset_type=="stock":available.pop("7D",None)
    else: available={k:v for k,v in available.items() if k not in {"T+5","T+20"}}
    horizon=horizon or ("1D" if "1D" in available else next(iter(available)))
    if horizon not in available:raise ValueError(f"{asset_type}/{interval} 不支持 {horizon}")
    x,y,meta=_aligned_dataset(frame,asset_type,interval,horizon)
    if len(x)<180 or y.nunique()<2:raise ValueError("样本不足，至少需要180条完整特征且标签需包含两个方向")
    profile=_asset_profile(asset_type,symbol,frame);factories,unavailable=_model_factories({**profile,"research_mode":True})
    test_start=max(120,int(len(x)*.62)); chunk=max(20,(len(x)-test_start)//max(1,folds))
    outputs:dict[str,list[np.ndarray]]={name:[] for name in factories}; actual=[]; returns=[]; oos_indices=[]; fold_rows=[]
    for begin in range(test_start,len(x),chunk):
        end=min(len(x),begin+chunk); train_end=_purged_train_end(meta,begin,max(1,available[horizon]))
        cal_size=max(30,int(train_end*.18)); fit_end=train_end-cal_size
        if fit_end<80 or train_end-fit_end<20:continue
        fold={"train":[str(meta["feature_time"].iloc[0]),str(meta["feature_time"].iloc[fit_end-1])],
              "calibration":[str(meta["feature_time"].iloc[fit_end]),str(meta["feature_time"].iloc[train_end-1])],
              "test":[str(meta["feature_time"].iloc[begin]),str(meta["feature_time"].iloc[end-1])],"samples":end-begin}
        for name,factory in factories.items():
            try:outputs[name].append(_fit_one(factory,name,x.iloc[:fit_end],y.iloc[:fit_end],x.iloc[fit_end:train_end],y.iloc[fit_end:train_end],x.iloc[begin:end]))
            except Exception as exc:unavailable[name]=f"training failed: {type(exc).__name__}";outputs[name]=[]
        actual.extend(y.iloc[begin:end]);returns.extend(meta["future_return"].iloc[begin:end]);oos_indices.extend(x.index[begin:end]);fold_rows.append(fold)
    y_oos=pd.Series(actual); future=np.asarray(returns,float)
    if not len(y_oos):raise ValueError("Purged walk-forward 后没有可评估样本")
    cost={"CN_EQUITY":.0015,"US_EQUITY":.001,"BTC":.001,"ETH":.001,"MAJOR_ALTCOIN":.0015,"LOW_LIQUIDITY_TOKEN":.0025}.get(profile["name"],.0015)
    annual=365 if asset_type=="crypto" else 252; rows={}; valid=[]
    for name,parts in outputs.items():
        if not parts:continue
        probs=np.vstack(parts); metrics=_research_metrics(y_oos,probs,future,cost,annual,available[horizon])
        fold_ics=[];offset=0
        for part,fold in zip(parts,fold_rows):
            size=fold["samples"];value=_correlation(part[:,2]-part[:,0],future[offset:offset+size]);offset+=size
            if value is not None:fold_ics.append(value)
        metrics["icir"]=(round(float(np.mean(fold_ics)/np.std(fold_ics,ddof=1)),4)
                         if len(fold_ics)>1 and np.std(fold_ics,ddof=1)>0 else None)
        rows[name]={"status":"EXPERIMENTAL","metrics":metrics};valid.append((name,probs,metrics))
    majority=int(y.iloc[:test_start].value_counts().idxmax()); base=np.full((len(y_oos),3),.025);base[:,majority+1]=.95
    rows["MajorityBaseline"]={"status":"BASELINE","metrics":_research_metrics(y_oos,base,future,cost,annual,available[horizon])}
    price=frame.loc[oos_indices,"close"].to_numpy(float);daily=np.diff(price)/price[:-1]
    eq=np.cumprod(1+daily);peak=np.maximum.accumulate(eq);dd=eq/np.maximum(peak,1e-12)-1
    buy_return=float(price[-1]/price[0]-1) if len(price)>1 else 0;std=float(daily.std(ddof=1)) if len(daily)>1 else 0
    rows["BuyAndHold"]={"status":"BASELINE","metrics":{"samples":len(price),"net_return":round(buy_return,4),
        "sharpe":round(float(np.sqrt(annual)*daily.mean()/std),4) if std>0 else None,
        "maximum_drawdown":round(float(dd.min()),4) if len(dd) else 0,"transaction_cost":0,"turnover":0}}
    if valid:
        # Weights are derived from OOS fold quality, clipped at zero; this aggregate is
        # reported as research only because the same folds estimate its weights.
        weights=np.asarray([max(.001,(1-v[2]["brier"])*max(0,v[2]["directional_accuracy"]-rows["MajorityBaseline"]["metrics"]["directional_accuracy"]+.05)) for v in valid])
        ensemble=sum(w*v[1] for w,v in zip(weights,valid))/weights.sum(); em=_research_metrics(y_oos,ensemble,future,cost,annual,available[horizon])
        rows["ValidationWeightedEnsemble"]={"status":"EXPERIMENTAL","metrics":em,"weights":{v[0]:round(float(w/weights.sum()),4) for w,v in zip(weights,valid)}}
    best=min((name for name in rows if name not in {"MajorityBaseline","BuyAndHold"}),key=lambda n:rows[n]["metrics"]["brier"],default=None)
    baseline=rows["MajorityBaseline"]["metrics"];best_metrics=rows[best]["metrics"] if best else None
    candidate=bool(best_metrics and len(fold_rows)>=3 and best_metrics["samples"]>=100 and best_metrics["directional_accuracy"]>=baseline["directional_accuracy"]+.03 and (best_metrics["ic"] or 0)>.02 and best_metrics["brier"]<baseline["brier"])
    return {"engine":"Quant Intelligence Engine V2","symbol":symbol,"asset_type":asset_type,"profile":profile["name"],
            "interval":interval,"horizon":horizon,"generated_at":datetime.now(timezone.utc).isoformat(),"information_cutoff":str(frame["timestamp_utc"].iloc[-1]),
            "validation":{"method":"expanding purged walk-forward with separate calibration tail","folds":fold_rows,"leakage_check":True,"random_split":False},
            "models":rows,"unavailable_models":{**unavailable,"NewsOnly":"point-in-time historical news matrix insufficient",
                "TechnicalPlusNews":"point-in-time historical news matrix insufficient"},"best_model":best,
            "decision":"VALIDATED_CANDIDATE_REQUIRES_SHADOW" if candidate else "NO_EDGE","production_model":None,"cost_rate":cost,
            "notes":["News/event/fundamental features excluded: no sufficient point-in-time historical matrix.",
                     "Deep models remain experimental/unavailable until identical OOS data and sample requirements are met."]}


def ablation(candles: list[dict], asset_type: str, symbol: str, interval: str="1d", horizon: str="1D") -> dict:
    frame=feature_frame(candles);x,y,meta=_aligned_dataset(frame,asset_type,interval,horizon)
    variants={"Technical only":FEATURE_GROUPS["technical"],"Technical + Volume":FEATURE_GROUPS["technical"]+FEATURE_GROUPS["volume"],
              "Technical + Volume + Price":FEATURE_GROUPS["technical"]+FEATURE_GROUPS["volume"]+FEATURE_GROUPS["price"],
              "Full observed":FEATURES}
    begin=int(len(x)*.8);train_end=_purged_train_end(meta,begin,1);cal=max(30,int(train_end*.18));fit=train_end-cal;results={}
    factory=_model_factories(_asset_profile(asset_type,symbol,frame))[0]["LogisticRegression"]
    for name,cols in variants.items():
        probs=_fit_one(factory,"LogisticRegression",x[cols].iloc[:fit],y.iloc[:fit],x[cols].iloc[fit:train_end],y.iloc[fit:train_end],x[cols].iloc[begin:])
        results[name]=_research_metrics(y.iloc[begin:],probs,meta["future_return"].iloc[begin:].to_numpy(float),.0015,365 if asset_type=="crypto" else 252)
    return {"symbol":symbol,"horizon":horizon,"method":"same chronological holdout and Logistic baseline","results":results,
            "news":"NOT_TESTED_POINT_IN_TIME_DATA_INSUFFICIENT","event":"NOT_TESTED_POINT_IN_TIME_DATA_INSUFFICIENT","regime":"included only in Full observed"}
