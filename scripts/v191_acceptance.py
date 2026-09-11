from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


ASSETS=(
    ("600519","stock"),("000001","stock"),("300750","stock"),
    ("AAPL","stock"),("NVDA","stock"),("TSLA","stock"),
    ("BTC","crypto"),("ETH","crypto"),("SOL","crypto"),("BNB","crypto"),
)


async def call(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> dict:
    started=time.perf_counter()
    try:
        response=await client.request(method,path,**kwargs)
        body=response.json()
        success=response.is_success and body.get("success",True)
        return {"success":success,"status":response.status_code,
                "duration_ms":round((time.perf_counter()-started)*1000,2),
                "source":body.get("source"),"data":body.get("data",body),
                "error":None if success else body.get("message")}
    except Exception as exc:
        return {"success":False,"status":None,"duration_ms":round((time.perf_counter()-started)*1000,2),
                "source":None,"data":None,"error":f"{type(exc).__name__}: {str(exc)[:240]}"}


async def asset_checks(client: httpx.AsyncClient, symbol: str, asset_type: str, semaphore: asyncio.Semaphore) -> dict:
    route="crypto" if asset_type=="crypto" else "stock"
    interval="1h" if asset_type=="crypto" else "1d"
    async with semaphore:
        search=await call(client,"GET",f"/api/market/{route}/search",params={"q":symbol})
        quote,kline,news=await asyncio.gather(
            call(client,"GET",f"/api/market/{route}/quote",params={"symbol":symbol}),
            call(client,"GET",f"/api/market/{route}/kline",params={"symbol":symbol,"interval":interval,"limit":300}),
            call(client,"GET","/api/news/feed",params={"symbol":symbol,"page_size":5}),
        )
        prediction=await call(client,"POST","/api/ai/predict",json={"symbol":symbol,"asset_type":asset_type,"interval":interval})
    kdata=kline.get("data") or {}; pdata=prediction.get("data") or {}
    return {"symbol":symbol,"asset_type":asset_type,
            "checks":{"search":{"success":search["success"] and bool(search.get("data")),"duration_ms":search["duration_ms"],"source":search["source"],"error":search["error"]},
                      "quote":{"success":quote["success"] and bool((quote.get("data") or {}).get("price")),"duration_ms":quote["duration_ms"],"source":quote["source"] or (quote.get("data") or {}).get("source"),"error":quote["error"]},
                      "kline_indicators":{"success":kline["success"] and bool(kdata.get("candles")) and bool(kdata.get("indicators")),"duration_ms":kline["duration_ms"],"source":kline["source"],"error":kline["error"]},
                      "news":{"success":news["success"],"duration_ms":news["duration_ms"],"source":news["source"],"records":len((news.get("data") or {}).get("items",[])),"error":news["error"]},
                      "prediction":{"success":prediction["success"] and pdata.get("model",{}).get("name")=="PerformanceWeightedEnsemble","duration_ms":prediction["duration_ms"],"source":prediction["source"],"error":prediction["error"]}}}


async def main(base_url: str, output: Path) -> int:
    timeout=httpx.Timeout(240,connect=12)
    async with httpx.AsyncClient(base_url=base_url.rstrip("/"),timeout=timeout) as client:
        semaphore=asyncio.Semaphore(2)
        rows=await asyncio.gather(*(asset_checks(client,*asset,semaphore) for asset in ASSETS))
    failures=[{"symbol":row["symbol"],"check":name,"error":check.get("error")} for row in rows for name,check in row["checks"].items() if not check["success"]]
    report={"generated_at":datetime.now(timezone.utc).isoformat(),"base_url":base_url,"assets":rows,
            "summary":{"assets":len(rows),"checks":sum(len(row["checks"]) for row in rows),
                       "passed":sum(check["success"] for row in rows for check in row["checks"].values()),
                       "failed":len(failures)},"failures":failures}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report["summary"],ensure_ascii=False));
    for failure in failures: print(json.dumps(failure,ensure_ascii=False))
    return 1 if failures else 0


if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--base-url",default="http://127.0.0.1:18766")
    parser.add_argument("--output",type=Path,default=Path("work/v191-acceptance.json"));args=parser.parse_args()
    raise SystemExit(asyncio.run(main(args.base_url,args.output)))
