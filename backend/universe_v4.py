"""Build versioned universes from real provider metadata, never synthetic members."""
from __future__ import annotations

import httpx

from .data_pipeline_v4 import persist_universe
from .symbol_registry import list_members, refresh


TARGETS={"CN":300,"US":100,"CRYPTO":50}


async def build_universe(market: str, refresh_registry: bool=False) -> dict:
    if market not in TARGETS:raise ValueError("market must be CN, US or CRYPTO")
    refresh_result=await refresh() if refresh_registry else None
    if market=="CRYPTO":
        members=[];source="OKX public spot tickers ranked by observed quote volume"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response=await client.get("https://www.okx.com/api/v5/market/tickers",params={"instType":"SPOT"});response.raise_for_status()
            candidates=[]
            for row in response.json().get("data",[]):
                symbol=str(row.get("instId") or "")
                if not symbol.endswith("-USDT"):continue
                try:volume=float(row.get("volCcy24h") or 0)
                except (TypeError,ValueError):continue
                candidates.append((volume,symbol[:-5]))
            for volume,symbol in sorted(candidates,reverse=True)[:100]:members.append({"symbol":symbol,"metadata":{"quote_volume_24h":volume}})
        except Exception as exc:
            members=[{"symbol":row["symbol"],"metadata":{"liquidity":"UNAVAILABLE"}} for row in list_members(market,100)]
            source=f"registry fallback; liquidity ranking unavailable: {type(exc).__name__}"
    else:
        rows=list_members(market,1000 if market=="CN" else 500)
        members=[{"symbol":row["symbol"],"active":row["status"] in {"TRADING","live"},
                  "metadata":{"name":row["name"],"exchange":row["exchange"],"registry_source":row["source"]}} for row in rows]
        source="persistent registry populated by Eastmoney" if market=="CN" else "persistent registry populated by Nasdaq screener"
    universe=persist_universe(market,members,source,survivorship_status="CURRENT_CONSTITUENTS_ONLY; SURVIVORSHIP_BIAS_UNRESOLVED")
    universe.update({"targetMinimum":TARGETS[market],"meetsMinimum":len(members)>=TARGETS[market],
                     "refresh":refresh_result,"warning":None if len(members)>=TARGETS[market] else "INSUFFICIENT_REAL_PROVIDER_MEMBERS"})
    return universe
