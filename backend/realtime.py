"""Real market-data streaming and the process-wide realtime store.

Production paths in this module only accept exchange/provider observations.  The
test suite injects fixtures through ``process_*`` methods; those methods are not
connected to any production scheduler.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable
from zoneinfo import ZoneInfo

import websockets

from .indicators import indicator_payload
from .market import (crypto_derivatives, crypto_kline, crypto_onchain,
                     crypto_quote, macro_context, news_context,
                     normalize_crypto, stock_kline, stock_quote)
from .strategy_engine import StrategyEngine


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class RealtimeRefreshPolicy:
    crypto_ticker_seconds: int = 2
    stock_poll_seconds: int = 15
    derivatives_seconds: int = 30
    news_seconds: int = 60
    macro_seconds: int = 300
    onchain_seconds: int = 300
    warning_multiplier: float = 2.0
    stale_multiplier: float = 4.0
    disconnected_multiplier: float = 8.0
    max_reconnect_seconds: int = 30
    prediction_min_seconds: int = 300
    prediction_price_move: float = .003
    analysis_min_seconds: float = 1.0


@dataclass
class MarketState:
    symbol: str
    asset_type: str
    interval: str
    source: str | None = None
    quote: dict[str, Any] | None = None
    candles: list[dict[str, Any]] = field(default_factory=list)
    indicators: dict[str, Any] | None = None
    strategy: dict[str, Any] | None = None
    order_flow: dict[str, Any] = field(default_factory=lambda: {
        "status": "NO_DATA", "buy_volume": 0.0, "sell_volume": 0.0,
        "cumulative_delta": 0.0, "trade_count": 0,
    })
    context: dict[str, Any] = field(default_factory=dict)
    dataTimestamp: str | None = None
    receivedTimestamp: str | None = None
    processedTimestamp: str | None = None
    serverTimestamp: str | None = None
    lastUpdateTime: float = 0.0
    connectionStatus: str = "CONNECTING"
    latencyMs: int | None = None
    last_sequence: str | None = None
    last_signal: str | None = None
    last_prediction_at: float = 0.0
    last_prediction_price: float | None = None
    last_analysis_at: float = 0.0
    seen_trades: deque[str] = field(default_factory=lambda: deque(maxlen=4000))

    def snapshot(self) -> dict[str, Any]:
        return {k: v for k, v in vars(self).items() if k != "seen_trades"}


class RealtimeMarketStore:
    def __init__(self, policy: RealtimeRefreshPolicy | None = None) -> None:
        self.policy = policy or RealtimeRefreshPolicy()
        self._states: dict[str, MarketState] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def key(asset_type: str, symbol: str, interval: str) -> str:
        return f"{asset_type}:{symbol.upper()}:{interval}"

    async def get_or_create(self, asset_type: str, symbol: str, interval: str) -> MarketState:
        key = self.key(asset_type, symbol, interval)
        async with self._lock:
            return self._states.setdefault(key, MarketState(symbol=symbol.upper(), asset_type=asset_type, interval=interval))

    async def snapshots(self) -> dict[str, dict[str, Any]]:
        async with self._lock:
            return {key: state.snapshot() for key, state in self._states.items()}

    async def asset_states(self, asset_type: str, symbol: str) -> list[MarketState]:
        prefix = f"{asset_type}:{symbol.upper()}:"
        async with self._lock:
            return [state for key, state in self._states.items() if key.startswith(prefix)]

    def health(self, state: MarketState, now: float | None = None) -> str:
        if state.asset_type == "stock" and not self.stock_market_open(state.symbol):
            return "MARKET_CLOSED"
        if not state.lastUpdateTime:
            return "CONNECTING"
        base = self.policy.crypto_ticker_seconds if state.asset_type == "crypto" else self.policy.stock_poll_seconds
        age = (now or time.time()) - state.lastUpdateTime
        if age > base * self.policy.disconnected_multiplier:
            return "DISCONNECTED"
        if age > base * self.policy.stale_multiplier:
            return "STALE"
        if age > base * self.policy.warning_multiplier:
            return "WARNING"
        return "CONNECTED"

    @staticmethod
    def stock_market_open(symbol: str = "", moment: datetime | None = None) -> bool:
        if isinstance(symbol, datetime): moment,symbol=symbol,""
        is_us=bool(symbol and not symbol.isdigit())
        local = (moment or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York" if is_us else "Asia/Shanghai"))
        minute = local.hour * 60 + local.minute
        return local.weekday() < 5 and ((570 <= minute < 960) if is_us else (570 <= minute < 690 or 780 <= minute < 900))


class BackendEventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    def publish(self, event: dict[str, Any]) -> None:
        event.setdefault("serverTimestamp", utc_now())
        for queue in tuple(self._subscribers):
            if queue.full():
                try: queue.get_nowait()
                except asyncio.QueueEmpty: pass
            queue.put_nowait(event)


class PredictionTrigger:
    def __init__(self, policy: RealtimeRefreshPolicy) -> None:
        self.policy = policy

    def evaluate(self, state: MarketState, price: float, new_bar: bool, signal: str | None,
                 structure_changed: bool) -> list[str]:
        reasons: list[str] = []
        if new_bar: reasons.append("NEW_BAR")
        if state.last_prediction_price and abs(price / state.last_prediction_price - 1) >= self.policy.prediction_price_move:
            reasons.append("PRICE_MOVE_THRESHOLD")
        if state.last_signal and signal and signal != state.last_signal:
            reasons.append("STRATEGY_STATE_CHANGED")
        if structure_changed: reasons.append("BOS_CHOCH_OR_FVG_CHANGED")
        if reasons and time.time() - state.last_prediction_at >= self.policy.prediction_min_seconds:
            state.last_prediction_at = time.time()
            state.last_prediction_price = price
            return reasons
        return []


class RealtimeDataManager:
    OKX_PUBLIC = "wss://ws.okx.com:8443/ws/v5/public"
    OKX_BUSINESS = "wss://ws.okx.com:8443/ws/v5/business"
    OKX_BARS = {"1m":"candle1m", "5m":"candle5m", "15m":"candle15m", "30m":"candle30m",
                "1h":"candle1H", "4h":"candle4H", "1d":"candle1Dutc"}
    INTERVAL_SECONDS = {"1m":60, "5m":300, "15m":900, "30m":1800,
                        "1h":3600, "4h":14400, "1d":86400}

    def __init__(self) -> None:
        self.policy = RealtimeRefreshPolicy()
        self.store = RealtimeMarketStore(self.policy)
        self.bus = BackendEventBus()
        self.trigger = PredictionTrigger(self.policy)
        self.tasks: dict[str, list[asyncio.Task]] = {}
        self._subscription_lock = asyncio.Lock()
        self.running = False
        self.server_offset_ms = 0
        self._news_seen: dict[str, set[str]] = {}
        self._prediction_callback: Callable[[str,str,str,list[str]],Awaitable[dict[str,Any]]] | None = None
        self._prediction_running: set[str] = set()
        self._analysis_running: set[str] = set()

    def set_prediction_callback(self, callback: Callable[[str,str,str,list[str]],Awaitable[dict[str,Any]]]) -> None:
        self._prediction_callback = callback

    async def start(self) -> None:
        self.running = True
        self.tasks["_system"] = [asyncio.create_task(self.health_loop(), name="realtime-health")]
        self.tasks["_bootstrap"] = [asyncio.create_task(self.subscribe("crypto", "BTC", "1m"), name="realtime-default")]

    async def stop(self) -> None:
        self.running = False
        pending = [task for tasks in self.tasks.values() for task in tasks]
        for task in pending: task.cancel()
        if pending: await asyncio.gather(*pending, return_exceptions=True)
        self.tasks.clear()

    async def subscribe(self, asset_type: str, symbol: str, interval: str) -> MarketState:
        symbol = normalize_crypto(symbol) if asset_type == "crypto" else symbol
        if interval not in self.OKX_BARS or asset_type not in {"crypto", "stock"}:
            raise ValueError("不支持的实时订阅")
        state = await self.store.get_or_create(asset_type, symbol, interval)
        # One real trade stream maintains the in-progress candle for every
        # supported timeframe.  Empty states become useful immediately and are
        # backfilled when a client actually opens that timeframe.
        if asset_type == "crypto":
            await asyncio.gather(*(self.store.get_or_create(asset_type, symbol, item)
                                   for item in self.OKX_BARS))
        key = self.store.key(asset_type, symbol, interval)
        async with self._subscription_lock:
            if key in self.tasks:
                return state
            # Reserve before the network bootstrap so simultaneous clients can
            # never create duplicate upstream subscriptions.
            self.tasks[key] = []
        await self._bootstrap(state)
        if asset_type == "crypto":
            asset_key = f"feed:{asset_type}:{symbol}"
            shared = []
            if asset_key not in self.tasks:
                shared = [asyncio.create_task(self._okx_public_loop(state), name=f"trades:{asset_key}"),
                          asyncio.create_task(self._slow_context_loop(state), name=f"context:{asset_key}")]
                self.tasks[asset_key] = shared
            self.tasks[key] = [asyncio.create_task(self._okx_candle_loop(state), name=f"candle:{key}")]
        else:
            self.tasks[key] = [asyncio.create_task(self._stock_poll_loop(state), name=f"stock:{key}"),
                               asyncio.create_task(self._slow_context_loop(state), name=f"context:{key}")]
        return state

    async def _bootstrap(self, state: MarketState) -> None:
        try:
            quote_call = crypto_quote(state.symbol, True) if state.asset_type == "crypto" else stock_quote(state.symbol, True)
            kline_call = crypto_kline(state.symbol, state.interval, 500, True) if state.asset_type == "crypto" else stock_kline(state.symbol, state.interval, 500, True)
            quote, (candles, source) = await asyncio.gather(quote_call, kline_call)
            state.candles = candles
            await self.process_ticker(state, quote, quote.get("updated_at"), quote.get("source"))
            await self._process_analysis(state, source, new_bar=False)
            self.bus.publish({"type":"snapshot", "key":self.store.key(state.asset_type,state.symbol,state.interval), "data":state.snapshot()})
        except Exception as exc:
            state.connectionStatus = "WARNING"
            self.bus.publish({"type":"connection", "data":{"status":"WARNING", "reason":f"BOOTSTRAP:{type(exc).__name__}"}})

    async def process_ticker(self, state: MarketState, quote: dict[str, Any], data_timestamp: str | None,
                             source: str) -> bool:
        sequence = f"{data_timestamp}:{quote.get('price')}:{quote.get('volume')}"
        if sequence == state.last_sequence:
            return False
        received = utc_now(); state.last_sequence = sequence
        state.quote = quote; state.source = source; state.dataTimestamp = data_timestamp
        state.receivedTimestamp = received; state.processedTimestamp = utc_now(); state.serverTimestamp = utc_now()
        state.lastUpdateTime = time.time(); state.connectionStatus = "CONNECTED"
        try:
            observed = datetime.fromisoformat((data_timestamp or received).replace("Z", "+00:00"))
            state.latencyMs = max(0, int((datetime.now(timezone.utc) - observed).total_seconds() * 1000))
        except ValueError: state.latencyMs = None
        self.bus.publish({"type":"ticker", "key":self.store.key(state.asset_type,state.symbol,state.interval), "data":state.snapshot()})
        return True

    async def process_trade(self, state: MarketState, trade: dict[str, Any]) -> bool:
        trade_id = str(trade.get("tradeId") or "")
        if not trade_id or trade_id in state.seen_trades:
            return False
        state.seen_trades.append(trade_id)
        size = float(trade["sz"]); side = trade.get("side")
        state.order_flow["status"] = "AVAILABLE"
        state.order_flow["source"] = "OKX trades WebSocket"
        state.order_flow["trade_count"] += 1
        if side == "buy": state.order_flow["buy_volume"] += size
        elif side == "sell": state.order_flow["sell_volume"] += size
        state.order_flow["cumulative_delta"] = state.order_flow["buy_volume"] - state.order_flow["sell_volume"]
        state.order_flow["dataTimestamp"] = datetime.fromtimestamp(int(trade["ts"])/1000, timezone.utc).isoformat()
        await self.process_tick(state, float(trade["px"]), size, int(trade["ts"]), "OKX trades WebSocket")
        return True

    @classmethod
    def _bucket_timestamp(cls, timestamp_ms: int, interval: str) -> str:
        seconds = cls.INTERVAL_SECONDS[interval]
        bucket = (timestamp_ms // 1000 // seconds) * seconds
        return datetime.fromtimestamp(bucket, timezone.utc).isoformat()

    async def process_tick(self, state: MarketState, price: float, size: float,
                           timestamp_ms: int, source: str) -> bool:
        """Aggregate an observed trade into the live candle; never synthesizes data."""
        stamp = self._bucket_timestamp(timestamp_ms, state.interval)
        new_bar = not state.candles or stamp > state.candles[-1]["timestamp"]
        if state.candles and stamp < state.candles[-1]["timestamp"]:
            return False
        if new_bar:
            if state.candles:
                state.candles[-1]["confirmed"] = True
            candle = {"timestamp": stamp, "open": price, "high": price, "low": price,
                      "close": price, "volume": size, "amount": price * size,
                      "confirmed": False, "tick_count": 1}
            state.candles.append(candle)
        else:
            candle = state.candles[-1]
            # Exchange candle snapshots may mark the bar confirmed just before
            # the first next-period trade arrives; only mutate an open bucket.
            if candle.get("confirmed"):
                return False
            candle["high"] = max(float(candle["high"]), price)
            candle["low"] = min(float(candle["low"]), price)
            candle["close"] = price
            candle["volume"] = float(candle.get("volume") or 0) + size
            candle["amount"] = float(candle.get("amount") or 0) + price * size
            candle["tick_count"] = int(candle.get("tick_count") or 0) + 1
        state.candles = state.candles[-1200:]
        state.source = source
        state.dataTimestamp = datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc).isoformat()
        state.receivedTimestamp = utc_now(); state.lastUpdateTime = time.time(); state.connectionStatus = "CONNECTED"
        key = self.store.key(state.asset_type,state.symbol,state.interval)
        if time.time() - state.last_analysis_at >= self.policy.analysis_min_seconds and key not in self._analysis_running:
            self._analysis_running.add(key)
            state.last_analysis_at = time.time()
            asyncio.create_task(self._run_analysis(state, source, new_bar, key), name=f"analysis:{key}")
        state.processedTimestamp = utc_now(); state.serverTimestamp = utc_now()
        self.bus.publish({"type":"candle", "key":self.store.key(state.asset_type,state.symbol,state.interval),
                          "data":{"candle":dict(candle),"newBar":new_bar,"tickDriven":True,
                                  "state":state.snapshot()}})
        return True

    async def _run_analysis(self, state: MarketState, source: str, new_bar: bool, key: str) -> None:
        try:
            await self._process_analysis(state, source, new_bar)
        finally:
            self._analysis_running.discard(key)

    async def process_candle(self, state: MarketState, candle: dict[str, Any], source: str) -> bool:
        if not state.candles:
            state.candles = [candle]; new_bar = True
        else:
            last_ts = state.candles[-1]["timestamp"]
            if candle["timestamp"] < last_ts: return False
            new_bar = candle["timestamp"] > last_ts
            if new_bar: state.candles.append(candle)
            elif state.candles[-1].get("confirmed"):
                return False
            else: state.candles[-1] = candle
            state.candles = state.candles[-1200:]
        state.source = source; state.dataTimestamp = candle["timestamp"]
        state.receivedTimestamp = utc_now(); state.lastUpdateTime = time.time(); state.connectionStatus = "CONNECTED"
        await self._process_analysis(state, source, new_bar)
        state.processedTimestamp = utc_now(); state.serverTimestamp = utc_now()
        self.bus.publish({"type":"candle", "key":self.store.key(state.asset_type,state.symbol,state.interval),
                          "data":{"candle":candle,"newBar":new_bar,"state":state.snapshot()}})
        return True

    async def _process_analysis(self, state: MarketState, source: str, new_bar: bool) -> None:
        if len(state.candles) < 60: return
        state.last_analysis_at = time.time()
        old_structure = self._structure_fingerprint(state.strategy)
        # A trade may mutate the live candle while worker threads calculate.
        # Use one atomic event-loop snapshot so all indicators see identical bars.
        rows = [dict(candle) for candle in state.candles]
        order_flow = dict(state.order_flow)
        state.indicators = await asyncio.to_thread(indicator_payload, rows)
        state.strategy = await asyncio.to_thread(StrategyEngine().analyze, rows, state.interval, source,
                                                  None, order_flow)
        is_confirmed = bool(state.candles[-1].get("confirmed"))
        state.strategy["realtime_status"] = "CONFIRMED" if is_confirmed else "UNCONFIRMED"
        for name in ("latest_bos", "latest_choch"):
            item = state.strategy.get("structure", {}).get(name)
            if item: item["confirmation_status"] = "CONFIRMED"
        for item in state.strategy.get("fvgs", []):
            item["confirmation_status"] = "INVALIDATED" if item.get("status") == "FILLED" else "CONFIRMED"
        state.strategy.get("fibonacci", {})["confirmation_status"] = "CONFIRMED" if state.strategy.get("fibonacci", {}).get("available_at") else "UNCONFIRMED"
        signal = state.strategy["confluence"]["signal"]
        new_structure = self._structure_fingerprint(state.strategy)
        reasons = self.trigger.evaluate(state, float(state.candles[-1]["close"]), new_bar, signal,
                                        old_structure is not None and old_structure != new_structure)
        state.last_signal = signal
        self.bus.publish({"type":"analysis", "key":self.store.key(state.asset_type,state.symbol,state.interval),
                          "data":{"indicators":state.indicators,"strategy":state.strategy,
                                  "processedTimestamp":utc_now()}})
        if reasons:
            key=self.store.key(state.asset_type,state.symbol,state.interval)
            self.bus.publish({"type":"prediction_required", "key":key,
                              "data":{"mode":"LIVE","reasons":reasons,"triggeredAt":utc_now()}})
            if self._prediction_callback and key not in self._prediction_running:
                asyncio.create_task(self._run_prediction(state,reasons),name=f"prediction:{key}")

    async def _run_prediction(self,state:MarketState,reasons:list[str]) -> None:
        key=self.store.key(state.asset_type,state.symbol,state.interval);self._prediction_running.add(key)
        try:
            result=await self._prediction_callback(state.symbol,state.asset_type,state.interval,reasons)  # type: ignore[misc]
            self.bus.publish({"type":"prediction","key":key,"data":{"mode":"LIVE","reasons":reasons,
                "generatedAt":utc_now(),"result":result}})
        except Exception as exc:
            self.bus.publish({"type":"prediction_error","key":key,"data":{"error":type(exc).__name__,"reasons":reasons}})
        finally:self._prediction_running.discard(key)

    @staticmethod
    def _structure_fingerprint(strategy: dict[str, Any] | None) -> str | None:
        if not strategy: return None
        structure = strategy.get("structure", {})
        fvgs = [(item.get("formed_at"), item.get("status")) for item in strategy.get("fvgs", [])]
        fib = strategy.get("fibonacci", {})
        return json.dumps([structure.get("latest_bos"), structure.get("latest_choch"), fvgs,
                           fib.get("status"), fib.get("available_at")], sort_keys=True, default=str)

    async def _okx_public_loop(self, state: MarketState) -> None:
        delay = 1
        while self.running:
            try:
                async with websockets.connect(self.OKX_PUBLIC, ping_interval=15, ping_timeout=12, close_timeout=5) as ws:
                    inst = f"{state.symbol}-USDT"
                    await ws.send(json.dumps({"op":"subscribe","args":[{"channel":"tickers","instId":inst},
                        {"channel":"trades","instId":inst},{"channel":"books5","instId":inst}]}))
                    delay = 1; state.connectionStatus = "CONNECTED"
                    async for raw in ws:
                        message = json.loads(raw); channel = message.get("arg",{}).get("channel")
                        for row in message.get("data", []):
                            if channel == "tickers":
                                last=float(row["last"]); opened=float(row["open24h"] or last); stamp=datetime.fromtimestamp(int(row["ts"])/1000,timezone.utc).isoformat()
                                quote={"symbol":state.symbol,"pair":f"{state.symbol}/USDT","name":state.symbol,
                                    "asset_type":"crypto","currency":"USDT","price":last,"change":last-opened,
                                    "change_percent":(last/opened-1)*100 if opened else 0,"open":opened,"previous_close":None,
                                    "high":float(row["high24h"]),"low":float(row["low24h"]),"volume":float(row["vol24h"]),
                                    "amount":float(row["volCcy24h"]),"bid":float(row["bidPx"] or 0),"ask":float(row["askPx"] or 0),
                                    "source":"OKX ticker WebSocket","updated_at":stamp}
                                for target in await self.store.asset_states(state.asset_type, state.symbol):
                                    await self.process_ticker(target,dict(quote),stamp,quote["source"])
                            elif channel == "trades":
                                for target in await self.store.asset_states(state.asset_type, state.symbol):
                                    await self.process_trade(target,row)
                            elif channel == "books5":
                                if state.quote:
                                    state.quote["bid"] = float(row["bids"][0][0]) if row.get("bids") else None
                                    state.quote["ask"] = float(row["asks"][0][0]) if row.get("asks") else None
            except asyncio.CancelledError: raise
            except Exception as exc:
                state.connectionStatus = "DISCONNECTED"
                self.bus.publish({"type":"connection","key":self.store.key(state.asset_type,state.symbol,state.interval),
                                  "data":{"status":"DISCONNECTED","reason":type(exc).__name__,"retryIn":delay}})
                await asyncio.sleep(delay); delay=min(delay*2,self.policy.max_reconnect_seconds)
                try:
                    quote=await crypto_quote(state.symbol,True)
                    await self.process_ticker(state,quote,quote.get("updated_at"),quote.get("source","HTTP recovery"))
                except Exception: pass

    async def _okx_candle_loop(self, state: MarketState) -> None:
        delay=1
        while self.running:
            try:
                async with websockets.connect(self.OKX_BUSINESS,ping_interval=15,ping_timeout=12,close_timeout=5) as ws:
                    await ws.send(json.dumps({"op":"subscribe","args":[{"channel":self.OKX_BARS[state.interval],"instId":f"{state.symbol}-USDT"}]}))
                    delay=1
                    async for raw in ws:
                        message=json.loads(raw)
                        for row in message.get("data",[]):
                            candle={"timestamp":datetime.fromtimestamp(int(row[0])/1000,timezone.utc).isoformat(),"open":float(row[1]),
                                "high":float(row[2]),"low":float(row[3]),"close":float(row[4]),"volume":float(row[5]),
                                "amount":float(row[7] or row[6]),"confirmed":row[8]=="1"}
                            await self.process_candle(state,candle,"OKX candle WebSocket")
            except asyncio.CancelledError: raise
            except Exception:
                await asyncio.sleep(delay);delay=min(delay*2,self.policy.max_reconnect_seconds)
                try:
                    rows,source=await crypto_kline(state.symbol,state.interval,500,True)
                    if rows: await self.process_candle(state,rows[-1],source+" HTTP recovery")
                except Exception: pass

    async def _stock_poll_loop(self, state: MarketState) -> None:
        while self.running:
            try:
                quote,(rows,source)=await asyncio.gather(stock_quote(state.symbol,True),stock_kline(state.symbol,state.interval,500,True))
                await self.process_ticker(state,quote,quote.get("updated_at"),quote.get("source","A-share provider"))
                if rows: await self.process_candle(state,rows[-1],source+" 15s incremental polling")
                if not self.store.stock_market_open():
                    state.connectionStatus = "MARKET_CLOSED"
                    self.bus.publish({"type":"connection","key":self.store.key(state.asset_type,state.symbol,state.interval),
                                      "data":{"status":"MARKET_CLOSED","reason":"当前市场休市，实时行情暂停。",
                                              "lastUpdateTime":state.lastUpdateTime}})
            except asyncio.CancelledError: raise
            except Exception as exc:
                state.connectionStatus="WARNING"
                self.bus.publish({"type":"connection","data":{"status":"WARNING","reason":type(exc).__name__}})
            await asyncio.sleep(self.policy.stock_poll_seconds)

    async def _slow_context_loop(self, state: MarketState) -> None:
        counter=0
        while self.running:
            try:
                news=await news_context(state.symbol,state.asset_type,True)
                news_key=f"{state.asset_type}:{state.symbol}"
                seen=self._news_seen.setdefault(news_key,set())
                new_headlines=[item for item in news.get("headlines",[]) if (item.get("link") or item.get("title")) not in seen]
                seen.update(item.get("link") or item.get("title") for item in news.get("headlines",[]))
                payload={"news":news,"new_headlines":new_headlines,"checkedAt":utc_now(),
                         "incremental_since_last_check":True}
                if state.asset_type=="crypto":
                    payload["derivatives"],payload["onchain"]=await asyncio.gather(crypto_derivatives(state.symbol),crypto_onchain(state.symbol))
                if counter % 5 == 0: payload["macro"]=await macro_context()
                state.context.update(payload)
                self.bus.publish({"type":"context","key":self.store.key(state.asset_type,state.symbol,state.interval),"data":payload})
            except asyncio.CancelledError: raise
            except Exception: pass
            counter+=1;await asyncio.sleep(self.policy.news_seconds)

    async def health_loop(self) -> None:
        while self.running:
            snapshots = await self.store.snapshots()
            for key in snapshots:
                asset, symbol, interval = key.split(":", 2)
                state = await self.store.get_or_create(asset, symbol, interval)
                status = self.store.health(state)
                if status != state.connectionStatus:
                    state.connectionStatus = status
                    self.bus.publish({"type":"connection","key":key,"data":{"status":status,"lastUpdateTime":state.lastUpdateTime}})
            await asyncio.sleep(2)


realtime_manager = RealtimeDataManager()
