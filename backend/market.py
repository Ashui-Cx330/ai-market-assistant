from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd

from .cache import cache
from .providers import CRYPTO_NAMES, STOCKS, _eastmoney_secid, get_crypto_quote, get_stock_quote

HEADERS = {"User-Agent": "Mozilla/5.0 TradingAI/0.3", "Referer": "https://quote.eastmoney.com/"}
INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D"}
STOCK_KLT = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 101}


def normalize_crypto(symbol: str) -> str:
    return symbol.upper().replace("/USDT", "").replace("-USDT", "").replace("USDT", "").strip()


async def stock_search(query: str) -> list[dict]:
    key = f"stock-search:{query.lower()}"
    if cached := cache.get(key): return cached
    async with httpx.AsyncClient(timeout=8, headers=HEADERS) as client:
        try:
            response = await client.get("https://searchapi.eastmoney.com/api/suggest/get",
                                        params={"input": query.strip(), "type": 14, "count": 15})
            response.raise_for_status()
            rows = response.json().get("QuotationCodeTable", {}).get("Data", []) or []
            results = [{"symbol": row["Code"], "name": row["Name"], "asset_type": "stock",
                        "market": row.get("SecurityTypeName", "A股"), "source": "东方财富搜索"}
                       for row in rows if row.get("Classify") in {"AStock", "Index"}]
            if results: return cache.set(key, results, 300)
        except Exception:
            pass
    q = query.lower().strip()
    results = [{"symbol": code, "name": name, "asset_type": "stock", "market": "A股", "source": "本地代码索引"}
               for code, (name, _) in STOCKS.items() if q in code.lower() or q in name.lower()]
    return cache.set(key, results, 60)


async def crypto_search(query: str) -> list[dict]:
    q = normalize_crypto(query)
    key = f"crypto-search:{q}"
    if cached := cache.get(key): return cached
    popular = set(CRYPTO_NAMES) | {"DOGE", "XRP", "ADA", "AVAX", "DOT", "LINK", "LTC", "TRX"}
    results = [{"symbol": s, "pair": f"{s}/USDT", "name": CRYPTO_NAMES.get(s, s), "asset_type": "crypto", "source": "OKX instruments"}
               for s in sorted(popular) if not q or q in s]
    if q and q not in popular:
        async with httpx.AsyncClient(timeout=10, headers=HEADERS) as client:
            try:
                response = await client.get("https://www.okx.com/api/v5/public/instruments", params={"instType": "SPOT"})
                response.raise_for_status()
                bases = {row["baseCcy"] for row in response.json().get("data", []) if row.get("quoteCcy") == "USDT" and q in row.get("baseCcy", "")}
                results.extend({"symbol": s, "pair": f"{s}/USDT", "name": s, "asset_type": "crypto", "source": "OKX instruments"} for s in sorted(bases)[:20])
            except Exception:
                pass
    return cache.set(key, results[:20], 3600)


async def stock_quote(symbol: str) -> dict:
    key = f"stock-quote:{symbol}"
    if cached := cache.get(key): return cached
    async with httpx.AsyncClient(timeout=8, headers=HEADERS, follow_redirects=True) as client:
        try:
            response = await client.get("https://push2.eastmoney.com/api/qt/stock/get",
                params={"secid": _eastmoney_secid(symbol), "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170"})
            response.raise_for_status(); data = response.json().get("data")
            if not data or data.get("f43") in (None, "-"): raise ValueError("空行情")
            result = {"symbol": data["f57"], "name": data["f58"], "asset_type": "stock", "currency": "CNY",
                      "price": data["f43"] / 100, "change": data["f169"] / 100, "change_percent": data["f170"] / 100,
                      "open": data["f46"] / 100, "previous_close": data["f60"] / 100, "high": data["f44"] / 100,
                      "low": data["f45"] / 100, "volume": data["f47"], "amount": data["f48"],
                      "source": "东方财富公开接口", "updated_at": datetime.now(timezone.utc).isoformat()}
            return cache.set(key, result, 8)
        except Exception:
            basic = await get_stock_quote(client, symbol)
            if not basic.available: raise RuntimeError(basic.message)
            market = "sh" if symbol.startswith(("5", "6", "9")) else "sz"
            response = await client.get(f"https://qt.gtimg.cn/q={market}{symbol}")
            values = response.content.decode("gbk", errors="replace").split('"', 1)[1].rsplit('"', 1)[0].split("~")
            result = {"symbol": symbol, "name": values[1], "asset_type": "stock", "currency": "CNY",
                      "price": float(values[3]), "change": float(values[31]), "change_percent": float(values[32]),
                      "open": float(values[5]), "previous_close": float(values[4]), "high": float(values[33]), "low": float(values[34]),
                      "volume": float(values[6]), "amount": float(values[37]) * 10000 if len(values) > 37 and values[37] else None,
                      "source": "腾讯证券公开接口（备用）", "updated_at": datetime.now(timezone.utc).isoformat()}
            return cache.set(key, result, 8)


