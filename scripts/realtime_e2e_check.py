"""Check the running backend WebSocket boundary without browser automation."""
from __future__ import annotations
import argparse,asyncio,json,time
import websockets

async def main(url:str,duration:int):
    seen=[];required={"snapshot","ticker","candle","analysis"};target="crypto:BTC:1m"
    async with websockets.connect(url) as socket:
        hello=json.loads(await socket.recv());assert hello["type"]=="hello"
        await socket.send(json.dumps({"action":"subscribe","asset_type":"crypto","symbol":"BTC","interval":"1m"}))
        deadline=time.monotonic()+duration
        while time.monotonic()<deadline and not required.issubset(seen):
            try:event=json.loads(await asyncio.wait_for(socket.recv(),max(.1,deadline-time.monotonic())))
            except asyncio.TimeoutError:break
            if event.get("key") not in (None,target):continue
            seen.append(event["type"])
            print(event["type"],event.get("key"),event.get("serverTimestamp") or event.get("data",{}).get("serverTimestamp"))
    missing=required-set(seen);print(json.dumps({"seen":seen,"missing":sorted(missing),"pass":not missing},ensure_ascii=False))
    raise SystemExit(1 if missing else 0)

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--url",default="ws://127.0.0.1:8765/api/realtime/ws");parser.add_argument("--duration",type=int,default=30)
    args=parser.parse_args();asyncio.run(main(args.url,args.duration))
