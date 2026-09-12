from datetime import datetime, timedelta, timezone

from backend.news_intelligence import (EventExtractionEngine, NewsQuery, _dedupe,
                                       _filter, build_intelligence,
                                       event_backtest, structured_similarity)


def item(identity: str, title: str, published: str):
    return {"id":identity,"title":title,"url":f"https://example.test/{identity}","source":"fixture publisher",
            "provider":"test fixture","scope":"company","published_at":published,"collected_at":published,"symbol":"600519"}


def test_event_sentiment_and_causal_impact_are_explainable():
    stamp="2026-01-01T00:00:00+00:00"
    result=EventExtractionEngine().analyze(item("1","公司业绩大增超预期并宣布回购",stamp),"600519","测试公司")
    assert result["sentiment"]["score"] > 0
    assert result["sentiment"]["direction"] in {"利好","强利好"}
    assert result["sentiment"]["method"].endswith("(not FinBERT/LLM)")
    # No explicit entity is present, so the engine must not invent a direct stock relation.
    assert result["impact"]["primary"] == []
    assert result["impact"]["counter"]


def test_intelligence_does_not_claim_fake_accuracy():
    stamp="2026-01-01T00:00:00+00:00"
    result=build_intelligence([item("1","芯片行业增长突破",stamp)],"600519","测试公司",62,1.4,0)
    assert result["decision"]["model_historical_accuracy"] is None
    assert result["decision"]["confidence_grade"] == "D"
    assert result["predictions"]["T+1"]["type"] == "uncalibrated_evidence_estimate"


def test_point_in_time_backtest_enters_strictly_after_publication_and_rejects_small_sample():
    start=datetime(2026,1,1,tzinfo=timezone.utc)
    candles=[]
    for index in range(40):
        close=100+index
        candles.append({"timestamp":(start+timedelta(days=index)).isoformat(),"open":close-.5,
                        "high":close+1,"low":close-1,"close":close,"volume":100})
    event=EventExtractionEngine().analyze(item("1","公司回购",(start+timedelta(hours=12)).isoformat()),"600519","测试公司")
    result=event_backtest([event],candles)
    assert result["status"] == "DATA_INSUFFICIENT"
    assert result["outcomes"][0]["entry_time"] == candles[1]["timestamp"]
    assert result["metrics"]["T+5"]["event_window"] == "[-1,+5]"
    assert result["metrics"]["T+5"]["return_distribution"]["mean"] is not None
    future=EventExtractionEngine().analyze(item("2","公司回购",(start+timedelta(days=100)).isoformat()),"600519","测试公司")
    assert event_backtest([future],candles)["samples"] == 0


def test_entity_linking_does_not_force_unrelated_query_target():
    stamp="2026-01-01T00:00:00+00:00"
    unrelated=EventExtractionEngine().analyze(item("u","美联储讨论利率政策",stamp),"600519","贵州茅台")
    related=EventExtractionEngine().analyze(item("r","贵州茅台发布回购公告",stamp),"600519","贵州茅台")
    assert "600519" not in unrelated["symbols"]
    assert "600519" in related["symbols"]


def test_symbol_filter_and_fuzzy_dedup_are_deterministic():
    stamp="2026-01-01T00:00:00+00:00"
    a=item("a","英伟达财报超预期 - 媒体甲",stamp);a.update({"summary":"","symbols":[],"sectors":[]})
    b=item("b","英伟达财报超预期 | 媒体乙",stamp);b.update({"summary":"","symbols":[],"sectors":[]})
    rows=_filter([a,b],NewsQuery(symbol="NVDA",name="英伟达"))
    merged=_dedupe(rows)
    assert len(merged)==1 and merged[0]["related_source_count"]==2


def test_backtest_filters_direction_and_uses_trading_bars_for_t10():
    start=datetime(2026,1,1,tzinfo=timezone.utc);candles=[];events=[]
    for index in range(80):
        candles.append({"timestamp":(start+timedelta(days=index)).isoformat(),"open":100+index,"high":102+index,"low":99+index,"close":101+index,"volume":100})
    for index in range(12):
        event=EventExtractionEngine().analyze(item(str(index),"公司回购",(start+timedelta(days=index*2,hours=12)).isoformat()),"600519","测试公司")
        event["impact"]["score"]=80;events.append(event)
    result=event_backtest(events,candles,direction="bullish",min_impact=70,min_confidence=.5,selected_horizon=10)
    assert result["status"]=="AVAILABLE" and result["samples"]==12
    assert result["metrics"]["T+10"]["samples"]==12


def test_similar_events_use_structured_fields_not_llm_judgement():
    stamp="2026-01-01T00:00:00+00:00"
    query=EventExtractionEngine().analyze(item("q","公司回购",stamp),"600519","测试公司")
    same=EventExtractionEngine().analyze(item("same","公司回购",stamp),"600519","测试公司")
    different=EventExtractionEngine().analyze(item("different","监管处罚导致亏损",stamp),"600519","测试公司")
    matches=structured_similarity(query,[different,same])
    assert matches[0]["event"]["id"]=="same"
    assert matches[0]["method"]=="structured-v1"
