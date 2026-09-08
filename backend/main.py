from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
from contextlib import asynccontextmanager

import pandas as pd

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai_engine import feature_frame, predict
from .backtest import run_backtest
from .database import (DB_PATH, add_watchlist, cancel_paper_order, connection, create_limit_order, execute_paper_order,
                       fill_limit_order, init_db, list_backtests, list_watchlist,
                       get_news_intelligence, load_news_intelligence, load_provider_health, query_news_intelligence,
                       paper_daily_pnl, paper_snapshot, prediction_history, prediction_statistics, remove_watchlist,
                       resolve_prediction_history, save_backtest, save_external_feature_observations,
                       save_feature_observations, save_historical_event_outcomes, save_news_intelligence,
                       reset_paper_accounts, save_prediction_history, save_provider_health)
from .indicators import indicator_payload
from .market import (crypto_derivatives, crypto_kline, crypto_onchain, crypto_quote, crypto_search, event_risk,
                     canonical_symbol, cross_validate_quote, macro_context, macro_history, news_context, normalize_crypto, stock_fundamental, stock_kline, stock_quote,
                     stock_financial_history, stock_search)
from .providers import fetch_quotes
from .feature_services import FeatureStore
from .v3_engines import CapitalFlowEngine, MarketRegimeEngine, analyze_v3
from .v4_research import PortfolioRiskEngine, build_research_layer
from .strategy_engine import (SIGNAL_KEYS, StrategyEngine, strategy_backtest,
                              strategy_incremental_experiment, walk_forward_strategy,
                              optimize_strategy_parameters, ml_ict_incremental_experiment)
from .realtime import realtime_manager, utc_now
from .news_intelligence import build_intelligence, collect_historical_news, collect_news, event_backtest

ROOT = Path(__file__).resolve().parent.parent
VERSION = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    await realtime_manager.start()
    try:
        yield
    finally:
        await realtime_manager.stop()


app = FastAPI(title="AI行情助手", version=VERSION, docs_url="/api/docs", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def ok(data=None, message="成功", source=None) -> dict:
    result = {"success": True, "message": message, "data": data}
    if source: result["source"] = source
    return result


def resolved_symbol(symbol: str, asset_type: str) -> str:
    return canonical_symbol(symbol, asset_type.lower())


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"success": False, "message": str(exc.detail), "data": None})


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"success": False, "message": "请求参数不正确", "data": None, "errors": exc.errors()})


@app.exception_handler(Exception)
async def unknown_error(_: Request, exc: Exception):
    return JSONResponse(status_code=503, content={"success": False, "message": str(exc) or "服务暂时不可用", "data": None})


