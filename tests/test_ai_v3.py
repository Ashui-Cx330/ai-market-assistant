from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import timedelta

import backend.database as database
from backend.ai_engine import feature_frame
from backend.v3_engines import (CapitalFlowEngine, MarketRegimeEngine,
                                MarketStructureEngine, SupportResistanceEngine,
                                analyze_v3)


def candles(count=520, drift=.0004, volatility=.005, seed=33):
    rng=np.random.default_rng(seed);close=100*np.exp(np.cumsum(rng.normal(drift,volatility,count)))
    times=pd.date_range("2025-01-01",periods=count,freq="15min",tz="UTC");rows=[]
    for index,value in enumerate(close):
        opened=close[index-1] if index else value;spread=abs(rng.normal(.002,.0007))
        rows.append({"timestamp":times[index].isoformat(),"open":opened,"high":max(opened,value)*(1+spread),
                     "low":min(opened,value)*(1-spread),"close":value,"volume":float(rng.integers(1000,9000)),"amount":0.0})
    return rows


def prediction(rows, direction="UP", probabilities=None):
    probabilities=probabilities or {"down":.18,"flat":.22,"up":.60};last=pd.Timestamp(rows[-1]["timestamp"])
    item={"prediction":direction,"probabilities":probabilities,"model_consensus":.8,"feature_coverage":.5,
          "nominal_bar_count":4,"prediction_time":last.isoformat(),"future_timestamp":(last+timedelta(hours=1)).isoformat(),
          "threshold_percent":.25,"confidence":"B","model_details":{},"top_factors":[]}
    return {"engine_version":"3.0","predictions":{"1H":item},"model":{"asset_profile":{"confidence_factor":1.0,"slippage_factor":1.0}},
            "feature_availability":{"feature_coverage":.5,"feature_status":{}}}


def test_market_regime_is_dynamic():
    up=feature_frame(candles(drift=.002,volatility=.002));down=feature_frame(candles(drift=-.002,volatility=.002,seed=34))
    up_flow=CapitalFlowEngine().analyze(up);down_flow=CapitalFlowEngine().analyze(down)
    assert MarketRegimeEngine().analyze(up,up_flow,.5)["trend"] == "UP"
    assert MarketRegimeEngine().analyze(down,down_flow,.5)["trend"] == "DOWN"


def test_capital_flow_and_divergence_use_real_rows():
    frame=feature_frame(candles());result=CapitalFlowEngine().analyze(frame)
    assert result["status"] == "AVAILABLE" and result["gross_turnover"] > 0
    assert result["price_flow_relation"] in {"CONFIRMED","BULLISH_DIVERGENCE","BEARISH_DIVERGENCE"}
    assert result["is_exchange_reported_net_flow"] is False


def test_market_structure_and_level_zones():
    frame=feature_frame(candles());structure=MarketStructureEngine().analyze(frame);levels=SupportResistanceEngine().analyze(frame)
    assert structure["structure"] and levels["status"] == "AVAILABLE"
    assert levels["supports"] or levels["resistances"]
    assert all(0 <= level["strength"] <= 100 for level in levels["supports"]+levels["resistances"])


def test_dynamic_stop_take_profit_position_and_expected_value():
    rows=candles();result=analyze_v3(rows,prediction(rows),"15m","crypto","BTC",100000,.01,1)
    assert result["risk_plan"]["optimization"]["samples"] > 100
    assert result["risk_plan"]["stop_loss"] < result["risk_plan"]["entry"]
    assert len(result["take_profits"]) == 3 and result["risk_reward"]["tp2"] > 0
    assert result["position_sizing"]["quantity"] >= 0
    assert result["decision"]["action"] in {"BUY","SELL","HOLD","WAIT","NO_TRADE"}
    assert result["risk_validation"]["samples"] > 100


def test_scenarios_sum_to_one_and_have_traceability():
    rows=candles();result=analyze_v3(rows,prediction(rows),"15m","crypto","BTC")
    assert abs(sum(item["probability"] for item in result["scenarios"])-1) < 1e-9
    assert result["evidence_chain"]["stop_calculation"]["trace"]["atr"] > 0
    assert result["event_risk"]["status"] == "NO_DATA"


def test_negative_expected_value_can_block_trade():
    rows=candles();weak=prediction(rows,"UP",{"down":.7,"flat":.2,"up":.1});result=analyze_v3(rows,weak,"15m","crypto","BTC")
    assert result["expected_value"]["positive"] is False
    assert result["decision"]["action"] == "NO_TRADE"


def test_low_liquidity_profile_reduces_position():
    rows=candles();base=prediction(rows);low=prediction(rows);low["model"]["asset_profile"]={"confidence_factor":.5,"slippage_factor":2.5}
    normal=analyze_v3(rows,base,"15m","crypto","BTC");reduced=analyze_v3(rows,low,"15m","crypto","TINY")
    assert reduced["position_sizing"]["notional"] < normal["position_sizing"]["notional"]


def test_prediction_history_resolution_and_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(database,"DB_PATH",tmp_path/"history.sqlite3");database.init_db()
    rows=candles();past=rows[:-20];forecast=prediction(past);decision=analyze_v3(past,forecast,"15m","crypto","BTC")
    assert database.save_prediction_history("BTC","crypto","15m",forecast,decision) == 1
    assert database.resolve_prediction_history("BTC",rows) == 1
    stats=database.prediction_statistics();assert stats["overall"]["samples"] == 1
    assert stats["by_horizon"]["1H"]["brier_score"] >= 0
