"""Observe an actual OKX stream for 1/5/15-minute acceptance checkpoints."""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import websockets


async def observe(duration: int, symbol: str) -> dict:
    started=time.time(); prices=[];ticker_stamps=[];candle_closes=[];candle_volumes=[];candle_stamps=[];trades=set()
    checkpoints={60:None,300:None,900:None}
    async with websockets.connect("wss://ws.okx.com:8443/ws/v5/public",ping_interval=15,ping_timeout=12) as public, \
               websockets.connect("wss://ws.okx.com:8443/ws/v5/business",ping_interval=15,ping_timeout=12) as business:
        await public.send(json.dumps({"op":"subscribe","args":[{"channel":"tickers","instId":symbol},{"channel":"trades","instId":symbol}]}))
        await business.send(json.dumps({"op":"subscribe","args":[{"channel":"candle1m","instId":symbol}]}))
        async def reader(ws,kind):
            async for raw in ws:
                message=json.loads(raw);channel=message.get("arg",{}).get("channel")
                for row in message.get("data",[]):
                    if channel=="tickers":prices.append(float(row["last"]));ticker_stamps.append(row["ts"])
                    elif channel=="trades":trades.add(row["tradeId"])
                    elif channel=="candle1m":
                        candle_stamps.append(row[0]);candle_closes.append(float(row[4]));candle_volumes.append(float(row[5]))
        tasks=[asyncio.create_task(reader(public,"public")),asyncio.create_task(reader(business,"business"))]
        try:
            while time.time()-started<duration:
                elapsed=int(time.time()-started)
                for mark in checkpoints:
                    if checkpoints[mark] is None and elapsed>=min(mark,duration):
                        checkpoints[mark]={"elapsed_seconds":elapsed,"ticker_events":len(ticker_stamps),"unique_prices":len(set(prices)),
                            "unique_timestamps":len(set(ticker_stamps)),"trade_events":len(trades),"candle_events":len(candle_stamps),
                            "unique_candle_closes":len(set(candle_closes)),"unique_candle_volumes":len(set(candle_volumes))}
                await asyncio.sleep(1)
        finally:
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    final_snapshot={"elapsed_seconds":int(time.time()-started),"ticker_events":len(ticker_stamps),
        "unique_prices":len(set(prices)),"unique_timestamps":len(set(ticker_stamps)),"trade_events":len(trades),
        "candle_events":len(candle_stamps),"unique_candle_closes":len(set(candle_closes)),
        "unique_candle_volumes":len(set(candle_volumes))}
    # The loop condition can cross the exact final second between iterations;
    # preserve the actually observed final totals instead of leaving 900 null.
    applicable={key:(value or final_snapshot) for key,value in checkpoints.items() if key<=duration}
    passed=bool(prices and len(set(ticker_stamps))>1 and trades and candle_closes and
                (len(set(prices))>1 or len(set(candle_closes))>1 or len(set(candle_volumes))>1))
    return {"test":"REAL OKX WebSocket; no fixtures","symbol":symbol,"started_at":datetime.fromtimestamp(started,timezone.utc).isoformat(),
            "finished_at":datetime.now(timezone.utc).isoformat(),"duration_seconds":int(time.time()-started),"checkpoints":applicable,
            "observed":{"ticker_events":len(ticker_stamps),"unique_prices":len(set(prices)),"trade_events":len(trades),
                        "candle_events":len(candle_stamps),"unique_candle_closes":len(set(candle_closes)),
                        "unique_candle_volumes":len(set(candle_volumes))},"pass":passed}


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--duration",type=int,default=900);parser.add_argument("--symbol",default="BTC-USDT")
    parser.add_argument("--output",default="outputs/realtime-live-test.json");args=parser.parse_args()
    result=asyncio.run(observe(args.duration,args.symbol));path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8");print(json.dumps(result,ensure_ascii=False,indent=2))
    raise SystemExit(0 if result["pass"] else 1)


if __name__=="__main__":main()
