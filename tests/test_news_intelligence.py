from datetime import datetime, timedelta, timezone

from backend.news_intelligence import EventExtractionEngine, build_intelligence, event_backtest


def item(identity: str, title: str, published: str):
    return {"id":identity,"title":title,"url":f"https://example.test/{identity}","source":"fixture publisher",
            "provider":"test fixture","scope":"company","published_at":published,"collected_at":published,"symbol":"600519"}


def test_event_sentiment_and_causal_impact_are_explainable():
    stamp="2026-01-01T00:00:00+00:00"
    result=EventExtractionEngine().analyze(item("1","公司业绩大增超预期并宣布回购",stamp),"600519","测试公司")
    assert result["sentiment"]["score"] > 0
    assert result["sentiment"]["direction"] in {"利好","强利好"}
    assert result["sentiment"]["method"].endswith("(not FinBERT/LLM)")
    assert result["impact"]["primary"] and result["impact"]["counter"]


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
    future=EventExtractionEngine().analyze(item("2","公司回购",(start+timedelta(days=100)).isoformat()),"600519","测试公司")
    assert event_backtest([future],candles)["samples"] == 0