async def crypto_quote(symbol: str) -> dict:
    symbol = normalize_crypto(symbol); key = f"crypto-quote:{symbol}"
    if cached := cache.get(key): return cached
    async with httpx.AsyncClient(timeout=8, headers=HEADERS, follow_redirects=True) as client:
        errors = []
        try:
            response = await client.get("https://www.okx.com/api/v5/market/ticker", params={"instId": f"{symbol}-USDT"})
            response.raise_for_status(); rows = response.json().get("data", [])
            if not rows: raise ValueError("空行情")
            row = rows[0]; last = float(row["last"]); opened = float(row["open24h"])
            result = {"symbol": symbol, "pair": f"{symbol}/USDT", "name": CRYPTO_NAMES.get(symbol, symbol), "asset_type": "crypto", "currency": "USDT",
                      "price": last, "change": last-opened, "change_percent": (last/opened-1)*100 if opened else 0,
                      "open": opened, "previous_close": None, "high": float(row["high24h"]), "low": float(row["low24h"]),
                      "volume": float(row["vol24h"]), "amount": float(row["volCcy24h"]), "source": "OKX",
                      "updated_at": datetime.fromtimestamp(int(row["ts"])/1000, timezone.utc).isoformat()}
            return cache.set(key, result, 8)
        except Exception as exc: errors.append(f"OKX:{type(exc).__name__}")
        try:
            stats = (await client.get(f"https://api.exchange.coinbase.com/products/{symbol}-USDT/stats")); stats.raise_for_status(); row=stats.json()
            last=float(row["last"]); opened=float(row["open"])
            result={"symbol":symbol,"pair":f"{symbol}/USDT","name":CRYPTO_NAMES.get(symbol,symbol),"asset_type":"crypto","currency":"USDT",
                    "price":last,"change":last-opened,"change_percent":(last/opened-1)*100,"open":opened,"previous_close":None,
                    "high":float(row["high"]),"low":float(row["low"]),"volume":float(row["volume"]),"amount":None,
                    "source":"Coinbase（备用）","updated_at":datetime.now(timezone.utc).isoformat()}
            return cache.set(key,result,8)
        except Exception as exc: errors.append(f"Coinbase:{type(exc).__name__}")
        raise RuntimeError("行情数据获取失败（"+"；".join(errors)+"）")


def _aggregate(candles: list[dict], rule: str) -> list[dict]:
    if not candles: return []
    df = pd.DataFrame(candles); df["dt"] = pd.to_datetime(df["timestamp"], utc=True); df = df.set_index("dt")
    out = df.resample(rule).agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum","amount":"sum"}).dropna(subset=["close"])
    return [{"timestamp": idx.isoformat(), **{k: float(row[k]) for k in ("open","high","low","close","volume","amount")}}
            for idx,row in out.iterrows()]


