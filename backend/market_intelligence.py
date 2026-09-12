"""Point-in-time, auditable market-intelligence views.

This module intentionally keeps calibrated price-model probabilities separate
from unvalidated news context.  News can explain and trigger a re-evaluation,
but is not silently blended into P(UP) until an ablation proves incremental
out-of-sample value.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone

import numpy as np

from .database import (connection, load_news_intelligence,
                       market_intelligence_snapshots,
                       save_market_intelligence_snapshot)
from .news_intelligence import SOURCE_REGISTRY


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _display_horizon(asset_type: str, horizon: str) -> str:
    if asset_type == "stock": return {"1D":"T+1"}.get(horizon,horizon)
    return {"1D":"24H"}.get(horizon,horizon)


def _level(score: float | None, samples: int = 0) -> tuple[str,str]:
    if score is None:return "D","Insufficient Evidence"
    if samples >= 250 and score >= 70:return "A","Strong"
    if samples >= 120 and score >= 55:return "B","Moderate"
    return "C","Weak / Experimental"


def _prediction_rows(symbol: str, asset_type: str, limit: int = 3000) -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute("""SELECT * FROM prediction_history
            WHERE symbol=? AND asset_type=? ORDER BY prediction_time DESC,id DESC LIMIT ?""",
            (symbol,asset_type,limit)).fetchall()]


def _track_metrics(rows: list[dict]) -> dict:
    resolved=[x for x in rows if x.get("actual")]
    if not resolved:return {"status":"INSUFFICIENT_EVIDENCE","samples":0,"minimum_samples":30,
                            "notice":"尚无已到期的不可变预测记录，不能报告准确率。"}
    labels={"DOWN":0,"FLAT":1,"UP":2};y=np.array([labels[x["actual"]] for x in resolved]);pred=np.array([labels[x["prediction"]] for x in resolved])
    probs=np.array([[x["prob_down"],x["prob_flat"],x["prob_up"]] for x in resolved],dtype=float)
    one=np.eye(3)[y];accuracy=float((pred==y).mean());brier=float(np.mean(np.sum((probs-one)**2,axis=1)))
    loss=float(-np.mean(np.log(np.clip(probs[np.arange(len(y)),y],1e-12,1))));majority=max(Counter(y).values())/len(y)
    precision=[];recall=[];f1=[]
    for cls in range(3):
        tp=((pred==cls)&(y==cls)).sum();fp=((pred==cls)&(y!=cls)).sum();fn=((pred!=cls)&(y==cls)).sum()
        p=tp/max(tp+fp,1);r=tp/max(tp+fn,1);precision.append(p);recall.append(r);f1.append(2*p*r/max(p+r,1e-12))
    status="USEFUL" if len(resolved)>=30 and accuracy-majority>=.03 else "NO_EDGE" if len(resolved)>=30 else "INSUFFICIENT_EVIDENCE"
    return {"status":status,"samples":len(resolved),"minimum_samples":30,
            "accuracy":round(accuracy,4),"directional_accuracy":round(accuracy,4),"precision_macro":round(float(np.mean(precision)),4),
            "recall_macro":round(float(np.mean(recall)),4),"f1_macro":round(float(np.mean(f1)),4),"brier_score":round(brier,4),
            "log_loss":round(loss,4),"baseline":round(majority,4),"edge":round(accuracy-majority,4),
            "notice":"不足30个已结算样本时仅作审计展示，不认定统计优势。" if len(resolved)<30 else "基于本机不可变已结算预测。"}


def _similar_events(symbol: str, news: list[dict], minimum: int = 10) -> dict:
    kinds=[x.get("event",{}).get("event_type") for x in news if x.get("event",{}).get("event_type")]
    dominant=Counter(kinds).most_common(1)[0][0] if kinds else None
    if not dominant:return {"status":"INSUFFICIENT_EVIDENCE","event_type":None,"samples":0,"minimum_samples":minimum}
    with connection() as conn:
        rows=[dict(x) for x in conn.execute("""SELECT h.* FROM historical_events h
            JOIN news_events e ON e.news_id=h.news_id WHERE h.symbol=? AND e.event_type=?""",(symbol,dominant)).fetchall()]
    result={"status":"AVAILABLE" if len(rows)>=minimum else "INSUFFICIENT_EVIDENCE","event_type":dominant,"samples":len(rows),"minimum_samples":minimum,"periods":{}}
    if len(rows)>=minimum:
        for key,label in (("t1_return","T+1"),("t5_return","T+5"),("t20_return","T+20")):
            values=[float(x[key]) for x in rows if x.get(key) is not None]
            if values:
                result["periods"][label]={"up":round(sum(v>.002 for v in values)/len(values)*100,1),"sideways":round(sum(abs(v)<=.002 for v in values)/len(values)*100,1),"down":round(sum(v<-.002 for v in values)/len(values)*100,1),"samples":len(values)}
    else:result["notice"]="历史相似事件样本不足，不显示胜率。"
    return result


def _news_snapshot(symbol: str, cutoff: str | None = None) -> list[dict]:
    rows=load_news_intelligence(symbol,100)
    if cutoff:rows=[x for x in rows if not x.get("published_at") or x["published_at"]<=cutoff]
    return rows[:30]


def build_snapshot_from_prediction(symbol: str, asset_type: str, prediction: dict,
                                   trigger_reason: str = "manual") -> dict:
    """Create and append a snapshot from a completed genuine model run."""
    decision=prediction.get("decision_center",{});data_cutoff=prediction.get("data_time") or prediction.get("predicted_at") or _now()
    periods=[];live_track=_track_metrics(_prediction_rows(symbol,asset_type))
    for horizon,item in prediction.get("predictions",{}).items():
        if not item.get("prediction"):continue
        probs=item["probabilities"];grade,label=_level(item.get("confidence_score"),int(item.get("walk_forward_samples") or 0))
        periods.append({"horizon":_display_horizon(asset_type,horizon),"raw_horizon":horizon,"direction":item["prediction"],"trend":item.get("trend"),
          "up":round(probs["up"]*100,1),"sideways":round(probs["flat"]*100,1),"down":round(probs["down"]*100,1),"confidence":label,"evidence":grade,
          "samples":item.get("sample_count"),"walk_forward_samples":item.get("walk_forward_samples"),"model_advantage":item.get("model_advantage"),
          "model_level":"Useful" if item.get("validation_scheme",{}).get("leakage_check") and item.get("model_advantage",0)>=.03 and live_track.get("status")=="USEFUL" else "Experimental",
          "probability_type":item.get("probability_type"),"target_time":item.get("future_timestamp")})
    technical=decision.get("technical_strategy",{});confluence=technical.get("confluence",{});regime=technical.get("market_regime") or decision.get("market_regime",{})
    top=[]
    for item in prediction.get("predictions",{}).values():
        if item.get("top_factors"):
            top=item["top_factors"];break
    contributions=[]
    for factor in top:
        sign=1 if factor.get("direction")=="positive" else -1
        contributions.append({"factor":factor.get("label") or factor.get("feature"),"contribution":round(sign*float(factor.get("importance",0))*100,1),"source":"calibrated price model feature importance"})
    news=_news_snapshot(symbol,data_cutoff);news_score=round(sum(float(x.get("sentiment",{}).get("score") or 0)*float(x.get("impact",{}).get("score") or 0)/100 for x in news)/max(len(news),1),1)
    snapshot={"symbol":symbol,"asset_type":asset_type,"status":"AVAILABLE" if periods else "INSUFFICIENT_EVIDENCE","generated_at":_now(),"updated_at":_now(),
      "data_cutoff":data_cutoff,"trigger_reason":trigger_reason,"model_version":prediction.get("engine_version"),"periods":periods,"contributions":contributions,
      "market_regime":regime,"news_context":{"count":len(news),"evidence_score":news_score,"included_in_probability":False,
        "reason":"新闻尚未完成跨市场消融验证；当前仅作为事件、风险和重算触发器，不伪装成概率输入。","items":news[:12]},
      "risk_plan":technical.get("risk_plan") or decision.get("risk_plan"),"similar_events":_similar_events(symbol,news),
      "probability_boundary":"P(UP/SIDEWAYS/DOWN)来自样本外校准价格模型；Impact Score与新闻情绪均不是上涨概率。",
      "information_cutoff_enforced":True,"prediction_notice":"模型概率判断，不构成投资建议。"}
    snapshot_id=save_market_intelligence_snapshot(snapshot);snapshot["snapshot_id"]=snapshot_id
    return snapshot


def _snapshot_from_history(symbol: str, asset_type: str, rows: list[dict]) -> dict | None:
    if not rows:return None
    latest_time=rows[0]["prediction_time"];group=[x for x in rows if x["prediction_time"]==latest_time]
    periods=[]
    for row in group:
        periods.append({"horizon":_display_horizon(asset_type,row["horizon"]),"raw_horizon":row["horizon"],"direction":row["prediction"],
          "trend":{"UP":"偏多","FLAT":"震荡","DOWN":"偏空"}.get(row["prediction"]),"up":round(row["prob_up"]*100,1),"sideways":round(row["prob_flat"]*100,1),"down":round(row["prob_down"]*100,1),
          "confidence":"Historical cache","evidence":"C","samples":None,"model_level":"Experimental","probability_type":"calibrated_model_probability","target_time":row["target_time"]})
    news=_news_snapshot(symbol,latest_time)
    return {"symbol":symbol,"asset_type":asset_type,"status":"STALE_CACHE","generated_at":latest_time,"updated_at":latest_time,"data_cutoff":latest_time,
      "trigger_reason":"prediction_history_cache","model_version":group[0].get("model_version"),"periods":periods,"contributions":[],"market_regime":group[0].get("regime"),
      "news_context":{"count":len(news),"included_in_probability":False,"items":news[:12]},"similar_events":_similar_events(symbol,news),
      "information_cutoff_enforced":True,"probability_boundary":"缓存概率来自已保存的校准价格模型；新闻未静默混入概率。","prediction_notice":"模型概率判断，不构成投资建议。"}


def intelligence_view(symbol: str, asset_type: str) -> dict:
    rows=_prediction_rows(symbol,asset_type);saved=market_intelligence_snapshots(symbol,asset_type,20)
    current=saved[0] if saved else _snapshot_from_history(symbol,asset_type,rows)
    if current is None:
        current={"symbol":symbol,"asset_type":asset_type,"status":"INSUFFICIENT_EVIDENCE","generated_at":_now(),"data_cutoff":None,"periods":[],"contributions":[],
                 "news_context":{"count":len(_news_snapshot(symbol)),"included_in_probability":False,"items":_news_snapshot(symbol)[:12]},
                 "prediction_notice":"尚无真实模型快照，请在后台运行判断。"}
    previous=saved[1] if len(saved)>1 else None;changes=[]
    if previous:
        old={x["horizon"]:x for x in previous.get("periods",[])}
        for item in current.get("periods",[]):
            before=old.get(item["horizon"])
            if before and (before.get("direction")!=item.get("direction") or abs(before.get("up",0)-item.get("up",0))>=3):
                changes.append({"horizon":item["horizon"],"from":before.get("direction"),"to":item.get("direction"),"up_delta":round(item.get("up",0)-before.get("up",0),1),"reason":current.get("trigger_reason")})
    return {**current,"why_changed":changes,"track_record":_track_metrics(rows),"source_registry":list(SOURCE_REGISTRY),"history_count":len(rows),"immutable_snapshot_count":len(saved)}


def track_record(symbol: str | None = None, asset_type: str | None = None) -> dict:
    with connection() as conn:
        query="SELECT * FROM prediction_history WHERE 1=1";params=[]
        if symbol:query+=" AND symbol=?";params.append(symbol)
        if asset_type:query+=" AND asset_type=?";params.append(asset_type)
        rows=[dict(x) for x in conn.execute(query,params).fetchall()]
    horizons=sorted({x["horizon"] for x in rows});assets=sorted({x["symbol"] for x in rows});markets=sorted({x["asset_type"] for x in rows})
    return {"overall":_track_metrics(rows),"by_horizon":{h:_track_metrics([x for x in rows if x["horizon"]==h]) for h in horizons},
            "by_asset":{s:_track_metrics([x for x in rows if x["symbol"]==s]) for s in assets},
            "by_market":{m:_track_metrics([x for x in rows if x["asset_type"]==m]) for m in markets},
            "event_breakdown_status":"NOT_AVAILABLE","event_breakdown_notice":"旧预测未持久化事件标签；不会事后补写或猜测。"}
