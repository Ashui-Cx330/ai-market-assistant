from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.terminal_v19 import (_market_pair, _scanner_indicator_summary, _score,
                                  _briefing_item, _watchlist_news_payload, _weighted_news_score,
                                  parse_strategy_text)


@pytest.fixture
def sample_candles():
    start=datetime(2025,1,1,tzinfo=timezone.utc)
    return [{"timestamp":(start+timedelta(days=index)).isoformat(),"open":100+index*.1,
             "high":101+index*.1,"low":99+index*.1,"close":100.5+index*.1,
             "volume":1000+index,"amount":100000+index} for index in range(240)]


def test_ai_score_is_deterministic_and_explained(monkeypatch):
    monkeypatch.setattr("backend.terminal_v19._news_dimension", lambda symbol: (60, "利好", []))
    quote={"price":110}
    indicators={"score":70,"latest":{"ma20":100,"ma60":90,"macd":2,"macd_signal":1,"rsi":58,"volume_ratio":1.5,"atr":2}}
    first=_score(quote,indicators,"NVDA");second=_score(quote,indicators,"NVDA")
    assert first==second
    assert 0<=first["ai_score"]<=100 and len(first["factors"])>=4
    assert "不是预测准确率" in first["score_definition"]


def test_natural_language_strategy_parser_is_strict():
    rule=parse_strategy_text("RSI低于30后买入，持有5天")
    assert rule["status"]=="PARSED"
    assert rule["entry"]=={"indicator":"RSI(14)","operator":"<","value":30.0}
    assert rule["exit"]["bars"]==5
    rejected=parse_strategy_text("凭感觉帮我稳赚")
    assert rejected["status"]=="UNSUPPORTED" and rejected["strategy"] is None


def test_scanner_uses_compact_indicator_payload(sample_candles):
    result=_scanner_indicator_summary(sample_candles)
    assert result["series"]==[]
    assert 0<=result["score"]<=100
    assert {"ma20","macd","rsi","volume_ratio","atr"}.issubset(result["latest"])


def test_market_pair_uses_auditable_kline_fallback(monkeypatch,sample_candles):
    async def failed_quote(_symbol): raise ConnectionError("quote route blocked")
    async def real_kline(_symbol,_interval,_limit): return sample_candles,"Test real OHLCV"
    monkeypatch.setattr("backend.terminal_v19.stock_quote",failed_quote)
    monkeypatch.setattr("backend.terminal_v19.stock_kline",real_kline)
    quote,candles,source=asyncio.run(_market_pair("600519.SH","stock","1d",240))
    assert candles==sample_candles and source=="Test real OHLCV"
    assert quote["price"]==sample_candles[-1]["close"]
    assert quote["currency"]=="CNY"
    assert quote["quote_status"]=="DELAYED_KLINE_FALLBACK"


def test_watchlist_news_contains_only_explicit_relations(monkeypatch):
    assets=[{"symbol":"BTC","name":"Bitcoin","asset_type":"crypto"},
            {"symbol":"NVDA","name":"NVIDIA","asset_type":"stock"}]
    monkeypatch.setattr("backend.terminal_v19.list_watchlist",lambda:assets)
    def feed(symbol,**_kwargs):
        return {"items":[{"id":symbol,"title":symbol,"symbols":[symbol],"published_at":"2026-01-01T00:00:00+00:00",
                          "sentiment":{"score":20},"impact":{"score":50}}]}
    monkeypatch.setattr("backend.terminal_v19.query_news_intelligence",feed)
    result=_watchlist_news_payload(None,168)
    assert result["total"]==2
    assert result["scope"]=="ONLY_EXPLICIT_WATCHLIST_RELATIONS"
    assert {x["matched_watchlist_symbols"][0] for x in result["items"]}=={"BTC","NVDA"}


def test_recent_high_impact_news_receives_more_weight():
    now=datetime.now(timezone.utc)
    items=[{"published_at":now.isoformat(),"sentiment":{"score":60},"impact":{"score":90}},
           {"published_at":(now-timedelta(days=20)).isoformat(),"sentiment":{"score":-60},"impact":{"score":20}}]
    assert _weighted_news_score(items)>40


def test_trader_briefing_closes_gate_for_stale_or_breached_data():
    report={"symbol":"BTC","name":"Bitcoin","asset_type":"crypto","currency":"USDT",
            "current_price":90,"verdict":"偏多","action":"做多观察","score":25,
            "quote_updated_at":(datetime.now(timezone.utc)-timedelta(hours=10)).isoformat(),
            "data_cutoff":datetime.now(timezone.utc).date().isoformat(),
            "data_source":"observed test source","summary":"test","components":{},
            "risk_plan":{"entry":100,"exit_line":95,"take_profits":[]},
            "news":{"count":0,"items":[]}}
    item,alerts=_briefing_item(report,12)
    assert item["decision_gate"]=="RISK_REVIEW"
    assert item["evidence_grade"]=="D"
    assert {x["alert_type"] for x in alerts}=={"EXIT_LINE_BREACH","STALE_DATA"}
    assert any("NO EDGE" in blocker for blocker in item["blockers"])


def test_crypto_daily_candle_timestamp_does_not_override_fresh_quote():
    now=datetime.now(timezone.utc)
    report={"symbol":"BTC","name":"Bitcoin","asset_type":"crypto","currency":"USDT",
            "current_price":100,"verdict":"中性","action":"等待确认","score":0,
            "quote_updated_at":now.isoformat(),"data_cutoff":now.date().isoformat(),
            "data_source":"observed test source","summary":"test","components":{},
            "risk_plan":{"entry":100,"exit_line":90,"take_profits":[]},"news":{"count":0,"items":[]}}
    item,alerts=_briefing_item(report,120)
    assert item["is_stale"] is False
    assert item["evidence_grade"]=="C"
    assert not any(x["alert_type"]=="STALE_DATA" for x in alerts)
