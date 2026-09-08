from __future__ import annotations

import asyncio
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd

from .cache import cache
from .providers import CRYPTO_NAMES, STOCKS, _eastmoney_secid, get_crypto_quote, get_stock_quote

HEADERS = {"User-Agent": "Mozilla/5.0 TradingAI/0.3", "Referer": "https://quote.eastmoney.com/"}
INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "30m": "30m", "1h": "1H", "4h": "4H", "1d": "1D"}
STOCK_KLT = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "1d": 101}
YAHOO_INTERVALS={"1m":("1m","7d"),"5m":("5m","1mo"),"15m":("15m","1mo"),"30m":("30m","1mo"),"1h":("60m","2y"),"4h":("60m","2y"),"1d":("1d","5y")}

def normalize_stock_symbol(symbol: str) -> str:
    value=symbol.upper().strip().replace("NASDAQ:","").replace("NYSE:","")
    if value.startswith(("SH","SZ")) and len(value)==8:value=value[2:]
    if value.endswith((".SH",".SZ")):value=value[:-3]
    return value

def canonical_symbol(symbol: str, asset_type: str) -> str:
    value=normalize_crypto(symbol) if asset_type=="crypto" else normalize_stock_symbol(symbol)
    if asset_type=="crypto":return value
    if value.isdigit() and len(value)==6:return f"{value}.{'SH' if value.startswith(('5','6','9')) else 'SZ'}"
    return value

def _us_stock(symbol:str)->bool:return bool(re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}",normalize_stock_symbol(symbol)))


def normalize_crypto(symbol: str) -> str:
    return symbol.upper().replace("/USDT", "").replace("-USDT", "").replace("USDT", "").strip()


async def stock_search(query: str) -> list[dict]:
    key = f"stock-search:{query.lower()}"
    if cached := cache.get(key): return cached
    async with httpx.AsyncClient(timeout=8, headers=HEADERS) as client:
        if re.search(r"[A-Za-z]",query):
            try:
                response=await client.get("https://query1.finance.yahoo.com/v1/finance/search",params={"q":query.strip(),"quotesCount":12,"newsCount":0});response.raise_for_status()
                results=[{"symbol":row["symbol"],"name":row.get("shortname") or row.get("longname") or row["symbol"],"asset_type":"stock","market":"美股","currency":"USD","canonical_symbol":row["symbol"],"source":"Yahoo Finance 搜索"} for row in response.json().get("quotes",[]) if row.get("quoteType") in {"EQUITY","ETF","INDEX"} and row.get("symbol")]
                if results:return cache.set(key,results[:15],300)
            except Exception:pass
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


async def stock_quote(symbol: str, force_refresh: bool = False) -> dict:
    symbol=normalize_stock_symbol(symbol)
    key = f"stock-quote:{symbol}"
    if not force_refresh and (cached := cache.get(key)): return cached
    async with httpx.AsyncClient(timeout=8, headers=HEADERS, follow_redirects=True) as client:
        if _us_stock(symbol):
            response=await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",params={"interval":"1m","range":"1d"});response.raise_for_status();node=response.json()["chart"]["result"][0];meta=node["meta"]
            price=float(meta.get("regularMarketPrice"));previous=float(meta.get("chartPreviousClose") or meta.get("previousClose") or price);quote=node.get("indicators",{}).get("quote",[{}])[0]
            highs=[x for x in quote.get("high",[]) if x is not None];lows=[x for x in quote.get("low",[]) if x is not None];volumes=[x for x in quote.get("volume",[]) if x is not None]
            result={"symbol":symbol,"canonical_symbol":symbol,"name":meta.get("shortName") or meta.get("longName") or symbol,"asset_type":"stock","market":"美股","currency":meta.get("currency") or "USD","price":price,"change":price-previous,"change_percent":((price/previous)-1)*100 if previous else 0,"open":float(meta.get("regularMarketOpen") or previous),"previous_close":previous,"high":float(meta.get("regularMarketDayHigh") or max(highs,default=price)),"low":float(meta.get("regularMarketDayLow") or min(lows,default=price)),"volume":float(meta.get("regularMarketVolume") or (volumes[-1] if volumes else 0)),"amount":None,"source":"Yahoo Finance public chart API","updated_at":datetime.fromtimestamp(int(meta.get("regularMarketTime") or datetime.now().timestamp()),timezone.utc).isoformat()}
            return cache.set(key,result,8)
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


