from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

import backend.database as database
from backend.ai_engine import _aligned_dataset, _purged_slices, feature_frame
from backend.v4_research import (AnomalyEngine, CrossAssetEngine,
                                 DataQualityEngine, NewsEventEngine,
                                 PathRiskEngine, PortfolioRiskEngine, factor_ablation,
                                 ReturnDistributionEngine)


def candles(count=620, seed=91, start="2025-01-01", drift=.0002):
    rng=np.random.default_rng(seed);close=100*np.exp(np.cumsum(rng.normal(drift,.006,count)))
    times=pd.date_range(start,periods=count,freq="15min",tz="UTC");rows=[]
    for i,value in enumerate(close):
        opened=close[i-1] if i else value;spread=.002+abs(rng.normal(0,.0006))
        rows.append({"timestamp":times[i].isoformat(),"open":opened,"high":max(opened,value)*(1+spread),
                     "low":min(opened,value)*(1-spread),"close":value,"volume":float(rng.integers(1000,9000)),"amount":0.0})
    return rows


def test_purged_embargo_boundaries_do_not_overlap_labels():
    frame=feature_frame(candles());_,_,meta=_aligned_dataset(frame,"crypto","15m","4H")
    slices=_purged_slices(meta,embargo_rows=16)
    tr=slices["train"];ca=slices["calibration"];va=slices["validation"];te=slices["test"]
    assert meta["target_time"].iloc[tr[1]-1] < meta["feature_time"].iloc[ca[0]]
    assert meta["target_time"].iloc[ca[1]-1] < meta["feature_time"].iloc[va[0]]
    assert meta["target_time"].iloc[va[1]-1] < meta["feature_time"].iloc[te[0]]
    assert ca[0]-tr[1] >= 16 and va[0]-ca[1] >= 16 and te[0]-va[1] >= 16


def test_cross_asset_correlations_are_calculated_not_fixed():
    target=candles(seed=1);peer=candles(seed=2)
    output=CrossAssetEngine().analyze("BTC",target,{"ETH":peer})
    assert output["status"]=="AVAILABLE" and output["correlations"][0]["samples"]>100
    assert -1 <= output["correlations"][0]["correlation"] <= 1


def test_structured_news_dedup_and_time_fields():
    rows=candles();published=datetime(2025,1,3,tzinfo=timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
    news={"status":"AVAILABLE","source":"test wire","headlines":[
        {"title":"ETF 获批 BTC 上涨","published":published,"keyword_signal":1},
        {"title":"ETF 获批 BTC 上涨","published":published,"keyword_signal":1}]}
    output=NewsEventEngine().analyze(news,"BTC",rows,datetime.now(timezone.utc).isoformat())
    assert len(output["events"])==1 and output["duplicate_count"]==1
    assert output["events"][0]["publication_time"] and output["events"][0]["collected_at"]


def test_quality_path_distribution_anomaly_and_portfolio_are_observed():
    rows=candles();frame=feature_frame(rows)
    quality=DataQualityEngine().analyze(frame,"real test feed",{"news":{"status":"NO_DATA"}},[])
    assert 0<=quality["score"]<=100 and quality["components"]["source_count"]==1
    path=PathRiskEngine().analyze(frame,"15m","crypto","1H","LONG",2,
                                  [{"name":"TP1","price":103},{"name":"TP2","price":105}])
    assert path["status"]=="AVAILABLE" and path["samples"]>100 and "mae" in path and "mfe" in path
    distribution=ReturnDistributionEngine().analyze(frame,"15m","crypto","1H")
    assert distribution["status"]=="AVAILABLE" and distribution["holdout_samples"]>0
    ablation=factor_ablation(frame,"15m","crypto","1H")
    assert ablation["status"]=="AVAILABLE" and len(ablation["experiments"])==3
    anomaly=AnomalyEngine().analyze(frame,None,{"events":[]})
    assert anomaly["status"] in {"NORMAL","ANOMALY"}
    returns=pd.DataFrame({"BTC":np.random.default_rng(1).normal(0,.01,200),"ETH":np.random.default_rng(2).normal(0,.015,200)})
    portfolio=PortfolioRiskEngine().analyze(returns,{"BTC":.6,"ETH":.4})
    assert portfolio["status"]=="AVAILABLE" and portfolio["cvar_95_per_bar"]>=portfolio["var_95_per_bar"]


def test_feature_store_schema_and_flat_lifecycle(tmp_path,monkeypatch):
    monkeypatch.setattr(database,"DB_PATH",tmp_path/"v4.sqlite3");database.init_db()
    frame=feature_frame(candles(200));saved=database.save_feature_observations("BTC",frame["timestamp_utc"].iloc[-1].isoformat(),frame,"real","HIGH")
    assert saved>10
    with database.connection() as conn:
        columns={row[1] for row in conn.execute("PRAGMA table_info(prediction_history)")}
        assert {"prediction_id","status","mae","mfe","data_quality"}.issubset(columns)
        assert conn.execute("SELECT COUNT(*) FROM feature_observations").fetchone()[0]==saved