class WatchlistItem(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    asset_type: str
    name: str | None = None


class PredictionRequest(BaseModel):
    symbol: str
    asset_type: str
    interval: str = "1h"
    account_equity: float = Field(default=100000, gt=0)
    max_risk_percent: float = Field(default=.01, gt=0, le=.1)
    leverage: float = Field(default=1, ge=1, le=100)
    contract_multiplier: float = Field(default=1, gt=0)
    minimum_lot: float | None = Field(default=None, gt=0)


class BacktestRequest(BaseModel):
    symbol: str
    asset_type: str
    interval: str = "1d"
    strategy: str = "ma"
    initial_cash: float = Field(default=100000, gt=0)
    limit: int = Field(default=1000, ge=100, le=5000)
    fee_rate: float | None = Field(default=None, ge=0, le=.05)
    slippage_rate: float = Field(default=.0005, ge=0, le=.05)


class StrategyBacktestRequest(BaseModel):
    symbol: str
    asset_type: str
    interval: str = "1h"
    strategy: str = "fib_fvg_bos"
    limit: int = Field(default=1000, ge=200, le=5000)
    fee_rate: float | None = Field(default=None, ge=0, le=.05)
    slippage_rate: float = Field(default=.0005, ge=0, le=.05)
    walk_forward: bool = True
    optimize: bool = False
    start_time: str | None = None
    end_time: str | None = None
    parameters: dict[str, float] = Field(default_factory=dict)
    initial_cash: float = Field(default=100000, gt=0)


class PaperOrderRequest(BaseModel):
    symbol: str
    asset_type: str
    side: str
    quantity: float | None = Field(default=None, gt=0)
    amount: float | None = Field(default=None, gt=0)
    order_type: str = "MARKET"
    price: float | None = Field(default=None, gt=0)


class NewsBacktestRequest(BaseModel):
    symbol: str
    asset_type: str
    interval: str = "1d"
    event_type: str | None = None
    direction: str = "all"
    min_impact: float = Field(default=0, ge=0, le=100)
    min_confidence: float = Field(default=0, ge=0, le=100)
    horizon: int = Field(default=5)
    refresh_historical: bool = True


@app.get("/api/health")
def health() -> dict:
    with connection() as conn:
        conn.execute("SELECT 1").fetchone()
    frontend_ready = (DIST / "index.html").exists()
    return {"status": "ok", "service": "AI行情助手", "phase": "V7 实时K线与新闻情报", "version": VERSION,
            "desktop": os.environ.get("TRADING_AI_DESKTOP") == "1", "database": "ok",
            "database_path": str(DB_PATH), "frontend": "ok" if frontend_ready else "missing"}


@app.get("/api/realtime/time")
def realtime_time() -> dict:
    return ok({"serverTimestamp": utc_now()})


@app.get("/api/realtime/snapshot")
async def realtime_snapshot() -> dict:
    return ok(await realtime_manager.store.snapshots())


@app.get("/api/news/providers")
def news_providers() -> dict:
    return ok({"providers":["EastmoneyAnnouncementProvider","CoinDeskProvider","CointelegraphProvider",
                            "CNBCMarketsProvider","BBCBusinessProvider","YahooFinanceProvider"],
               "health":load_provider_health(), "active_source":"multiple independent public providers",
               "nlp_method":"financial-event-rules-v2 deterministic rules",
               "finbert_status":"NOT_INSTALLED",
               "notice":"Provider 可独立降级；当前分析是可审计规则引擎，不冒充 FinBERT/LLM。"})


@app.get("/api/news/intelligence")
async def news_intelligence(symbol: str | None = None, asset_type: str = "stock", name: str | None = None,
                            force_refresh: bool = False, market: str | None = None,
                            category: str | None = None, direction: str | None = None,
                            keyword: str | None = None, hours: int | None = Query(default=None, ge=1, le=24*365),
                            page: int = Query(default=1, ge=1), page_size: int = Query(default=20, ge=1, le=100)) -> dict:
    normalized = resolved_symbol(symbol, asset_type) if symbol else symbol
    rows, statuses = await collect_news(normalized, name, market, keyword, 50)
    technical_score = volume_ratio = None
    if normalized:
        states = await realtime_manager.store.asset_states(asset_type, normalized)
        usable = next((state for state in states if state.indicators), None)
        if usable and usable.indicators:
            technical_score = usable.indicators.get("score")
            volume_ratio = usable.indicators.get("latest", {}).get("volume_ratio")
    live = build_intelligence(rows, normalized, name, technical_score, volume_ratio,
                              len(load_news_intelligence(normalized)))
    live["persisted"] = await asyncio.to_thread(save_news_intelligence, live["all_news"], normalized)
    await asyncio.to_thread(save_provider_health, statuses)
    feed = await asyncio.to_thread(query_news_intelligence, normalized, market, category, direction,
                                   keyword, hours, page, page_size)
    # Database is the explicit fallback when one/all live providers fail.
    final_rows = feed["items"]
    result = build_intelligence(final_rows, normalized, name, technical_score, volume_ratio,
                                len(load_news_intelligence(normalized)))
    result.update(feed); result["all_news"] = final_rows
    result["top_news"] = final_rows[:10]
    result["provider_statuses"] = statuses
    result["provider_errors"] = [x for x in statuses if x["status"] != "HEALTHY"]
    result["cache_fallback"] = not bool(rows) and bool(final_rows)
    result["persisted"] = live["persisted"]
    return ok(result, "真实新闻与缓存降级链路完成", source="independent public providers")


@app.get("/api/news/feed")
def news_feed(symbol: str | None = None, market: str | None = None, category: str | None = None,
              direction: str | None = None, keyword: str | None = None,
              hours: int | None = Query(default=None, ge=1, le=24*365), page: int = Query(default=1, ge=1),
              page_size: int = Query(default=20, ge=1, le=100)) -> dict:
    return ok(query_news_intelligence(symbol,market,category,direction,keyword,hours,page,page_size),
              "新闻筛选与分页完成",source="local normalized news database")


@app.post("/api/news/backtest")
async def news_backtest(body: NewsBacktestRequest) -> dict:
    symbol = resolved_symbol(body.symbol, body.asset_type)
    historical_status=[]
    if body.refresh_historical:
        rows,historical_status=await collect_historical_news(symbol,limit=100,pages=3)
        if rows:
            analyzed=build_intelligence(rows,symbol)["all_news"]
            await asyncio.to_thread(save_news_intelligence,analyzed,symbol)
    events = load_news_intelligence(symbol)
    data, source = await _kline(body.asset_type, symbol, "1d", 1200)
    confidence=body.min_confidence/100 if body.min_confidence>1 else body.min_confidence
    result = await asyncio.to_thread(event_backtest, events, data["candles"], body.event_type,
                                     body.direction, body.min_impact, confidence, body.horizon)
    result["persisted_outcomes"]=await asyncio.to_thread(save_historical_event_outcomes,symbol,result["outcomes"])
    result.update({"symbol":symbol,"asset_type":body.asset_type,"interval":"1d","requested_interval":body.interval,
                   "data_source":source,"news_source":"persisted public headlines and exchange announcements",
                   "historical_provider_statuses":historical_status})
    return ok(result, "Point-in-Time 新闻事件回测完成", source=source)


@app.get("/api/news/item/{news_id}")
def news_item(news_id: str) -> dict:
    item=get_news_intelligence(news_id)
    if not item: raise HTTPException(404,"新闻不存在")
    return ok(item,"新闻详情")


@app.websocket("/api/realtime/ws")
async def realtime_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    queue = realtime_manager.bus.subscribe()
    send_lock=asyncio.Lock()

    async def send(payload: dict) -> None:
        # Starlette/websockets cannot safely accept concurrent frame writes.
        try:
            async with send_lock: await websocket.send_json(payload)
        except RuntimeError as exc:
            if "once a close message has been sent" in str(exc):
                raise WebSocketDisconnect(code=1000) from exc
            raise

    async def forward() -> None:
        while True:
            await send(await queue.get())

    async def receive() -> None:
        while True:
            message = await websocket.receive_json()
            if message.get("action") == "subscribe":
                state = await realtime_manager.subscribe(str(message.get("asset_type")), str(message.get("symbol")),
                                                         str(message.get("interval") or "1m"))
                await send({"type":"snapshot","key":realtime_manager.store.key(state.asset_type,state.symbol,state.interval),
                            "data":state.snapshot(),"serverTimestamp":utc_now()})
            elif message.get("action") == "ping":
                await send({"type":"pong","data":{"serverTimestamp":utc_now()}})
    # Establish protocol ordering before the global event bus can forward data.
    await send({"type":"hello","data":{"status":"CONNECTED","serverTimestamp":utc_now()}})
    sender=asyncio.create_task(forward());receiver=asyncio.create_task(receive())
    try:
        done,pending=await asyncio.wait({sender,receiver},return_when=asyncio.FIRST_COMPLETED)
        for task in pending: task.cancel()
        await asyncio.gather(*pending,return_exceptions=True)
        for task in done:
            error=task.exception()
            if error and not isinstance(error,WebSocketDisconnect): raise error
    except WebSocketDisconnect:
        pass
    finally:
        realtime_manager.bus.unsubscribe(queue)


@app.get("/api/market/overview")
async def market_overview() -> dict:
    indices = [("000001", "stock"), ("399001", "stock"), ("399006", "stock")]
    watch = [(row["symbol"], row["asset_type"]) for row in list_watchlist()]
    quotes = await fetch_quotes(list(dict.fromkeys(indices + watch)))
    return {"items": quotes, "notice": "行情仅供分析研究，不构成投资建议。数据源异常时不会生成替代数据。"}


@app.get("/api/ai/market-context")
async def ai_market_context() -> dict:
    rows, source = await crypto_kline("BTC", "15m", 240)
    frame = feature_frame(rows); availability = FeatureStore().availability(frame, "crypto")
    derivatives,rotation,macro,news,events,onchain = await asyncio.gather(
        crypto_derivatives("BTC"),_capital_rotation("crypto", "15m", "BTC", rows),macro_context(),
        news_context("BTC","crypto"),event_risk(),crypto_onchain("BTC"))
    external={"macro":macro,"news":news,"event":events,"fundamental":{"status":"NOT_APPLICABLE"},"onchain":onchain}
    flow = CapitalFlowEngine().analyze(frame, derivatives)
    regime = MarketRegimeEngine().analyze(frame, flow, availability["feature_coverage"],external)
    snapshot={"current_time":pd.Timestamp.now(tz="UTC").isoformat(),"data_timestamp":frame["timestamp_utc"].iloc[-1].isoformat(),
              "market_state":regime["primary"],"risk_appetite":regime["risk_mode"],"volatility":regime["volatility"],
              "liquidity":regime["liquidity"],"flow":flow["direction"],"sentiment":regime.get("sentiment"),
              "macro":macro.get("assets",{}),"btc":{"price":float(frame["close"].iloc[-1]),"source":source},
              "eth":{"status":"AVAILABLE" if any(x.get("symbol")=="ETH" for x in rotation) else "NO_DATA"},
              "market_breadth":{"status":"DATA_INSUFFICIENT"},"total_crypto_market_cap":{"status":"DATA_INSUFFICIENT"},
              "btc_dominance":{"status":"DATA_INSUFFICIENT"},"major_events":events}
    return ok({"data_timestamp":frame["timestamp_utc"].iloc[-1].isoformat(),"source":source,"market_snapshot":snapshot,"market_regime":regime,
               "capital_flow":flow,"capital_rotation":rotation,"risk_alerts":(["REGIME_CHANGE_RISK"] if abs(flow["flow_acceleration"])>.08 or regime["volatility_percentile"]>.9 else []),
               "event_risk":events,"external_context":external}, source=source)


@app.get("/api/market/stock/search")
async def api_stock_search(q: str = Query(min_length=1)) -> dict: return ok(await stock_search(q))


@app.get("/api/market/crypto/search")
async def api_crypto_search(q: str = Query(min_length=1)) -> dict: return ok(await crypto_search(q))


@app.get("/api/market/stock/quote")
async def api_stock_quote(symbol: str) -> dict: return ok(await stock_quote(symbol), source="实时公开行情")


@app.get("/api/market/crypto/quote")
async def api_crypto_quote(symbol: str) -> dict: return ok(await crypto_quote(symbol), source="公开交易所 API")


async def _kline(asset_type: str, symbol: str, interval: str, limit: int):
    if asset_type == "stock": candles, source = await stock_kline(symbol, interval, limit)
    elif asset_type == "crypto": candles, source = await crypto_kline(symbol, interval, limit)
    else: raise HTTPException(400, "asset_type 必须是 stock 或 crypto")
    indicators = await asyncio.to_thread(indicator_payload, candles)
    return {"symbol": symbol, "asset_type": asset_type, "interval": interval, "candles": candles, "indicators": indicators}, source


@app.get("/api/market/stock/kline")
async def api_stock_kline(symbol: str, interval: str = "1d", limit: int = Query(400, ge=80, le=1200)) -> dict:
    data, source = await _kline("stock", symbol, interval, limit); return ok(data, source=source)


@app.get("/api/market/crypto/kline")
async def api_crypto_kline(symbol: str, interval: str = "1h", limit: int = Query(400, ge=80, le=1200)) -> dict:
    data, source = await _kline("crypto", symbol, interval, limit); return ok(data, source=source)


@app.post("/api/ai/predict")
async def api_predict(body: PredictionRequest) -> dict:
    symbol = resolved_symbol(body.symbol, body.asset_type)
    # Keep enough chronological history for genuine train/calibration/test and
    # walk-forward evaluation. Providers may return fewer real rows.
    wanted = 3000 if body.asset_type == "crypto" else (2500 if body.interval == "1d" else 1200)
    data, source = await _kline(body.asset_type, symbol, body.interval, wanted)
    result = await asyncio.to_thread(predict, data["candles"], body.interval, body.asset_type, symbol)
    result.update({"symbol": symbol, "asset_type": body.asset_type, "interval": body.interval, "data_source": source})
    derivatives, rotation, macro, news, events, fundamental, financial_history, onchain, quote_validation = await asyncio.gather(
        crypto_derivatives(symbol) if body.asset_type == "crypto" else asyncio.sleep(0,result={"status":"NOT_APPLICABLE"}),
        _capital_rotation(body.asset_type, body.interval, symbol, data["candles"]),
        macro_context(), news_context(symbol,body.asset_type), event_risk(),
        stock_fundamental(symbol) if body.asset_type == "stock" else asyncio.sleep(0,result={"status":"NOT_APPLICABLE"}),
        stock_financial_history(symbol) if body.asset_type == "stock" else asyncio.sleep(0,result={"status":"NOT_APPLICABLE"}),
        crypto_onchain(symbol) if body.asset_type == "crypto" else asyncio.sleep(0,result={"status":"NOT_APPLICABLE"}),
        cross_validate_quote(symbol,body.asset_type))
    external={"macro":macro,"news":news,"event":events,"fundamental":fundamental,
              "financial_history":financial_history,"onchain":onchain,"quote_validation":quote_validation}
    decision = await asyncio.to_thread(analyze_v3, data["candles"], result, body.interval, body.asset_type, symbol,
                                       body.account_equity, body.max_risk_percent, body.leverage,
                                       body.contract_multiplier, body.minimum_lot, derivatives, rotation, external)
    peer_rows=await _cross_asset_history(body.asset_type,body.interval,symbol,data["candles"])
    research=await asyncio.to_thread(build_research_layer,data["candles"],body.interval,body.asset_type,symbol,result,
                                     decision,source,external,peer_rows,derivatives,
                                     ([{"field":"price","sources":quote_validation.get("values"),"spread_percent":quote_validation.get("spread_percent")}]
                                      if quote_validation.get("conflict") else []))
    decision["research"]=research
    technical_engine = StrategyEngine()
    decision["technical_strategy"] = await asyncio.to_thread(
        technical_engine.analyze, data["candles"], body.interval, source)
    multi_rows, multi_sources = await _strategy_timeframe_history(body.asset_type, symbol, body.interval, data["candles"], source)
    multi = await asyncio.to_thread(technical_engine.analyze_multi_timeframe, multi_rows, multi_sources)
    decision["technical_strategy"]["multi_timeframe"] = multi
    factor = multi["confidence_factor"]
    if factor < 1:
        for signal in decision["technical_strategy"]["signals"]:
            signal["confidence"] = round(signal["confidence"] * factor, 2)
        decision["technical_strategy"]["confluence"]["score"] = round(decision["technical_strategy"]["confluence"]["score"] * factor, 2)
        decision["technical_strategy"]["confluence"]["higher_timeframe_penalty"] = factor
    primary = result["predictions"].get("1H") or next((item for item in result["predictions"].values() if item.get("prediction")), {})
    technical = decision["technical_strategy"]; tech_signal = technical["confluence"]["signal"]
    model_direction = primary.get("prediction", "FLAT")
    aligned = (tech_signal == "BUY" and model_direction == "UP") or (tech_signal == "SELL" and model_direction == "DOWN")
    positive_ev = technical["risk_plan"]["expected_value"] is not None and technical["risk_plan"]["expected_value"] > 0
    if aligned and positive_ev and not multi["conflict"]:
        final_action = tech_signal
        final_reason = "CALIBRATED_MODEL_AND_DEDUPLICATED_STRATEGIES_ALIGNED_WITH_POSITIVE_EV"
    elif multi["conflict"]:
        final_action = "WATCH"
        final_reason = "HIGHER_TIMEFRAME_CONFLICT"
    else:
        final_action = "HOLD"
        final_reason = "MODEL_STRATEGY_MISMATCH_OR_NON_POSITIVE_EV"
    decision["v5_final_decision"] = {
        "action": final_action, "reason": final_reason, "direction": technical["confluence"]["direction"],
        "probabilities": primary.get("probabilities"), "expected_return": research.get("return_distribution",{}).get("expected_return"),
        "expected_volatility": research.get("return_distribution",{}).get("expected_volatility"),
        "entry": technical["risk_plan"]["entry"], "stop": technical["risk_plan"]["stop_loss"],
        "take_profits": technical["risk_plan"]["take_profits"], "expected_value": technical["risk_plan"]["expected_value"],
        "strategy_confluence": technical["confluence"]["score"], "model_confidence": primary.get("confidence_score"),
        "data_quality": technical["data_quality"]["score"], "market_regime": technical["market_regime"],
        "bullish_evidence": technical["evidence_chain"]["bullish"], "bearish_evidence": technical["evidence_chain"]["bearish"],
        "neutral_evidence": technical["evidence_chain"]["neutral"],
        "invalidation_conditions": technical["risk_plan"]["invalidation_conditions"]}
    # Persist only observed/calculated feature values. This table is separate
    # from final predictions and can be audited by timestamp and source.
    observed_frame=feature_frame(data["candles"])
    await asyncio.to_thread(save_feature_observations,symbol,observed_frame["timestamp_utc"].iloc[-1].isoformat(),
                            observed_frame,source,research["data_quality"]["grade"])
    await asyncio.to_thread(save_external_feature_observations,symbol,research["live_data_collected_at"],external,
                            research["data_quality"]["grade"])
    signed_strengths={signal["strategy"]:(signal["strength"] if signal["signal"]=="BUY" else -signal["strength"] if signal["signal"]=="SELL" else 0)
                      for signal in decision["technical_strategy"]["signals"] if signal["status"]=="AVAILABLE"}
    await asyncio.to_thread(save_external_feature_observations,symbol,research["live_data_collected_at"],
                            {"v5_strategy":{"source":"causal StrategyEngine v5","signals":signed_strengths,
                                            "confluence":decision["technical_strategy"]["confluence"]["score"]}},
                            research["data_quality"]["grade"])
    resolved = await asyncio.to_thread(resolve_prediction_history, symbol, data["candles"])
    saved = await asyncio.to_thread(save_prediction_history, symbol, body.asset_type, body.interval, result, decision)
    result["decision_center"] = decision; result["history"] = {"resolved":resolved,"saved":saved}
    return ok(result, message="V5 因果技术策略、量化研究审计与交易决策完成", source=source)


async def _realtime_prediction(symbol: str, asset_type: str, interval: str, reasons: list[str]) -> dict:
    result = await api_predict(PredictionRequest(symbol=symbol,asset_type=asset_type,interval=interval))
    result["realtime"] = {"mode":"LIVE","trigger_reasons":reasons,"generated_at":utc_now()}
    return result


realtime_manager.set_prediction_callback(_realtime_prediction)


async def _cross_asset_history(asset_type: str, interval: str, symbol: str, current: list[dict]) -> dict[str,list[dict]]:
    peers: dict[str,list[dict]]={}
    candidates=(["BTC","ETH"] if asset_type=="crypto" else ["000001","399001","399006","000300"])
    async def fetch(candidate):
        try:
            rows,_=await (crypto_kline(candidate,interval,800) if asset_type=="crypto" else stock_kline(candidate,interval,800))
            return candidate,rows
        except Exception:return candidate,[]
    fetched=await asyncio.gather(*(fetch(item) for item in candidates if item!=symbol))
    peers.update({name:rows for name,rows in fetched if rows})
    history=await macro_history(interval)
    peers.update(history.get("assets",{}))
    return peers


async def _strategy_timeframe_history(asset_type: str, symbol: str, current_interval: str,
                                      current: list[dict], current_source: str) -> tuple[dict[str,list[dict]],dict[str,str]]:
    timeframes = ("1d", "4h", "1h", "15m", "5m")
    rows_by = {current_interval: current}; sources = {current_interval: current_source}
    async def fetch(timeframe: str):
        try:
            rows, provider = await (crypto_kline(symbol,timeframe,500) if asset_type=="crypto" else stock_kline(symbol,timeframe,500))
            return timeframe, rows, provider
        except Exception as exc:
            return timeframe, [], f"UNAVAILABLE:{type(exc).__name__}"
    fetched = await asyncio.gather(*(fetch(tf) for tf in timeframes if tf != current_interval))
    for timeframe, rows, provider in fetched:
        if rows: rows_by[timeframe] = rows
        sources[timeframe] = provider
    return rows_by, sources


async def _capital_rotation(asset_type: str, interval: str, symbol: str, current: list[dict]) -> list[dict]:
    candidates = (["BTC","ETH","SOL"] if asset_type == "crypto" else [symbol,"000001","399001","399006"])
    candidates = list(dict.fromkeys(candidates)); rows_by_symbol = {symbol: current}
    async def fetch(candidate):
        try:
            rows, provider = await (crypto_kline(candidate, interval, 240) if asset_type=="crypto" else stock_kline(candidate, interval, 240))
            return candidate, rows, provider
        except Exception: return candidate, None, None
    fetched = await asyncio.gather(*(fetch(candidate) for candidate in candidates if candidate != symbol))
    providers={symbol:"same request"}
    for candidate,rows,provider in fetched:
        if rows: rows_by_symbol[candidate]=rows;providers[candidate]=provider
    output=[]
    for candidate,rows in rows_by_symbol.items():
        sample=rows[-min(40,len(rows)):]
        if len(sample)<8: continue
        returns=float(sample[-1]["close"] / sample[0]["close"] - 1);signed=0.0;gross=0.0
        for previous,item in zip(sample,sample[1:]):
            turnover=float(item.get("amount") or item["close"]*item["volume"]);gross+=abs(turnover)
            signed += turnover * (1 if item["close"]>previous["close"] else -1 if item["close"]<previous["close"] else 0)
        output.append({"symbol":candidate,"return":round(returns,5),"flow_ratio":round(signed/max(gross,1e-12),5),
                       "rotation_score":round(returns*4+signed/max(gross,1e-12),5),"source":providers[candidate]})
    return sorted(output,key=lambda item:item["rotation_score"],reverse=True)


@app.post("/api/ai/decision")
async def api_decision(body: PredictionRequest) -> dict: return await api_predict(body)


@app.get("/api/ai/history")
def ai_history(limit: int = Query(100,ge=1,le=1000)) -> dict: return ok(prediction_history(limit))


@app.get("/api/ai/statistics")
def ai_statistics() -> dict: return ok(prediction_statistics())


@app.get("/api/ai/portfolio-risk")
async def ai_portfolio_risk() -> dict:
    positions=paper_snapshot()["positions"]
    if len(positions)<2:return ok({"status":"DATA_INSUFFICIENT","reason":"模拟账户至少需要两个持仓"})
    async def fetch(position):
        try:
            rows,_=await (crypto_kline(position["symbol"],"1h",800) if position["asset_type"]=="crypto" else stock_kline(position["symbol"],"1h",800))
            return position,rows
        except Exception:return position,[]
    fetched=await asyncio.gather(*(fetch(position) for position in positions))
    series={};notionals={}
    for position,rows in fetched:
        if not rows:continue
        local=pd.DataFrame(rows);local["timestamp"]=pd.to_datetime(local["timestamp"],utc=True)
        series[position["symbol"]]=local.set_index("timestamp")["close"].pct_change()
        notionals[position["symbol"]]=float(position["quantity"])*float(rows[-1]["close"])
    matrix=pd.concat(series,axis=1) if series else pd.DataFrame()
    return ok(PortfolioRiskEngine().analyze(matrix,notionals))


@app.post("/api/backtest/run")
async def api_backtest(body: BacktestRequest) -> dict:
    symbol = resolved_symbol(body.symbol, body.asset_type)
    data, source = await _kline(body.asset_type, symbol, body.interval, body.limit)
    fee = body.fee_rate if body.fee_rate is not None else (.001 if body.asset_type == "crypto" else .0003)
    legacy_strategies = {"ma", "macd", "rsi", "ai", "ai_technical"}
    if body.strategy in SIGNAL_KEYS and body.strategy not in legacy_strategies:
        result = await asyncio.to_thread(strategy_backtest, data["candles"], body.strategy, body.interval,
                                         fee, body.slippage_rate)
        result["initial_cash"] = body.initial_cash
        result["return_percent"] = round(((math.prod(1 + trade["return"] for trade in result["trades"]) - 1) * 100), 2) if result["trades"] else 0
        result["final_cash"] = round(body.initial_cash * (1 + result["return_percent"] / 100), 2)
        result["max_drawdown_percent"] = round((result.get("max_drawdown") or 0) * 100, 2)
        result["win_rate_percent"] = round((result.get("win_rate") or 0) * 100, 2)
        result["trade_count"] = result["number_of_trades"]
        result["sharpe_ratio"] = result["sharpe"]; result["sortino_ratio"] = result["sortino"]
        result["fee_rate"] = fee; result["slippage_rate"] = body.slippage_rate
        result["equity_curve"] = []
    else:
        result = await asyncio.to_thread(run_backtest, data["candles"], body.strategy, body.initial_cash, fee,
                                         body.slippage_rate, body.interval, body.asset_type)
    result.update({"symbol": symbol, "asset_type": body.asset_type, "interval": body.interval, "data_source": source})
    result["run_id"] = save_backtest(symbol, body.asset_type, body.strategy, body.interval, result)
    return ok(result, message="回测完成", source=source)


@app.get("/api/backtest/history")
def backtest_history(limit: int = Query(30,ge=1,le=100)) -> dict: return ok(list_backtests(limit))


@app.get("/api/strategy/catalog")
def strategy_catalog() -> dict:
    return ok({"count": len(SIGNAL_KEYS), "strategies": list(SIGNAL_KEYS),
               "unavailable_without_external_data": ["order_flow", "options"],
               "causality": "confirmed swing available_at; signal close T; execution open T+1"})


@app.get("/api/strategy/leaderboard")
def strategy_leaderboard(limit: int = Query(200, ge=1, le=1000)) -> dict:
    latest: dict[tuple[str,str,str],dict] = {}
    for run in list_backtests(limit):
        result = run["result"]
        if run["strategy"] not in SIGNAL_KEYS or "number_of_trades" not in result: continue
        key = (run["symbol"], run["interval"], run["strategy"])
        if key not in latest:
            latest[key] = {"symbol":run["symbol"],"interval":run["interval"],"strategy":run["strategy"],
                           "created_at":run["created_at"],**{name:result.get(name) for name in
                           ("number_of_trades","win_rate","profit_factor","expectancy","sharpe","sortino","max_drawdown","mae","mfe","status")}}
    rows = sorted(latest.values(), key=lambda item: (item.get("expectancy") or -999, item.get("sharpe") or -999), reverse=True)
    return ok({"status":"AVAILABLE" if rows else "NO_VALIDATED_RUNS","rows":rows,
               "notice":"仅显示用户实际运行并保存的因果历史回测；无记录时不填成绩。"})


@app.post("/api/strategy/analyze")
async def strategy_analyze(body: PredictionRequest) -> dict:
    symbol = resolved_symbol(body.symbol, body.asset_type)
    data, source = await _kline(body.asset_type, symbol, body.interval, 1200)
    result = await asyncio.to_thread(StrategyEngine().analyze, data["candles"], body.interval, source)
    result.update({"symbol": symbol, "asset_type": body.asset_type, "interval": body.interval, "data_source": source})
    return ok(result, message="30 类因果技术策略分析完成", source=source)


@app.post("/api/strategy/backtest")
async def strategy_lab(body: StrategyBacktestRequest) -> dict:
    if body.strategy not in SIGNAL_KEYS: raise HTTPException(400, "未知 V5 策略")
    symbol = resolved_symbol(body.symbol, body.asset_type)
    data, source = await _kline(body.asset_type, symbol, body.interval, body.limit)
    rows = data["candles"]
    if body.start_time or body.end_time:
        frame = pd.DataFrame(rows); stamps = pd.to_datetime(frame["timestamp"], utc=True)
        mask = pd.Series(True, index=frame.index)
        if body.start_time:
            start=pd.Timestamp(body.start_time);start=start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC");mask &= stamps >= start
        if body.end_time:
            end=pd.Timestamp(body.end_time);end=end.tz_localize("UTC") if end.tzinfo is None else end.tz_convert("UTC");mask &= stamps <= end
        rows = frame.loc[mask].to_dict("records")
    if len(rows) < 200: raise HTTPException(400, "所选时间范围真实 K 线不足 200 根")
    fee = body.fee_rate if body.fee_rate is not None else (.001 if body.asset_type == "crypto" else .0003)
    result = await asyncio.to_thread(strategy_backtest, rows, body.strategy, body.interval, fee, body.slippage_rate, 8, 80, body.parameters)
    if body.walk_forward:
        result["walk_forward"] = await asyncio.to_thread(walk_forward_strategy, rows, body.strategy, body.interval)
    if body.optimize:
        result["parameter_optimization"] = await asyncio.to_thread(optimize_strategy_parameters, rows, body.strategy, body.interval, fee, body.slippage_rate)
    compounded = math.prod(1 + trade["return"] for trade in result["trades"]) if result["trades"] else 1.0
    result.update({"initial_cash":body.initial_cash,"final_cash":round(body.initial_cash*compounded,2),
                   "return_percent":round((compounded-1)*100,2),"max_drawdown_percent":round((result.get("max_drawdown") or 0)*100,2),
                   "win_rate_percent":round((result.get("win_rate") or 0)*100,2),"trade_count":result["number_of_trades"],
                   "sharpe_ratio":result["sharpe"],"sortino_ratio":result["sortino"],"fee_rate":fee,
                   "slippage_rate":body.slippage_rate,
                   "equity_curve":[{"timestamp":trade["execution_time"],"equity":round(body.initial_cash*math.prod(1+t["return"] for t in result["trades"][:index+1]),2)} for index,trade in enumerate(result["trades"])]})
    result.update({"symbol": symbol, "asset_type": body.asset_type, "interval": body.interval, "data_source": source})
    result["run_id"] = save_backtest(symbol, body.asset_type, body.strategy, body.interval, result)
    return ok(result, message="策略实验室样本外验证完成", source=source)


@app.post("/api/strategy/incremental-experiment")
async def strategy_incremental(body: StrategyBacktestRequest) -> dict:
    symbol = resolved_symbol(body.symbol, body.asset_type)
    data, source = await _kline(body.asset_type, symbol, body.interval, body.limit)
    result = await asyncio.to_thread(strategy_incremental_experiment, data["candles"], body.interval)
    result["ml_ablation"] = await asyncio.to_thread(ml_ict_incremental_experiment, data["candles"], body.interval, body.asset_type)
    result.update({"symbol": symbol, "asset_type": body.asset_type, "interval": body.interval, "data_source": source})
    return ok(result, message="Fib/FVG/BOS 增量实验完成", source=source)


@app.post("/api/paper/order")
async def paper_order(body: PaperOrderRequest) -> dict:
    asset_type = body.asset_type.lower(); symbol = resolved_symbol(body.symbol, asset_type)
    quote = await (crypto_quote(symbol) if asset_type == "crypto" else stock_quote(symbol)); price = float(quote["price"])
    quantity = body.quantity; fee_rate = .001 if asset_type == "crypto" else .0003
    if quantity is None:
        if body.amount is None: raise HTTPException(400, "quantity 或 amount 至少填写一个")
        quantity = body.amount / (price * (1 + fee_rate)) if body.side.upper() == "BUY" else body.amount / price
    order_type=body.order_type.upper()
    if order_type=="MARKET":
        order = execute_paper_order(symbol, quote["name"], asset_type, body.side, price, quantity, fee_rate)
        return ok(order, message="模拟市价订单已成交", source=quote["source"])
    if order_type!="LIMIT" or body.price is None:raise HTTPException(400,"限价单必须填写有效限价")
    should_fill=(body.side.upper()=="BUY" and price<=body.price) or (body.side.upper()=="SELL" and price>=body.price)
    if should_fill:
        pending=create_limit_order(symbol,quote["name"],asset_type,body.side,body.price,quantity,fee_rate)
        order=fill_limit_order(pending["id"],price,fee_rate)
        return ok(order,message="模拟限价订单已按当前真实行情成交",source=quote["source"])
    order=create_limit_order(symbol,quote["name"],asset_type,body.side,body.price,quantity,fee_rate)
    return ok(order,message="模拟限价订单已挂单，资金或持仓已冻结",source=quote["source"])


async def _marked_snapshot() -> dict:
    snapshot = paper_snapshot(); marked = []
    # Re-evaluate pending limits only against observed provider quotes.
    for order in [x for x in snapshot["orders"] if x.get("status")=="pending"]:
        try:
            q=await (crypto_quote(order["symbol"],True) if order["asset_type"]=="crypto" else stock_quote(order["symbol"],True))
            fill_limit_order(order["id"],float(q["price"]),.001 if order["asset_type"]=="crypto" else .0003)
        except Exception:pass
    snapshot=paper_snapshot()
    for position in snapshot["positions"]:
        try:
            quote = await (crypto_quote(position["symbol"]) if position["asset_type"] == "crypto" else stock_quote(position["symbol"])); price = quote["price"]
            value = position["quantity"] * price; cost = position["quantity"] * position["average_cost"]
            marked.append({**position, "current_price": price, "market_value": round(value, 2), "unrealized_pnl": round(value-cost, 2),
                           "return_percent": round((price/position["average_cost"]-1)*100, 2), "quote_source": quote["source"]})
        except Exception as exc: marked.append({**position, "current_price": None, "market_value": None, "unrealized_pnl": None, "return_percent": None, "quote_error": str(exc)})
    snapshot["positions"] = marked
    for account in snapshot["accounts"]:
        value = sum(p["market_value"] or 0 for p in marked if p["currency"] == account["currency"])
        account["available_cash"]=account["cash"];account["position_market_value"]=round(value,2)
        account["total_equity"] = round(account["cash"]+account.get("frozen_cash",0)+value, 2); account["cumulative_pnl"]=round(account["total_equity"]-account["initial_cash"],2);account["return_percent"] = round((account["total_equity"]/account["initial_cash"]-1)*100, 2)
        account["today_pnl"]=paper_daily_pnl(account["currency"],account["total_equity"],utc_now()[:10])
    return snapshot


@app.get("/api/paper/account")
async def paper_account() -> dict: return ok((await _marked_snapshot())["accounts"])


@app.get("/api/paper/snapshot")
async def paper_complete_snapshot() -> dict:
    """Return one internally consistent mark for all paper-trading panels."""
    return ok(await _marked_snapshot())


@app.get("/api/paper/positions")
async def paper_positions() -> dict: return ok((await _marked_snapshot())["positions"])


@app.get("/api/paper/orders")
def paper_orders() -> dict: return ok(paper_snapshot()["orders"])


@app.post("/api/paper/orders/{order_id}/cancel")
def paper_cancel(order_id: int) -> dict:
    try:return ok(cancel_paper_order(order_id),"模拟挂单已撤销，冻结资产已释放")
    except ValueError as exc:raise HTTPException(400,str(exc))


@app.post("/api/paper/reset")
def paper_reset() -> dict:
    reset_paper_accounts();return ok({"reset":True},"模拟账户已恢复初始资金")


@app.get("/api/watchlist")
def get_watchlist() -> dict:
    items = list_watchlist(); return {"success": True, "items": items, "data": items, "message": "成功"}


@app.post("/api/watchlist", status_code=201)
def create_watchlist(item: WatchlistItem) -> dict:
    asset_type = item.asset_type.lower()
    if asset_type not in {"stock", "crypto"}: raise HTTPException(400, "asset_type 必须是 stock 或 crypto")
    symbol = resolved_symbol(item.symbol, asset_type)
    add_watchlist(symbol, asset_type, item.name); return ok({"symbol": symbol, "asset_type": asset_type, "name": item.name}, "已加入自选")


@app.delete("/api/watchlist/{symbol}")
def delete_watchlist(symbol: str) -> dict: remove_watchlist(symbol.upper()); return ok({"symbol": symbol.upper()}, "已移出自选")


@app.get("/api/quotes/{asset_type}/{symbol}")
async def legacy_quote(asset_type: str, symbol: str) -> dict: return await (crypto_quote(symbol) if asset_type == "crypto" else stock_quote(symbol))


@app.get("/api/search")
async def legacy_search(q: str = "") -> dict:
    stocks, cryptos = await asyncio.gather(stock_search(q or "000001"), crypto_search(q or "BTC")); return {"items": stocks+cryptos}


DIST = Path(os.environ.get("TRADING_AI_FRONTEND_DIR", ROOT / "frontend" / "dist"))
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        candidate = (DIST / path).resolve()
        if path and candidate.is_file() and DIST.resolve() in candidate.parents: return FileResponse(candidate)
        return FileResponse(DIST / "index.html")