async def crypto_quote(symbol: str, force_refresh: bool = False) -> dict:
    symbol = normalize_crypto(symbol); key = f"crypto-quote:{symbol}"
    if not force_refresh and (cached := cache.get(key)): return cached
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


async def cross_validate_quote(symbol: str, asset_type: str) -> dict:
    """Read two independent public quote endpoints; never substitute a value."""
    symbol=normalize_crypto(symbol) if asset_type=="crypto" else symbol
    values={};errors=[]
    async with httpx.AsyncClient(timeout=10,headers=HEADERS,follow_redirects=True) as client:
        if asset_type=="crypto":
            try:
                row=(await client.get("https://www.okx.com/api/v5/market/ticker",params={"instId":f"{symbol}-USDT"})).json()["data"][0]
                values["OKX"]=float(row["last"])
            except Exception as exc:errors.append(f"OKX:{type(exc).__name__}")
            try:
                response=await client.get(f"https://api.exchange.coinbase.com/products/{symbol}-USDT/ticker");response.raise_for_status()
                values["Coinbase"]=float(response.json()["price"])
            except Exception as exc:errors.append(f"Coinbase:{type(exc).__name__}")
        else:
            try:
                response=await client.get("https://push2.eastmoney.com/api/qt/stock/get",params={"secid":_eastmoney_secid(symbol),"fields":"f43"});response.raise_for_status()
                values["Eastmoney"]=float(response.json()["data"]["f43"])/100
            except Exception as exc:errors.append(f"Eastmoney:{type(exc).__name__}")
            try:
                market="sh" if symbol.startswith(("5","6","9")) else "sz";response=await client.get(f"https://qt.gtimg.cn/q={market}{symbol}")
                values["Tencent"]=float(response.content.decode("gbk",errors="replace").split('"',1)[1].split("~")[3])
            except Exception as exc:errors.append(f"Tencent:{type(exc).__name__}")
    if len(values)<2:return {"status":"PARTIAL_DATA" if values else "NO_DATA","source":"independent public quote endpoints","values":values,"errors":errors,"conflict":False}
    spread=(max(values.values())-min(values.values()))/max(np_mean(list(values.values())),1e-12)
    return {"status":"AVAILABLE","source":"independent public quote endpoints","values":values,"spread_percent":_safe_round(spread*100,4),
            "conflict":bool(spread>.005),"threshold_percent":.5,"errors":errors}


def np_mean(values):return sum(values)/len(values) if values else 0


def _aggregate(candles: list[dict], rule: str) -> list[dict]:
    if not candles: return []
    df = pd.DataFrame(candles); df["dt"] = pd.to_datetime(df["timestamp"], utc=True); df = df.set_index("dt")
    out = df.resample(rule).agg({"open":"first","high":"max","low":"min","close":"last","volume":"sum","amount":"sum"}).dropna(subset=["close"])
    return [{"timestamp": idx.isoformat(), **{k: float(row[k]) for k in ("open","high","low","close","volume","amount")}}
            for idx,row in out.iterrows()]


