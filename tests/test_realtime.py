from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from backend.realtime import MarketState, PredictionTrigger, RealtimeDataManager, RealtimeMarketStore, RealtimeRefreshPolicy


def candles(count: int = 90) -> list[dict]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        close = 100 + index * .1 + (index % 4) * .03
        rows.append({"timestamp":(start+timedelta(minutes=index)).isoformat(),"open":close-.05,
                     "high":close+.2,"low":close-.2,"close":close,"volume":1000+index,"amount":close*(1000+index)})
    return rows


def test_ticker_deduplication_and_timestamps():
    async def run():
        manager=RealtimeDataManager();state=MarketState("BTC","crypto","1m")
        stamp="2026-01-01T00:00:01+00:00"
        quote={"price":100.0,"volume":2.0,"updated_at":stamp}
        assert await manager.process_ticker(state,quote,stamp,"fixture") is True
        assert await manager.process_ticker(state,quote,stamp,"fixture") is False
        assert state.dataTimestamp==stamp and state.receivedTimestamp and state.processedTimestamp
    asyncio.run(run())


def test_current_candle_updates_then_rolls_and_recalculates_full_pipeline():
    async def run():
        manager=RealtimeDataManager();state=MarketState("BTC","crypto","1m",candles=candles())
        current=dict(state.candles[-1]);current["close"]+=1;current["high"]+=1;current["volume"]+=20
        assert await manager.process_candle(state,current,"fixture")
        assert len(state.candles)==90 and state.candles[-1]["close"]==current["close"]
        assert state.indicators and state.strategy and state.strategy["structure"] is not None
        following=dict(current);following["timestamp"]=(datetime.fromisoformat(current["timestamp"])+timedelta(minutes=1)).isoformat()
        assert await manager.process_candle(state,following,"fixture")
        assert len(state.candles)==91
    asyncio.run(run())


def test_trade_id_deduplication_and_real_order_flow_aggregation():
    async def run():
        manager=RealtimeDataManager();state=MarketState("BTC","crypto","1m")
        trade={"tradeId":"42","px":"100.5","sz":"1.5","side":"buy","ts":"1767225600000"}
        assert await manager.process_trade(state,trade)
        assert not await manager.process_trade(state,trade)
        assert state.order_flow["buy_volume"]==1.5 and state.order_flow["trade_count"]==1
    asyncio.run(run())


def test_real_trade_tick_updates_ohlcv_and_all_timeframe_buckets():
    async def run():
        manager = RealtimeDataManager()
        states = [await manager.store.get_or_create("crypto", "BTC", interval)
                  for interval in manager.OKX_BARS]
        first = 1767225665000  # 2026-01-01T00:01:05Z
        for state in states:
            await manager.process_trade(state, {"tradeId":f"a-{state.interval}","px":"100","sz":"2","side":"buy","ts":str(first)})
            await manager.process_trade(state, {"tradeId":f"b-{state.interval}","px":"103","sz":"1","side":"sell","ts":str(first+5000)})
            await manager.process_trade(state, {"tradeId":f"c-{state.interval}","px":"99","sz":"4","side":"buy","ts":str(first+10000)})
            bar = state.candles[-1]
            assert (bar["open"],bar["high"],bar["low"],bar["close"]) == (100,103,99,99)
            assert bar["volume"] == 7 and bar["amount"] == 699 and bar["tick_count"] == 3
            assert bar["timestamp"] == manager._bucket_timestamp(first,state.interval)
        one_minute = states[0]
        await manager.process_trade(one_minute,{"tradeId":"next","px":"101","sz":".5","side":"buy","ts":str(first+60000)})
        assert len(one_minute.candles)==2 and one_minute.candles[-2]["confirmed"] is True
        assert one_minute.candles[-1]["open"]==101 and one_minute.candles[-1]["confirmed"] is False
    asyncio.run(run())


def test_health_thresholds_and_prediction_debounce():
    policy=RealtimeRefreshPolicy(crypto_ticker_seconds=2,prediction_min_seconds=60)
    store=RealtimeMarketStore(policy);state=MarketState("BTC","crypto","1m",lastUpdateTime=100)
    assert store.health(state,103)=="CONNECTED"
    assert store.health(state,105)=="WARNING"
    assert store.health(state,109)=="STALE"
    assert store.health(state,117)=="DISCONNECTED"
    trigger=PredictionTrigger(policy)
    assert trigger.evaluate(state,100,True,"BUY",False)==["NEW_BAR"]
    assert trigger.evaluate(state,101,True,"SELL",True)==[]


def test_event_bus_connects_store_to_consumers():
    async def run():
        manager=RealtimeDataManager();queue=manager.bus.subscribe();state=MarketState("BTC","crypto","1m")
        await manager.process_ticker(state,{"price":100,"volume":1},"2026-01-01T00:00:00+00:00","fixture")
        event=await asyncio.wait_for(queue.get(),.2)
        assert event["type"]=="ticker" and event["data"]["quote"]["price"]==100
    asyncio.run(run())
