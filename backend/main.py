from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from contextlib import asynccontextmanager

import pandas as pd

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai_engine import feature_frame, predict
from .backtest import run_backtest
from .database import (DB_PATH, add_watchlist, connection, execute_paper_order, init_db, list_backtests, list_watchlist,
                       paper_snapshot, prediction_history, prediction_statistics, remove_watchlist,
                       resolve_prediction_history, save_backtest, save_external_feature_observations,
                       save_feature_observations, save_prediction_history)
from .indicators import indicator_payload
from .market import (crypto_derivatives, crypto_kline, crypto_onchain, crypto_quote, crypto_search, event_risk,
                     cross_validate_quote, macro_context, macro_history, news_context, normalize_crypto, stock_fundamental, stock_kline, stock_quote,
                     stock_financial_history, stock_search)
from .providers import fetch_quotes
from .feature_services import FeatureStore
from .v3_engines import CapitalFlowEngine, MarketRegimeEngine, analyze_v3
from .v4_research import PortfolioRiskEngine, build_research_layer

ROOT = Path(__file__).resolve().parent.parent
VERSION = json.loads((ROOT / "version.json").read_text(encoding="utf-8"))["version"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="AI行情助手", version=VERSION, docs_url="/api/docs", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


def ok(data=None, message="成功", source=None) -> dict:
    result = {"success": True, "message": message, "data": data}
    if source: result["source"] = source
    return result


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


class PaperOrderRequest(BaseModel):
    symbol: str
    asset_type: str
    side: str
    quantity: float | None = Field(default=None, gt=0)
    amount: float | None = Field(default=None, gt=0)


@app.get("/api/health")
def health() -> dict:
    with connection() as conn:
        conn.execute("SELECT 1").fetchone()
    frontend_ready = (DIST / "index.html").exists()
    return {"status": "ok", "service": "AI行情助手", "phase": "V4 量化研究审计", "version": VERSION,
            "desktop": os.environ.get("TRADING_AI_DESKTOP") == "1", "database": "ok",
            "database_path": str(DB_PATH), "frontend": "ok" if frontend_ready else "missing"}


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
    symbol = normalize_crypto(body.symbol) if body.asset_type == "crypto" else body.symbol
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
    # Persist only observed/calculated feature values. This table is separate
    # from final predictions and can be audited by timestamp and source.
    observed_frame=feature_frame(data["candles"])
    await asyncio.to_thread(save_feature_observations,symbol,observed_frame["timestamp_utc"].iloc[-1].isoformat(),
                            observed_frame,source,research["data_quality"]["grade"])
    await asyncio.to_thread(save_external_feature_observations,symbol,research["live_data_collected_at"],external,
                            research["data_quality"]["grade"])
    resolved = await asyncio.to_thread(resolve_prediction_history, symbol, data["candles"])
    saved = await asyncio.to_thread(save_prediction_history, symbol, body.asset_type, body.interval, result, decision)
    result["decision_center"] = decision; result["history"] = {"resolved":resolved,"saved":saved}
    return ok(result, message="V4 量化研究审计与交易决策完成", source=source)


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
    symbol = normalize_crypto(body.symbol) if body.asset_type == "crypto" else body.symbol
    data, source = await _kline(body.asset_type, symbol, body.interval, body.limit)
    fee = body.fee_rate if body.fee_rate is not None else (.001 if body.asset_type == "crypto" else .0003)
    result = await asyncio.to_thread(run_backtest, data["candles"], body.strategy, body.initial_cash, fee,
                                     body.slippage_rate, body.interval, body.asset_type)
    result.update({"symbol": symbol, "asset_type": body.asset_type, "interval": body.interval, "data_source": source})
    result["run_id"] = save_backtest(symbol, body.asset_type, body.strategy, body.interval, result)
    return ok(result, message="回测完成", source=source)


@app.get("/api/backtest/history")
def backtest_history(limit: int = Query(30,ge=1,le=100)) -> dict: return ok(list_backtests(limit))


@app.post("/api/paper/order")
async def paper_order(body: PaperOrderRequest) -> dict:
    asset_type = body.asset_type.lower(); symbol = normalize_crypto(body.symbol) if asset_type == "crypto" else body.symbol
    quote = await (crypto_quote(symbol) if asset_type == "crypto" else stock_quote(symbol)); price = float(quote["price"])
    quantity = body.quantity; fee_rate = .001 if asset_type == "crypto" else .0003
    if quantity is None:
        if body.amount is None: raise HTTPException(400, "quantity 或 amount 至少填写一个")
        quantity = body.amount / (price * (1 + fee_rate)) if body.side.upper() == "BUY" else body.amount / price
    order = execute_paper_order(symbol, quote["name"], asset_type, body.side, price, quantity, fee_rate)
    return ok(order, message="模拟订单已成交", source=quote["source"])


async def _marked_snapshot() -> dict:
    snapshot = paper_snapshot(); marked = []
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
        account["total_equity"] = round(account["cash"]+value, 2); account["return_percent"] = round((account["total_equity"]/account["initial_cash"]-1)*100, 2)
    return snapshot


@app.get("/api/paper/account")
async def paper_account() -> dict: return ok((await _marked_snapshot())["accounts"])


@app.get("/api/paper/positions")
async def paper_positions() -> dict: return ok((await _marked_snapshot())["positions"])


@app.get("/api/paper/orders")
def paper_orders() -> dict: return ok(paper_snapshot()["orders"])


@app.get("/api/watchlist")
def get_watchlist() -> dict:
    items = list_watchlist(); return {"success": True, "items": items, "data": items, "message": "成功"}


@app.post("/api/watchlist", status_code=201)
def create_watchlist(item: WatchlistItem) -> dict:
    asset_type = item.asset_type.lower()
    if asset_type not in {"stock", "crypto"}: raise HTTPException(400, "asset_type 必须是 stock 或 crypto")
    symbol = normalize_crypto(item.symbol) if asset_type == "crypto" else item.symbol.strip()
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