async def stock_kline(symbol: str, interval: str, limit: int = 400, force_refresh: bool = False) -> tuple[list[dict], str]:
    symbol=normalize_stock_symbol(symbol)
    if interval == "1w":
        daily, source = await stock_kline(symbol, "1d", min(5000, max(400, limit * 7)), force_refresh)
        weekly=_aggregate(daily, "W-FRI")[-limit:]
        if weekly: weekly[-1]["timestamp"]=daily[-1]["timestamp"]
        return weekly, f"{source} · weekly aggregation"
    if _us_stock(symbol):
        if interval not in YAHOO_INTERVALS:raise ValueError("美股支持 1m/5m/15m/30m/1h/4h/1d")
        key=f"stock-kline:{symbol}:{interval}:{limit}"
        if not force_refresh and (cached:=cache.get(key)):return cached
        yahoo_interval,range_value=YAHOO_INTERVALS[interval]
        async with httpx.AsyncClient(timeout=18,headers=HEADERS,follow_redirects=True) as client:
            response=await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",params={"interval":yahoo_interval,"range":range_value,"events":"history"});response.raise_for_status();node=response.json()["chart"]["result"][0];quotes=node["indicators"]["quote"][0];candles=[]
            for i,stamp in enumerate(node.get("timestamp",[])):
                values=[quotes.get(k,[None]*len(node.get("timestamp",[])))[i] for k in ("open","high","low","close")]
                if any(v is None for v in values):continue
                candles.append({"timestamp":datetime.fromtimestamp(stamp,timezone.utc).isoformat(),"open":float(values[0]),"high":float(values[1]),"low":float(values[2]),"close":float(values[3]),"volume":float(quotes.get("volume",[0])[i] or 0),"amount":0.0})
            if interval=="4h":candles=_aggregate(candles,"4h")
            if not candles:raise RuntimeError("Yahoo Finance 未返回美股K线")
            return cache.set(key,(candles[-limit:],"Yahoo Finance public chart API"),20 if interval!="1d" else 300)
    requested = interval; source_interval = "1h" if interval == "4h" else interval
    if source_interval not in STOCK_KLT: raise ValueError("A股支持 1m/5m/15m/30m/1h/4h/1d")
    key=f"stock-kline:{symbol}:{interval}:{limit}"
    if not force_refresh:
        if cached:=cache.get(key): return cached
        for larger in (1200,2500):
            if limit<larger and (cached:=cache.get(f"stock-kline:{symbol}:{interval}:{larger}")):
                return cached[0][-limit:],cached[1]
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
        except Exception as exc: errors.append(f"东方财富:{type(exc).__name__}:{str(exc)[:120]}")
        # Sina's public K-line feed is an independent intraday fallback.  It
        # returns exchange observations (not reconstructed or generated bars).
        if source_interval in {"5m", "15m", "30m", "1h"}:
            try:
                market="sh" if symbol.startswith(("5","6","9")) else "sz"
                scale={"5m":5,"15m":15,"30m":30,"1h":60}[source_interval]
                response=await client.get(
                    f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_{market}{symbol}_{scale}_=/CN_MarketDataService.getKLineData",
                    params={"symbol":f"{market}{symbol}","scale":scale,"ma":"no","datalen":min(max(limit,500),1023)},
                    headers={**HEADERS,"Referer":"https://finance.sina.com.cn/"})
                response.raise_for_status(); text=response.text
                begin,end=text.find("["),text.rfind("]")
                if begin<0 or end<=begin: raise ValueError("空 K线")
                rows=json.loads(text[begin:end+1])
                candles=[{"timestamp":v["day"],"open":float(v["open"]),"close":float(v["close"]),
                          "high":float(v["high"]),"low":float(v["low"]),"volume":float(v["volume"]),
                          "amount":float(v.get("amount") or 0)} for v in rows]
                if requested=="4h": candles=_aggregate(candles,"4h")
                if candles:return cache.set(key,(candles[-limit:],"新浪财经历史行情（备用）"),30)
            except Exception as exc: errors.append(f"新浪财经:{type(exc).__name__}:{str(exc)[:120]}")
        if interval=="1d":
            try:
                market="sh" if symbol.startswith(("5","6","9")) else "sz"
                response=await client.get("https://web.ifzq.gtimg.cn/appstock/app/fqkline/get",params={"param":f"{market}{symbol},day,,,{limit},qfq"}); response.raise_for_status()
                node=response.json()["data"][f"{market}{symbol}"]; rows=node.get("qfqday") or node.get("day") or []
                candles=[{"timestamp":v[0],"open":float(v[1]),"close":float(v[2]),"high":float(v[3]),"low":float(v[4]),"volume":float(v[5]),"amount":0.0} for v in rows]
                if candles:return cache.set(key,(candles[-limit:],"腾讯证券历史行情（备用）"),300)
            except Exception as exc: errors.append(f"腾讯证券:{type(exc).__name__}:{str(exc)[:120]}")
        raise RuntimeError("K线数据获取失败（"+"；".join(errors)+"）")


