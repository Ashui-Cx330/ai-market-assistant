from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai_engine import predict
from .backtest import run_backtest
from .database import (DB_PATH, add_watchlist, connection, execute_paper_order, init_db, list_backtests, list_watchlist,
                       paper_snapshot, remove_watchlist, save_backtest)
from .indicators import indicator_payload
from .market import (crypto_kline, crypto_quote, crypto_search, normalize_crypto, stock_kline,
                     stock_quote, stock_search)
from .providers import fetch_quotes

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


class BacktestRequest(BaseModel):
    symbol: str
    asset_type: str
    interval: str = "1d"
    strategy: str = "ma"
    initial_cash: float = Field(default=100000, gt=0)
    limit: int = Field(default=500, ge=100, le=1200)


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
    return {"status": "ok", "service": "AI行情助手", "phase": "功能修复版", "version": VERSION,
            "desktop": os.environ.get("TRADING_AI_DESKTOP") == "1", "database": "ok",
            "database_path": str(DB_PATH), "frontend": "ok" if frontend_ready else "missing"}


@app.get("/api/market/overview")
async def market_overview() -> dict:
    indices = [("000001", "stock"), ("399001", "stock"), ("399006", "stock")]
    watch = [(row["symbol"], row["asset_type"]) for row in list_watchlist()]
    quotes = await fetch_quotes(list(dict.fromkeys(indices + watch)))
    return {"items": quotes, "notice": "行情仅供分析研究，不构成投资建议。数据源异常时不会生成替代数据。"}


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
    data, source = await _kline(body.asset_type, symbol, body.interval, 600)
    result = await asyncio.to_thread(predict, data["candles"], body.interval)
    result.update({"symbol": symbol, "asset_type": body.asset_type, "interval": body.interval, "data_source": source})
    return ok(result, message="模型训练与预测完成", source=source)


@app.post("/api/backtest/run")
async def api_backtest(body: BacktestRequest) -> dict:
    symbol = normalize_crypto(body.symbol) if body.asset_type == "crypto" else body.symbol
    data, source = await _kline(body.asset_type, symbol, body.interval, body.limit)
    fee = .001 if body.asset_type == "crypto" else .0003
    result = await asyncio.to_thread(run_backtest, data["candles"], body.strategy, body.initial_cash, fee)
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
