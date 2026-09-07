from __future__ import annotations

import asyncio
import json

from backend.ai_engine import feature_frame
from backend.market import crypto_kline, stock_kline


ASSETS=(("BTC","crypto"),("ETH","crypto"),("600519","stock"),("300750","stock"),("000001","stock"))
INTERVALS=("15m","1h","4h","1d")


async def check(symbol: str,asset_type: str,interval: str) -> dict:
    try:
        rows,source=await (crypto_kline(symbol,interval,500) if asset_type=="crypto" else stock_kline(symbol,interval,500))
        frame=feature_frame(rows)
        valid=int(frame[["rsi","macd","atr","flow_pressure","sentiment_score"]].dropna().shape[0])
        return {"asset":symbol,"asset_type":asset_type,"interval":interval,"status":"PASS" if len(rows)>=80 and valid else "FAIL",
                "bars":len(rows),"valid_feature_rows":valid,"source":source,"latest":rows[-1]["timestamp"]}
    except Exception as exc:
        return {"asset":symbol,"asset_type":asset_type,"interval":interval,"status":"FAIL","error":f"{type(exc).__name__}: {exc}"}


async def main():
    results=await asyncio.gather(*(check(symbol,kind,interval) for symbol,kind in ASSETS for interval in INTERVALS))
    print(json.dumps({"checks":len(results),"passed":sum(row["status"]=="PASS" for row in results),"results":results},ensure_ascii=False,indent=2))
    raise SystemExit(0 if all(row["status"]=="PASS" for row in results) else 1)


if __name__=="__main__":asyncio.run(main())