async def crypto_kline(symbol: str, interval: str, limit: int = 400, force_refresh: bool = False) -> tuple[list[dict],str]:
    symbol=normalize_crypto(symbol)
    if interval == "1w":
        daily, source = await crypto_kline(symbol, "1d", min(5000, max(400, limit * 7)), force_refresh)
        weekly=_aggregate(daily, "1W")[-limit:]
        if weekly: weekly[-1]["timestamp"]=daily[-1]["timestamp"]
        return weekly, f"{source} · weekly aggregation"
    if interval not in INTERVALS: raise ValueError("币种支持 1m/5m/15m/30m/1h/4h/1d")
    key=f"crypto-kline:{symbol}:{interval}:{limit}"
    if not force_refresh:
        if cached:=cache.get(key):return cached
        if limit<3000 and (cached:=cache.get(f"crypto-kline:{symbol}:{interval}:3000")):
            return cached[0][-limit:],cached[1]
    async with httpx.AsyncClient(timeout=15,headers=HEADERS,follow_redirects=True) as client:
        errors=[]
        try:
            all_rows=[]; after=None
            while len(all_rows)<limit and len(all_rows)<10000:
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


async def crypto_derivatives(symbol: str) -> dict:
    """Fetch real OKX public derivatives fields; never synthesize missing data."""
    symbol=normalize_crypto(symbol);key=f"crypto-derivatives:{symbol}"
    if cached:=cache.get(key): return cached
    instrument=f"{symbol}-USDT-SWAP"; result={"status":"NO_DATA","source":"OKX public API","open_interest":None,
                                              "open_interest_change":None,"funding_rate":None,"liquidation":None}
    async with httpx.AsyncClient(timeout=12,headers=HEADERS,follow_redirects=True) as client:
        available=0;errors=[]
        try:
            response=await client.get("https://www.okx.com/api/v5/public/open-interest",params={"instType":"SWAP","instId":instrument});response.raise_for_status()
            rows=response.json().get("data",[])
            if rows: result["open_interest"]=float(rows[0]["oiCcy"] or rows[0]["oi"]);available+=1
        except Exception as exc: errors.append(f"open_interest:{type(exc).__name__}")
        try:
            response=await client.get("https://www.okx.com/api/v5/public/funding-rate-history",params={"instId":instrument,"limit":20});response.raise_for_status()
            rows=response.json().get("data",[])
            if rows:
                rates=[float(row["fundingRate"]) for row in rows];result["funding_rate"]=rates[0]
                result["funding_rate_percentile"]=sum(value<=rates[0] for value in rates)/len(rates);available+=1
        except Exception as exc: errors.append(f"funding:{type(exc).__name__}")
        try:
            response=await client.get("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume",params={"ccy":symbol,"period":"1H"});response.raise_for_status()
            rows=response.json().get("data",[])
            if len(rows)>=2:
                newest,previous=float(rows[-1][1]),float(rows[-2][1]);result["open_interest_change"]=(newest/previous-1) if previous else None;available+=1
        except Exception as exc: errors.append(f"oi_history:{type(exc).__name__}")
    result["status"]="AVAILABLE" if available>=2 else "PARTIAL_DATA" if available else "NO_DATA";result["errors"]=errors
    return cache.set(key,result,60)


