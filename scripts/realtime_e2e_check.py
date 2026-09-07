"""Check the running backend WebSocket boundary without browser automation."""
from __future__ import annotations
import argparse,asyncio,json
import websockets

async def main(url:str,count:int):
    seen=[]
    async with websockets.connect(url) as socket:
        hello=json.loads(await socket.recv());assert hello["type"]=="hello"
        await socket.send(json.dumps({"action":"subscribe","asset_type":"crypto","symbol":"BTC","interval":"1m"}))
        while len(seen)<count:
            event=json.loads(await asyncio.wait_for(socket.recv(),30));seen.append(event["type"])
            print(event["type"],event.get("key"),event.get("serverTimestamp") or event.get("data",{}).get("serverTimestamp"))
    required={"snapshot","ticker","candle","analysis"}
    missing=required-set(seen);print(json.dumps({"seen":seen,"missing":sorted(missing),"pass":not missing},ensure_ascii=False))
    raise SystemExit(1 if missing else 0)

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--url",default="ws://127.0.0.1:8765/api/realtime/ws");parser.add_argument("--count",type=int,default=20)
    args=parser.parse_args();asyncio.run(main(args.url,args.count))
