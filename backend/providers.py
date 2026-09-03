from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

import httpx


CRYPTO_NAMES = {"BTC": "比特币", "ETH": "以太坊", "SOL": "Solana", "BNB": "BNB"}
STOCKS = {
    "000001": ("上证指数", "index"),
    "399001": ("深证成指", "index"),
    "399006": ("创业板指", "index"),
    "600519": ("贵州茅台", "stock"),
    "300750": ("宁德时代", "stock"),
    "002594": ("比亚迪", "stock"),
}


@dataclass
class Quote:
    symbol: str
    name: str
    asset_type: str
    price: float | None
    change_percent: float | None
    currency: str
    source: str | None
    available: bool
    message: str | None = None
    updated_at: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _crypto_binance(client: httpx.AsyncClient, symbol: str) -> Quote:
    response = await client.get("https://api.binance.com/api/v3/ticker/24hr", params={"symbol": f"{symbol}USDT"})
    response.raise_for_status()
    data = response.json()
    return Quote(symbol, CRYPTO_NAMES.get(symbol, symbol), "crypto", float(data["lastPrice"]),
                 float(data["priceChangePercent"]), "USDT", "Binance", True, updated_at=_now())


async def _crypto_okx(client: httpx.AsyncClient, symbol: str) -> Quote:
    response = await client.get("https://www.okx.com/api/v5/market/ticker", params={"instId": f"{symbol}-USDT"})
    response.raise_for_status()
    rows = response.json().get("data", [])
    if not rows:
        raise ValueError("OKX 未返回行情")
    data = rows[0]
    last, open24h = float(data["last"]), float(data["open24h"])
    change = (last / open24h - 1) * 100 if open24h else 0
    return Quote(symbol, CRYPTO_NAMES.get(symbol, symbol), "crypto", last, change, "USDT", "OKX", True,
                 updated_at=datetime.fromtimestamp(int(data["ts"]) / 1000, tz=timezone.utc).isoformat())


async def _crypto_coinbase(client: httpx.AsyncClient, symbol: str) -> Quote:
    response = await client.get(f"https://api.exchange.coinbase.com/products/{symbol}-USDT/stats")
    response.raise_for_status()
    data = response.json()
    last, open24h = float(data["last"]), float(data["open"])
    change = (last / open24h - 1) * 100 if open24h else 0
    return Quote(symbol, CRYPTO_NAMES.get(symbol, symbol), "crypto", last, change, "USDT", "Coinbase（备用）",
                 True, updated_at=_now())


async def get_crypto_quote(client: httpx.AsyncClient, symbol: str) -> Quote:
    symbol = symbol.upper().replace("/USDT", "").replace("-USDT", "")
    errors = []
    for provider in (_crypto_binance, _crypto_okx, _crypto_coinbase):
        try:
            return await provider(client, symbol)
        except Exception as exc:
            errors.append(f"{provider.__name__.replace('_crypto_', '').upper()}: {type(exc).__name__}")
    return Quote(symbol, CRYPTO_NAMES.get(symbol, symbol), "crypto", None, None, "USDT", None, False,
                 "数据源暂时不可用（" + "；".join(errors) + "）")


def _eastmoney_secid(symbol: str) -> str:
    if symbol.startswith(("5", "6", "9")) or symbol == "000001":
        return f"1.{symbol}"
    return f"0.{symbol}"


async def get_stock_quote(client: httpx.AsyncClient, symbol: str) -> Quote:
    symbol = symbol.strip()
    name, kind = STOCKS.get(symbol, (symbol, "stock"))
    errors = []
    try:
        response = await client.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={"secid": _eastmoney_secid(symbol), "fields": "f43,f57,f58,f116,f169,f170"},
        )
        response.raise_for_status()
        data = response.json().get("data")
        if not data or data.get("f43") in (None, "-"):
            raise ValueError("未返回有效行情")
        return Quote(symbol, data.get("f58") or name, kind, float(data["f43"]) / 100,
                     float(data["f170"]) / 100, "CNY", "东方财富公开接口", True, updated_at=_now())
    except Exception as exc:
        errors.append(f"东方财富: {type(exc).__name__}")

    try:
        market = "sh" if symbol.startswith(("5", "6", "9")) or symbol == "000001" else "sz"
        response = await client.get(f"https://qt.gtimg.cn/q={market}{symbol}")
        response.raise_for_status()
        text = response.content.decode("gbk", errors="replace")
        values = text.split('"', 1)[1].rsplit('"', 1)[0].split("~")
        if len(values) < 33 or not values[3]:
            raise ValueError("未返回有效行情")
        return Quote(symbol, values[1] or name, kind, float(values[3]), float(values[32]), "CNY",
                     "腾讯证券公开接口（备用）", True, updated_at=_now())
    except Exception as exc:
        errors.append(f"腾讯证券: {type(exc).__name__}")
        return Quote(symbol, name, kind, None, None, "CNY", None, False,
                     "数据源暂时不可用（" + "；".join(errors) + "）")


async def fetch_quotes(items: Iterable[tuple[str, str]]) -> list[dict]:
    timeout = httpx.Timeout(8.0, connect=5.0)
    headers = {"User-Agent": "Mozilla/5.0 TradingAI/0.1"}
    async with httpx.AsyncClient(timeout=timeout, headers=headers, follow_redirects=True) as client:
        ordered = list(items)
        crypto_tasks = {i: get_crypto_quote(client, s) for i, (s, t) in enumerate(ordered) if t == "crypto"}
        results: list[Quote | None] = [None] * len(ordered)
        if crypto_tasks:
            crypto_results = await asyncio.gather(*crypto_tasks.values())
            for index, result in zip(crypto_tasks, crypto_results):
                results[index] = result
        # Several Chinese quote endpoints close connections under bursts. Serial calls
        # are fast enough for a watchlist and materially more reliable on Windows.
        for index, (symbol, asset_type) in enumerate(ordered):
            if asset_type != "crypto":
                results[index] = await get_stock_quote(client, symbol)
                await asyncio.sleep(0.06)
    return [item.to_dict() for item in results if item is not None]