async def stock_kline(symbol: str, interval: str, limit: int = 400) -> tuple[list[dict], str]:
    requested = interval; source_interval = "1h" if interval == "4h" else interval
    if source_interval not in STOCK_KLT: raise ValueError("A股支持 1m/5m/15m/30m/1h/4h/1d")
    key=f"stock-kline:{symbol}:{interval}:{limit}"
    if cached:=cache.get(key): return cached
    days = 1200 if source_interval == "1d" else 40
    beg=(datetime.now()-timedelta(days=days)).strftime("%Y%m%d")
    async with httpx.AsyncClient(timeout=15,headers=HEADERS,follow_redirects=True) as client:
        errors=[]
        try:
            response=await client.get("https://push2his.eastmoney.com/api/qt/stock/kline/get",params={"secid":_eastmoney_secid(symbol),"klt":STOCK_KLT[source_interval],"fqt":1,"beg":beg,"end":"20500101","lmt":max(limit,500),"fields1":"f1,f2,f3,f4,f5,f6","fields2":"f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"})
            response.raise_for_status(); data=response.json().get("data"); rows=data.get("klines",[]) if data else []
            if not rows: raise ValueError("空 K线")
            candles=[]
            for item in rows:
                v=item.split(","); candles.append({"timestamp":v[0],"open":float(v[1]),"close":float(v[2]),"high":float(v[3]),"low":float(v[4]),"volume":float(v[5]),"amount":float(v[6])})
            if requested=="4h": candles=_aggregate(candles,"4h")
            return cache.set(key,(candles[-limit:],"东方财富历史行情"),30 if interval!="1d" else 300)
        except Exception as exc: errors.append(f"东方财富:{type(exc).__name__}")
        if interval=="1d":
            try:
                market="sh" if symbol.startswith(("5","6","9")) else "sz"
                response=await client.get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",params={"param":f"{market}{symbol},day,,,{limit},qfq"}); response.raise_for_status()
                node=response.json()["data"][f"{market}{symbol}"]; rows=node.get("qfqday") or node.get("day") or []
                candles=[{"timestamp":v[0],"open":float(v[1]),"close":float(v[2]),"high":float(v[3]),"low":float(v[4]),"volume":float(v[5]),"amount":0.0} for v in rows]
                if candles:return cache.set(key,(candles[-limit:],"腾讯证券历史行情（备用）"),300)
            except Exception as exc: errors.append(f"腾讯证券:{type(exc).__name__}")
        raise RuntimeError("K线数据获取失败（"+"；".join(errors)+"）")


async def crypto_kline(symbol: str, interval: str, limit: int = 400) -> tuple[list[dict],str]:
    symbol=normalize_crypto(symbol)
    if interval not in INTERVALS: raise ValueError("币种支持 1m/5m/15m/30m/1h/4h/1d")
    key=f"crypto-kline:{symbol}:{interval}:{limit}"
    if cached:=cache.get(key):return cached
    async with httpx.AsyncClient(timeout=15,headers=HEADERS,follow_redirects=True) as client:
        errors=[]
        try:
            all_rows=[]; after=None
            while len(all_rows)<limit and len(all_rows)<1200:
                params={"instId":f"{symbol}-USDT","bar":INTERVALS[interval],"limit":min(300,limit-len(all_rows))}
                if after:params["after"]=after
                response=await client.get("https://www.okx.com/api/v5/market/history-candles",params=params);response.raise_for_status();rows=response.json().get("data",[])
                if not rows:break
                all_rows.extend(rows);new_after=min(int(v[0]) for v in rows)
                if after==new_after:break
                after=new_after;await asyncio.sleep(.08)
            if not all_rows:raise ValueError("空 K线")
            unique={int(v[0]):v for v in all_rows}; candles=[{"timestamp":datetime.fromtimestamp(ts/1000,timezone.utc).isoformat(),"open":float(v[1]),"high":float(v[2]),"low":float(v[3]),"close":float(v[4]),"volume":float(v[5]),"amount":float(v[7] or v[6])} for ts,v in sorted(unique.items())]
            return cache.set(key,(candles[-limit:],"OKX"),20)
        except Exception as exc:errors.append(f"OKX:{type(exc).__name__}")
        granularity={"1m":60,"5m":300,"15m":900,"30m":1800,"1h":3600,"4h":21600,"1d":86400}[interval]
        try:
            response=await client.get(f"https://api.exchange.coinbase.com/products/{symbol}-USDT/candles",params={"granularity":granularity});response.raise_for_status();rows=response.json()
            candles=[{"timestamp":datetime.fromtimestamp(v[0],timezone.utc).isoformat(),"low":float(v[1]),"high":float(v[2]),"open":float(v[3]),"close":float(v[4]),"volume":float(v[5]),"amount":0.0} for v in reversed(rows)]
            if candles:return cache.set(key,(candles[-limit:],"Coinbase（备用）"),20)
        except Exception as exc:errors.append(f"Coinbase:{type(exc).__name__}")
        raise RuntimeError("K线数据获取失败（"+"；".join(errors)+"）")

