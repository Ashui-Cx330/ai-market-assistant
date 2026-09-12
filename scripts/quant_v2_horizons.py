from __future__ import annotations
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.market import crypto_kline,stock_kline
from backend.quant_v2 import benchmark

async def main():
    btc1,src1=await crypto_kline("BTC","1h",1200);btcd,srcd=await crypto_kline("BTC","1d",1200)
    nvda,srcn=await stock_kline("NVDA","1d",1200);out=[]
    for candles,kind,symbol,interval,horizon in [(btc1,"crypto","BTC","1h","1H"),(btc1,"crypto","BTC","1h","4H"),
        (btcd,"crypto","BTC","1d","7D"),(nvda,"stock","NVDA","1d","T+5"),(nvda,"stock","NVDA","1d","T+20")]:
        try:
            x=benchmark(candles,kind,symbol,interval,horizon,3);m=x["models"][x["best_model"]]["metrics"]
            out.append({"symbol":symbol,"horizon":horizon,"best":x["best_model"],"decision":x["decision"],"metrics":m,
                        "baseline":x["models"]["MajorityBaseline"]["metrics"]["directional_accuracy"],
                        "buy_hold":x["models"]["BuyAndHold"]["metrics"]})
        except Exception as exc:out.append({"symbol":symbol,"horizon":horizon,"error":f"{type(exc).__name__}: {exc}"})
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=="__main__":asyncio.run(main())