async def macro_context() -> dict:
    """Current cross-asset macro tape from public Yahoo chart observations."""
    key="external:macro"
    if cached:=cache.get(key): return cached
    assets={"DXY":"DX-Y.NYB","US10Y":"^TNX","SP500":"^GSPC","NASDAQ":"^IXIC",
            "GOLD":"GC=F","OIL":"CL=F","VIX":"^VIX"}
    async with httpx.AsyncClient(timeout=15,headers=HEADERS,follow_redirects=True) as client:
        async def fetch(label,ticker):
            try:
                response=await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",params={"range":"5d","interval":"1h"})
                response.raise_for_status(); node=response.json()["chart"]["result"][0]
                closes=[float(v) for v in node["indicators"]["quote"][0]["close"] if v is not None]
                if len(closes)<2:return label,None
                return label,{"price":_safe_round(closes[-1]),"change":_safe_round(closes[-1]/closes[max(0,len(closes)-25)]-1,6),
                              "timestamp":datetime.fromtimestamp(node["timestamp"][-1],timezone.utc).isoformat()}
            except Exception:return label,None
        rows=await asyncio.gather(*(fetch(label,ticker) for label,ticker in assets.items()))
    values={label:value for label,value in rows if value}
    if not values: result={"status":"NO_DATA","source":None,"assets":{}}
    else:
        risk_score=0.0
        if values.get("DXY"):risk_score-=np_sign(values["DXY"]["change"])
        if values.get("US10Y"):risk_score-=np_sign(values["US10Y"]["change"])
        if values.get("SP500"):risk_score+=np_sign(values["SP500"]["change"])
        result={"status":"AVAILABLE" if len(values)>=3 else "PARTIAL_DATA","source":"Yahoo Finance public chart API",
                "assets":values,"signal":"POSITIVE" if risk_score>0 else "NEGATIVE" if risk_score<0 else "NEUTRAL",
                "observed_assets":len(values)}
    return cache.set(key,result,300)


async def macro_history(interval: str = "1h") -> dict:
    """Historical cross-asset bars used only at timestamps where they existed."""
    key=f"external:macro-history:{interval}"
    if cached:=cache.get(key): return cached
    yahoo_interval="1d" if interval=="1d" else "1h"
    range_value="3y" if interval=="1d" else "60d"
    assets={"DXY":"DX-Y.NYB","US10Y":"^TNX","SP500":"^GSPC","NASDAQ":"^IXIC",
            "GOLD":"GC=F","OIL":"CL=F","VIX":"^VIX"}
    async with httpx.AsyncClient(timeout=18,headers=HEADERS,follow_redirects=True) as client:
        async def fetch(label,ticker):
            try:
                response=await client.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                                          params={"range":range_value,"interval":yahoo_interval})
                response.raise_for_status();node=response.json()["chart"]["result"][0]
                quotes=node["indicators"]["quote"][0];rows=[]
                for idx,stamp in enumerate(node.get("timestamp",[])):
                    close=quotes["close"][idx]
                    if close is not None:rows.append({"timestamp":datetime.fromtimestamp(stamp,timezone.utc).isoformat(),"close":float(close)})
                return label,rows
            except Exception:return label,[]
        fetched=await asyncio.gather(*(fetch(label,ticker) for label,ticker in assets.items()))
    values={label:rows for label,rows in fetched if rows}
    result={"status":"AVAILABLE" if len(values)>=5 else "PARTIAL_DATA" if values else "NO_DATA",
            "source":"Yahoo Finance public chart API","interval":yahoo_interval,"assets":values}
    return cache.set(key,result,300)


def _safe_round(value, digits=4):
    try:return round(float(value),digits)
    except (TypeError,ValueError):return None


def np_sign(value):
    return 1 if value>0 else -1 if value<0 else 0


