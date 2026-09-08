from __future__ import annotations

from backend.terminal_v19 import _score, parse_strategy_text


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
