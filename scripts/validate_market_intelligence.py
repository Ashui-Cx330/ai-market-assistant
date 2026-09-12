"""Live, read-only acceptance probe for the nine required assets."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from backend.database import init_db
from backend.market import (canonical_symbol, crypto_kline, crypto_quote,
                            crypto_search, stock_kline, stock_quote,
                            stock_search)
from backend.market_intelligence import intelligence_view
from backend.news_intelligence import build_intelligence, collect_news

ASSETS=(("600519","stock"),("000001","stock"),("300750","stock"),("NVDA","stock"),("AAPL","stock"),("TSLA","stock"),
        ("BTC","crypto"),("ETH","crypto"),("SOL","crypto"))


async def probe(symbol: str, asset_type: str) -> dict:
    result={"requested_symbol":symbol,"asset_type":asset_type}
    try:
        search=await (stock_search(symbol) if asset_type=="stock" else crypto_search(symbol));result["search"]="PASS" if search else "FAIL"
    except Exception as exc:result.update({"search":"FAIL","search_error":type(exc).__name__})
    try:
        quote=await (stock_quote(symbol) if asset_type=="stock" else crypto_quote(symbol));result["quote"]="PASS" if quote.get("price",0)>0 else "FAIL";result["quote_source"]=quote.get("source")
    except Exception as exc:result.update({"quote":"FAIL","quote_error":type(exc).__name__})
    interval="1d" if asset_type=="stock" else "1h"
    try:
        candles,source=await (stock_kline(symbol,interval,300) if asset_type=="stock" else crypto_kline(symbol,interval,300));result["kline"]="PASS" if len(candles)>=180 else "FAIL";result["kline_rows"]=len(candles);result["kline_source"]=source
    except Exception as exc:result.update({"kline":"FAIL","kline_error":type(exc).__name__})
    normalized=canonical_symbol(symbol,asset_type)
    try:
        rows,status=await collect_news(normalized,None,None,None,30);intel=build_intelligence(rows,normalized)
        result["news"]="PASS" if any(x.get("status")=="HEALTHY" for x in status) else "FAIL";result["news_items"]=len(rows)
        analyzed=intel.get("all_news",[])
        result["event_recognition"]="PASS" if analyzed and all(x.get("event",{}).get("event_type") for x in analyzed) else "NO_MATCHED_ITEMS"
        result["deduped_items"]=len({x.get("fingerprint") for x in intel.get("all_news",[])})
    except Exception as exc:result.update({"news":"FAIL","news_error":type(exc).__name__})
    cached=intelligence_view(normalized,asset_type);result["prediction_status"]=cached.get("status");result["prediction_periods"]=[x.get("horizon") for x in cached.get("periods",[])];result["prediction_record_count"]=cached.get("history_count",0)
    result["information_cutoff_enforced"]=cached.get("information_cutoff_enforced",False)
    return result


async def main():
    init_db();rows=await asyncio.gather(*(probe(*asset) for asset in ASSETS))
    print(json.dumps({"generated_at":datetime.now(timezone.utc).isoformat(),"assets":rows},ensure_ascii=False,indent=2))


if __name__=="__main__":asyncio.run(main())
