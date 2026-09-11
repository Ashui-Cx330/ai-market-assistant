from __future__ import annotations

import asyncio
import os
import sqlite3
import time
import math
from pathlib import Path
from threading import RLock

import httpx


_LOCK = RLock()
_SEEDED_PATHS: set[str] = set()
_REFRESH_TASK: asyncio.Task | None = None
_HEADERS = {"User-Agent": "Mozilla/5.0 AI-Market-Assistant/1.10"}


def _path() -> Path:
    root = Path(os.environ.get("TRADING_AI_DATA_DIR") or Path.home() / ".ai-market-assistant")
    path = root / "cache" / "symbol-registry.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


_SEED = (
    ("600519", "stock", "A股", "SSE", "贵州茅台", "贵州茅台|茅台|Kweichow Moutai|moutai", "", ""),
    ("000001", "stock", "A股", "SZSE", "平安银行", "平安银行|Ping An Bank|pingan", "", ""),
    ("300750", "stock", "A股", "SZSE", "宁德时代", "宁德时代|CATL", "", ""),
    ("688981", "stock", "A股", "SSE STAR", "中芯国际", "中芯国际|SMIC", "", ""),
    ("430047", "stock", "A股", "BSE", "诺思兰德", "诺思兰德", "", ""),
    ("NVDA", "stock", "美股", "NASDAQ", "NVIDIA Corporation", "NVIDIA|英伟达|NVDA", "", ""),
    ("AAPL", "stock", "美股", "NASDAQ", "Apple Inc.", "Apple|苹果|AAPL", "", ""),
    ("TSLA", "stock", "美股", "NASDAQ", "Tesla, Inc.", "Tesla|特斯拉|TSLA", "", ""),
    ("AMD", "stock", "美股", "NASDAQ", "Advanced Micro Devices", "AMD|超威半导体", "", ""),
    ("MSFT", "stock", "美股", "NASDAQ", "Microsoft Corporation", "Microsoft|微软|MSFT", "", ""),
    ("BTC", "crypto", "Crypto", "BINANCE", "Bitcoin", "Bitcoin|比特币|BTCUSDT|BTC/USDT", "BTC", "USDT"),
    ("ETH", "crypto", "Crypto", "BINANCE", "Ethereum", "Ethereum|以太坊|ETHUSDT|ETH/USDT", "ETH", "USDT"),
    ("SOL", "crypto", "Crypto", "BINANCE", "Solana", "Solana|SOLUSDT|SOL/USDT", "SOL", "USDT"),
    ("BNB", "crypto", "Crypto", "BINANCE", "BNB", "Binance Coin|币安币|BNBUSDT", "BNB", "USDT"),
    ("XRP", "crypto", "Crypto", "BINANCE", "XRP", "Ripple|瑞波币|XRPUSDT", "XRP", "USDT"),
)


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""CREATE TABLE IF NOT EXISTS symbols(
        symbol TEXT NOT NULL, asset_type TEXT NOT NULL, market TEXT NOT NULL,
        exchange TEXT NOT NULL, name TEXT NOT NULL, aliases TEXT NOT NULL DEFAULT '',
        base_asset TEXT NOT NULL DEFAULT '', quote_asset TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'TRADING', source TEXT NOT NULL,
        updated_at REAL NOT NULL, PRIMARY KEY(symbol,asset_type,exchange,quote_asset))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS registry_meta(
        source TEXT PRIMARY KEY, status TEXT NOT NULL, item_count INTEGER NOT NULL,
        updated_at REAL NOT NULL, error TEXT)""")
    return conn


def ensure_seeded() -> None:
    key=str(_path()).lower()
    if key in _SEEDED_PATHS: return
    with _LOCK:
        if key in _SEEDED_PATHS: return
        with _connect() as conn:
            now = time.time()
            conn.executemany("""INSERT OR IGNORE INTO symbols
                (symbol,asset_type,market,exchange,name,aliases,base_asset,quote_asset,status,source,updated_at)
                VALUES(?,?,?,?,?,?,?,?, 'TRADING','bundled verified index',?)""",
                [(*row, now) for row in _SEED])
            conn.commit()
        _SEEDED_PATHS.add(key)


def search(query: str, asset_type: str, limit: int = 20) -> list[dict]:
    ensure_seeded()
    raw = query.strip()
    compact = raw.upper().replace("/USDT", "").replace("-USDT", "")
    if compact.endswith("USDT"):
        compact = compact[:-4]
    token = f"%{raw.lower()}%"
    compact_token = f"%{compact.lower()}%"
    with _connect() as conn:
        rows = conn.execute("""SELECT * FROM symbols WHERE asset_type=? AND
            (lower(symbol) LIKE ? OR lower(name) LIKE ? OR lower(aliases) LIKE ? OR lower(base_asset) LIKE ?)
            ORDER BY CASE WHEN lower(symbol)=? THEN 0 WHEN lower(base_asset)=? THEN 1
                          WHEN lower(name)=? THEN 2 WHEN lower(symbol) LIKE ? THEN 3 ELSE 4 END,
                     length(symbol), symbol LIMIT ?""",
            (asset_type, compact_token, token, token, compact_token, compact.lower(), compact.lower(),
             raw.lower(), compact.lower() + "%", limit)).fetchall()
    output=[];seen=set()
    for row in rows:
        key=(row["symbol"],asset_type)
        if key in seen: continue
        seen.add(key)
        item={"symbol":row["symbol"],"name":row["name"],"asset_type":asset_type,
              "market":row["market"],"exchange":row["exchange"],"status":row["status"],
              "source":row["source"],"canonical_symbol":row["symbol"]}
        if asset_type == "crypto": item["pair"] = f'{row["base_asset"]}/USDT'
        output.append(item)
    return output


def _upsert(rows: list[tuple], source: str) -> int:
    if not rows: return 0
    with _LOCK, _connect() as conn:
        now=time.time()
        conn.executemany("""INSERT INTO symbols
          (symbol,asset_type,market,exchange,name,aliases,base_asset,quote_asset,status,source,updated_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol,asset_type,exchange,quote_asset) DO UPDATE SET
          name=excluded.name,aliases=excluded.aliases,status=excluded.status,source=excluded.source,
          updated_at=excluded.updated_at""", [(*row,source,now) for row in rows])
        conn.execute("INSERT INTO registry_meta VALUES(?,?,?,?,NULL) ON CONFLICT(source) DO UPDATE SET status='CONNECTED',item_count=excluded.item_count,updated_at=excluded.updated_at,error=NULL",
                     (source,"CONNECTED",len(rows),now))
        conn.commit()
    return len(rows)


async def _refresh_binance(client: httpx.AsyncClient) -> int:
    response=await client.get("https://api.binance.com/api/v3/exchangeInfo")
    response.raise_for_status(); rows=[]
    for item in response.json().get("symbols",[]):
        if item.get("quoteAsset") != "USDT": continue
        base=item.get("baseAsset","").upper()
        rows.append((base,"crypto","Crypto","BINANCE",base,f"{base}USDT|{base}/USDT",base,"USDT",item.get("status") or "UNKNOWN"))
    return await asyncio.to_thread(_upsert,rows,"Binance exchangeInfo")


async def _refresh_okx(client: httpx.AsyncClient) -> int:
    response=await client.get("https://www.okx.com/api/v5/public/instruments",params={"instType":"SPOT"})
    response.raise_for_status(); rows=[]
    for item in response.json().get("data",[]):
        if item.get("quoteCcy") != "USDT": continue
        base=item.get("baseCcy","").upper()
        rows.append((base,"crypto","Crypto","OKX",base,f"{base}USDT|{base}/USDT",base,"USDT",item.get("state") or "UNKNOWN"))
    return await asyncio.to_thread(_upsert,rows,"OKX instruments")


async def _refresh_a_shares(client: httpx.AsyncClient) -> int:
    page_size=100
    params={"pz":page_size,"po":1,"np":1,"fltt":2,"invt":2,"fid":"f3",
            "fs":"m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
            "fields":"f12,f13,f14"}
    async def page(number: int) -> tuple[list, int]:
        last_error=None
        for _ in range(2):
            try:
                response=await client.get("https://push2.eastmoney.com/api/qt/clist/get",params={**params,"pn":number})
                response.raise_for_status();data=response.json().get("data") or {}
                return data.get("diff") or [],int(data.get("total") or 0)
            except Exception as exc:last_error=exc;await asyncio.sleep(.25)
        raise last_error or RuntimeError("Eastmoney list failed")
    first,total=await page(1)
    page_count=min(80,max(1,math.ceil(total/page_size)))
    gate=asyncio.Semaphore(3)
    async def bounded(number: int):
        async with gate:return (await page(number))[0]
    rest=await asyncio.gather(*(bounded(number) for number in range(2,page_count+1)),return_exceptions=True)
    items=list(first)
    for value in rest:
        if not isinstance(value,BaseException):items.extend(value)
    rows=[]
    for item in items:
        code=str(item.get("f12") or ""); name=str(item.get("f14") or "")
        if len(code)!=6 or not code.isdigit() or not name: continue
        exchange="SSE" if str(item.get("f13"))=="1" else "BSE" if code.startswith(("4","8")) else "SZSE"
        rows.append((code,"stock","A股",exchange,name,name,"","","TRADING"))
    count=await asyncio.to_thread(_upsert,rows,"Eastmoney security list")
    failed_pages=sum(isinstance(value,BaseException) for value in rest)
    if failed_pages: raise RuntimeError(f"已缓存 {count} 只证券，但 {failed_pages} 个分页刷新失败")
    return count


async def refresh() -> dict:
    ensure_seeded(); results={}
    async with httpx.AsyncClient(timeout=12,headers=_HEADERS,follow_redirects=True) as client:
        calls={"Binance exchangeInfo":_refresh_binance(client),"OKX instruments":_refresh_okx(client),
               "Eastmoney security list":_refresh_a_shares(client)}
        values=await asyncio.gather(*calls.values(),return_exceptions=True)
    with _LOCK, _connect() as conn:
        now=time.time()
        for source,value in zip(calls,values):
            if isinstance(value,BaseException):
                conn.execute("INSERT INTO registry_meta VALUES(?,?,?,?,?) ON CONFLICT(source) DO UPDATE SET status='DEGRADED',updated_at=excluded.updated_at,error=excluded.error",
                             (source,"DEGRADED",0,now,f"{type(value).__name__}: {str(value)[:160]}"));results[source]=0
            else: results[source]=value
        conn.commit()
    return results


def schedule_refresh() -> asyncio.Task | None:
    global _REFRESH_TASK
    if _REFRESH_TASK is None or _REFRESH_TASK.done():
        _REFRESH_TASK=asyncio.create_task(refresh(),name="symbol-registry-refresh")
    return _REFRESH_TASK


def status() -> dict:
    ensure_seeded()
    with _LOCK, _connect() as conn:
        total=conn.execute("SELECT COUNT(DISTINCT symbol || ':' || asset_type) FROM symbols").fetchone()[0]
        sources=[dict(row) for row in conn.execute("SELECT * FROM registry_meta ORDER BY source")]
    return {"symbols":total,"sources":sources,"database":str(_path())}
