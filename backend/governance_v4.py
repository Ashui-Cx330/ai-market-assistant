"""Fail-closed production governance and point-in-time news eligibility."""
from __future__ import annotations

import pandas as pd


def news_feature_eligibility(news: dict, prediction_timestamp: str) -> dict:
    published=news.get("published_at")
    if not published:return {"eligible":False,"value":None,"reason":"UNKNOWN_PUBLISHED_AT"}
    try:
        source=pd.Timestamp(published);cutoff=pd.Timestamp(prediction_timestamp)
        source=source.tz_localize("UTC") if source.tzinfo is None else source.tz_convert("UTC")
        cutoff=cutoff.tz_localize("UTC") if cutoff.tzinfo is None else cutoff.tz_convert("UTC")
    except (TypeError,ValueError):return {"eligible":False,"value":None,"reason":"INVALID_TIMESTAMP"}
    if source>cutoff:return {"eligible":False,"value":None,"reason":"FUTURE_NEWS"}
    return {"eligible":True,"value":news.get("sentiment"),"reason":"POINT_IN_TIME"}


GATES=("oos_valid","walk_forward_stable","beats_baseline","positive_ic","positive_rank_ic",
       "stable_icir","positive_after_cost","acceptable_sharpe","acceptable_max_drawdown",
       "multi_window_stable","no_leakage","data_quality_pass","calibrated","multi_asset")


def production_gate(evidence: dict) -> dict:
    failed=[gate for gate in GATES if evidence.get(gate) is not True]
    return {"qualified":not failed,"decision":"MANUAL_REVIEW_REQUIRED" if not failed else "NO_EDGE",
            "production_model":None,"champion":None,"failed_gates":failed,
            "automatic_promotion":False,"note":"A pass creates a review candidate; it never auto-promotes."}