async def news_context(symbol: str, asset_type: str, force_refresh: bool = False) -> dict:
    """Timestamped headlines only; keyword score is labelled and never invents stories."""
    key=f"external:news:{asset_type}:{symbol}"
    if not force_refresh and (cached:=cache.get(key)): return cached
    name=STOCKS.get(symbol,(symbol,""))[0] if asset_type=="stock" else f"{symbol} crypto"
    query=f"{name} when:7d"
    try:
        async with httpx.AsyncClient(timeout=15,headers=HEADERS,follow_redirects=True) as client:
            response=await client.get("https://news.google.com/rss/search",params={"q":query,"hl":"zh-CN","gl":"CN","ceid":"CN:zh-Hans"})
            response.raise_for_status(); root=ET.fromstring(response.content)
        positive=("上涨","增长","突破","利好","获批","创新高","rally","surge","gain","approval")
        negative=("下跌","暴跌","风险","调查","处罚","亏损","危机","跌破","fall","crash","loss","probe")
        items=[]; raw_score=0
        for node in root.findall("./channel/item")[:10]:
            title=(node.findtext("title") or "").strip();published=(node.findtext("pubDate") or "").strip();link=(node.findtext("link") or "").strip()
            lower=title.lower();score=sum(word in lower for word in positive)-sum(word in lower for word in negative);raw_score+=score
            items.append({"title":title,"published":published,"link":link,"keyword_signal":np_sign(score)})
        now_python=datetime.now(timezone.utc);parsed=[pd.to_datetime(item["published"],utc=True,errors="coerce") for item in items]
        result={"status":"AVAILABLE" if items else "NO_DATA","source":"Google News RSS","headlines":items,
                "last_24h_count":sum(1 for stamp in parsed if pd.notna(stamp) and now_python-stamp.to_pydatetime()<=timedelta(hours=24)),
                "last_7d_count":sum(1 for stamp in parsed if pd.notna(stamp) and now_python-stamp.to_pydatetime()<=timedelta(days=7)),
                "sentiment_score":_safe_round(raw_score/max(len(items),1),4),"method":"auditable headline keyword score; no LLM-generated facts"}
    except Exception as exc:result={"status":"NO_DATA","source":None,"headlines":[],"error":type(exc).__name__}
    return cache.set(key,result,300)


async def event_risk() -> dict:
    key="external:event-calendar"
    if cached:=cache.get(key): return cached
    try:
        async with httpx.AsyncClient(timeout=15,headers=HEADERS,follow_redirects=True) as client:
            response=await client.get("https://nfs.faireconomy.media/ff_calendar_thisweek.json");response.raise_for_status();rows=response.json()
        now=datetime.now(timezone.utc);upcoming=[]
        for row in rows:
            try:stamp=datetime.fromisoformat(row["date"]).astimezone(timezone.utc)
            except Exception:continue
            hours=(stamp-now).total_seconds()/3600
            if 0<=hours<=72 and row.get("impact") in {"High","Medium"}:
                upcoming.append({"title":row.get("title"),"country":row.get("country"),"impact":row.get("impact"),
                                 "timestamp":stamp.isoformat(),"hours_until":round(hours,1),"forecast":row.get("forecast") or None,
                                 "previous":row.get("previous") or None})
        high=any(row["impact"]=="High" and row["hours_until"]<=36 for row in upcoming)
        result={"status":"AVAILABLE","source":"Fair Economy public weekly calendar","risk":"HIGH" if high else "MEDIUM" if upcoming else "LOW",
                "upcoming":upcoming[:12],"checked_at":now.isoformat()}
    except Exception as exc:result={"status":"NO_DATA","source":None,"risk":"UNKNOWN","upcoming":[],"error":type(exc).__name__}
    return cache.set(key,result,300)


async def stock_fundamental(symbol: str) -> dict:
    symbol=normalize_stock_symbol(symbol)
    if _us_stock(symbol):return {"status":"NOT_AVAILABLE","source":None,"reason":"免费Yahoo图表接口不提供可审计基本面字段"}
    key=f"external:fundamental:{symbol}"
    if cached:=cache.get(key): return cached
    market="sh" if symbol.startswith(("5","6","9")) else "sz"
    try:
        async with httpx.AsyncClient(timeout=12,headers=HEADERS,follow_redirects=True) as client:
            response=await client.get(f"https://qt.gtimg.cn/q={market}{symbol}");response.raise_for_status()
        values=response.content.decode("gbk",errors="replace").split('"',1)[1].rsplit('"',1)[0].split("~")
        result={"status":"AVAILABLE","source":"Tencent Securities public quote fundamentals","timestamp":values[30],
                "pe_dynamic":_safe_round(values[39]),"pb":_safe_round(values[46]),"market_cap_cny_100m":_safe_round(values[44]),
                "total_market_cap_cny_100m":_safe_round(values[45]),"turnover_rate_percent":_safe_round(values[38])}
    except Exception as exc:result={"status":"NO_DATA","source":None,"error":type(exc).__name__}
    return cache.set(key,result,300)


