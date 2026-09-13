"""Auditable incremental candle storage and versioned research universes."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pandas as pd

from .database import connection
from .symbol_master import resolve


def validate_candles(rows: list[dict]) -> dict:
    required={"timestamp","open","high","low","close","volume"}
    errors=[]; clean=[]; previous=None; seen=set()
    for index,row in enumerate(rows):
        missing=required-set(row)
        if missing: errors.append({"row":index,"code":"MISSING_FIELDS","fields":sorted(missing)});continue
        try:
            stamp=pd.Timestamp(row["timestamp"])
            stamp=stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
            values={key:float(row[key]) for key in ("open","high","low","close","volume")}
        except (TypeError,ValueError):errors.append({"row":index,"code":"INVALID_TYPE"});continue
        key=stamp.isoformat()
        if key in seen:errors.append({"row":index,"code":"DUPLICATE_TIMESTAMP"});continue
        if previous is not None and stamp<=previous:errors.append({"row":index,"code":"OUT_OF_ORDER"});continue
        if min(values[k] for k in ("open","high","low","close"))<=0 or values["high"]<max(values["open"],values["close"]) or values["low"]>min(values["open"],values["close"]) or values["high"]<values["low"]:
            errors.append({"row":index,"code":"BAD_OHLC"});continue
        if values["volume"]<0:errors.append({"row":index,"code":"NEGATIVE_VOLUME"});continue
        seen.add(key);previous=stamp;clean.append({**row,"timestamp":key,**values})
    return {"status":"PASSED" if not errors else "FAILED","input_rows":len(rows),"valid_rows":len(clean),
            "errors":errors,"rows":clean}


def store_incremental(symbol: str, asset_type: str, interval: str, rows: list[dict], source: str) -> dict:
    audit=validate_candles(rows)
    if audit["status"]!="PASSED":return {key:value for key,value in audit.items() if key!="rows"}
    identity=resolve(symbol,asset_type);now=datetime.now(timezone.utc).isoformat();inserted=0
    with connection() as conn:
        before=conn.total_changes
        conn.executemany("""INSERT OR IGNORE INTO market_candles
          (market,canonical_symbol,interval,timestamp,open,high,low,close,volume,amount,source,collected_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",[(identity.market,identity.canonical_symbol,interval,row["timestamp"],row["open"],row["high"],row["low"],row["close"],row["volume"],row.get("amount"),source,now) for row in audit["rows"]])
        inserted=conn.total_changes-before
        span=conn.execute("SELECT MIN(timestamp),MAX(timestamp),COUNT(*) FROM market_candles WHERE market=? AND canonical_symbol=? AND interval=?",(identity.market,identity.canonical_symbol,interval)).fetchone()
    return {"status":"PASSED","received":len(rows),"inserted":inserted,"duplicates_ignored":len(rows)-inserted,
            "market":identity.market,"symbol":identity.canonical_symbol,"start":span[0],"end":span[1],"stored":span[2]}


def persist_universe(market: str, members: list[dict], source: str, as_of: str | None=None,
                     survivorship_status: str="UNRESOLVED") -> dict:
    as_of=as_of or datetime.now(timezone.utc).date().isoformat()
    normalized=[]
    for item in members:
        identity=resolve(str(item["symbol"]),"crypto" if market=="CRYPTO" else "stock")
        normalized.append({"symbol":identity.canonical_symbol,"active":bool(item.get("active",True)),
                           "effective_from":item.get("effective_from"),"effective_to":item.get("effective_to"),
                           "metadata":item.get("metadata",{})})
    fingerprint=hashlib.sha256(json.dumps({"market":market,"as_of":as_of,"members":normalized},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
    version=f"{market}-{as_of}-{fingerprint}"
    with connection() as conn:
        conn.execute("""INSERT OR IGNORE INTO research_universes
          (universe_version,market,source,as_of,survivorship_status,member_count,payload_json)
          VALUES(?,?,?,?,?,?,?)""",(version,market,source,as_of,survivorship_status,len(normalized),json.dumps(normalized,ensure_ascii=False)))
        conn.executemany("""INSERT OR IGNORE INTO research_universe_members
          (universe_version,canonical_symbol,effective_from,effective_to,active,metadata_json) VALUES(?,?,?,?,?,?)""",
          [(version,x["symbol"],x["effective_from"],x["effective_to"],int(x["active"]),json.dumps(x["metadata"],ensure_ascii=False)) for x in normalized])
    return {"universeVersion":version,"market":market,"memberCount":len(normalized),"source":source,
            "survivorshipStatus":survivorship_status}


def data_hash(market: str | None=None) -> str:
    with connection() as conn:
        where=" WHERE market=?" if market else "";params=(market,) if market else ()
        rows=[tuple(row) for row in conn.execute(f"SELECT market,canonical_symbol,interval,COUNT(*),MIN(timestamp),MAX(timestamp) FROM market_candles{where} GROUP BY market,canonical_symbol,interval ORDER BY 1,2,3",params)]
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()
