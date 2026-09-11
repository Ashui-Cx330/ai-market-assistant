from __future__ import annotations

import asyncio

from backend import symbol_registry
from backend.performance import record, snapshot
from backend.market import _parse_tencent_daily_rows, canonical_symbol
from backend.providers import _eastmoney_secid


def test_local_registry_supports_required_aliases(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_AI_DATA_DIR",str(tmp_path))
    assert symbol_registry.search("600519","stock")[0]["name"] == "贵州茅台"
    assert symbol_registry.search("贵州茅台","stock")[0]["symbol"] == "600519"
    assert symbol_registry.search("pingan","stock")[0]["symbol"] == "000001"
    assert symbol_registry.search("Apple","stock")[0]["symbol"] == "AAPL"
    assert symbol_registry.search("比特币","crypto")[0]["symbol"] == "BTC"
    assert symbol_registry.search("BTCUSDT","crypto")[0]["pair"] == "BTC/USDT"


def test_search_endpoint_uses_registry_before_network(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_AI_DATA_DIR",str(tmp_path))
    monkeypatch.setattr("backend.market.schedule_symbol_refresh",lambda:None)
    from backend.market import stock_search, crypto_search
    assert asyncio.run(stock_search("300750"))[0]["name"] == "宁德时代"
    assert asyncio.run(crypto_search("BNBUSDT"))[0]["symbol"] == "BNB"


def test_performance_ring_summarizes_real_durations():
    record("/api/test","GET",200,12.25)
    record("/api/test","GET",200,20.75)
    result=snapshot(10)
    row=next(item for item in result["summary"] if item["path"]=="/api/test")
    assert row["calls"] >= 2
    assert row["average_ms"] >= 16.5


def test_a_share_exchange_identity_is_not_ambiguous():
    assert _eastmoney_secid("000001") == "0.000001"  # 平安银行
    assert _eastmoney_secid("000001.SZ") == "0.000001"
    assert _eastmoney_secid("000001.SH") == "1.000001"  # 上证指数
    assert canonical_symbol("000001","stock") == "000001.SZ"
    assert canonical_symbol("000001.SH","stock") == "000001.SH"


def test_tencent_daily_fallback_accepts_current_string_format():
    rows=["2026-09-10 11.68 11.85 11.86 11.66 867632",["2026-09-11","11.82","11.74","11.86","11.71","832461"]]
    candles=_parse_tencent_daily_rows(rows)
    assert [row["close"] for row in candles] == [11.85,11.74]
    assert candles[1]["volume"] == 832461