async def stock_financial_history(symbol: str) -> dict:
    """Point-in-time A-share financial statements with public announcement dates."""
    symbol=normalize_stock_symbol(symbol)
    if _us_stock(symbol):return {"status":"NOT_AVAILABLE","source":None,"history":[],"reason":"当前免费历史财报Provider仅覆盖A股"}
    key=f"external:financial-history:{symbol}"
    if cached:=cache.get(key):return cached
    try:
        async with httpx.AsyncClient(timeout=18,headers=HEADERS,follow_redirects=True) as client:
            response=await client.get("https://datacenter-web.eastmoney.com/api/data/v1/get",params={
                "reportName":"RPT_LICO_FN_CPD","columns":"ALL","filter":f'(SECURITY_CODE="{symbol}")',
                "pageNumber":1,"pageSize":60})
            response.raise_for_status();rows=(response.json().get("result") or {}).get("data") or []
        fields={"revenue":"TOTAL_OPERATE_INCOME","revenue_growth":"YSTZ",
                "net_income":"PARENT_NETPROFIT","net_income_growth":"SJLTZ","eps":"BASIC_EPS",
                "roe":"WEIGHTAVG_ROE","gross_margin":"XSMLL","operating_cash_flow_per_share":"MGJYXJJE"}
        history=[]
        for row in rows:
            period=row.get("REPORTDATE");announced=row.get("NOTICE_DATE") or row.get("UPDATE_DATE")
            if not period or not announced:continue
            history.append({"period_end":period,"announcement_date":announced,
                            **{name:_safe_round(row.get(field),6) for name,field in fields.items()}})
        history.sort(key=lambda item:item["announcement_date"],reverse=True)
        result={"status":"AVAILABLE" if history else "NO_DATA","source":"Eastmoney public financial data center",
                "history":history,"unavailable_fields":["ROA","net_margin","debt_ratio","free_cash_flow"],
                "point_in_time_field":"announcement_date","analyst_consensus_status":"DATA_INSUFFICIENT",
                "surprise_status":"DATA_INSUFFICIENT"}
    except Exception as exc:result={"status":"NO_DATA","source":None,"history":[],"error":type(exc).__name__,
                                   "analyst_consensus_status":"DATA_INSUFFICIENT","surprise_status":"DATA_INSUFFICIENT"}
    return cache.set(key,result,1800)


async def crypto_onchain(symbol: str) -> dict:
    key=f"external:onchain:{symbol}"
    if cached:=cache.get(key): return cached
    chain={"BTC":"bitcoin","ETH":"ethereum"}.get(normalize_crypto(symbol))
    if not chain:return {"status":"NOT_APPLICABLE_OR_NO_DATA","source":None}
    try:
        async with httpx.AsyncClient(timeout=20,headers=HEADERS,follow_redirects=True) as client:
            response=await client.get(f"https://api.blockchair.com/{chain}/stats");response.raise_for_status();data=response.json()["data"]
        fields=("blocks_24h","transactions_24h","mempool_transactions","mempool_tps","average_transaction_fee_24h","hashrate_24h","burned_24h")
        result={"status":"AVAILABLE","source":"Blockchair public chain statistics","chain":chain,
                "data":{field:data.get(field) for field in fields if data.get(field) is not None},"data_time":data.get("best_block_time")}
    except Exception as exc:result={"status":"NO_DATA","source":None,"chain":chain,"error":type(exc).__name__}
    return cache.set(key,result,300)
