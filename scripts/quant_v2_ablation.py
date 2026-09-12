from __future__ import annotations
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.market import stock_kline,crypto_kline
from backend.quant_v2 import ablation

async def main():
    out=[]
    for kind,symbol in (("stock","600519"),("stock","NVDA"),("crypto","BTC")):
        candles,_=await (stock_kline(symbol,"1d",1200) if kind=="stock" else crypto_kline(symbol,"1d",1200))
        out.append({"symbol":symbol,**ablation(candles,kind,symbol)})
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=="__main__":asyncio.run(main())
