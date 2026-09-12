from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

from backend.ai_engine import predict
from backend.market import crypto_kline, crypto_quote, stock_kline, stock_quote
from backend.news_intelligence import build_intelligence
from backend.database import load_news_intelligence
from backend.quant_v2 import benchmark, feature_catalog
from backend.strategy_engine import StrategyEngine

ASSETS=[("stock","600519"),("stock","000001"),("stock","300750"),
        ("stock","NVDA"),("stock","AAPL"),("stock","TSLA"),
        ("crypto","BTC"),("crypto","ETH"),("crypto","SOL")]


async def one(asset_type: str,symbol: str) -> dict:
    quote=await (stock_quote(symbol) if asset_type=="stock" else crypto_quote(symbol))
    candles,source=await (stock_kline(symbol,"1d",1200) if asset_type=="stock" else crypto_kline(symbol,"1d",1200))
    features=feature_catalog(candles,source)
    news=load_news_intelligence(symbol);events=build_intelligence(news,symbol)["all_news"] if news else []
    regime=StrategyEngine().analyze(candles,"1d",source)["market_regime"]
    model=benchmark(candles,asset_type,symbol,"1d","1D",3)
    best=model["best_model"];best_metrics=model["models"].get(best,{}).get("metrics",{})
    return {"symbol":symbol,"asset_type":asset_type,"quote":quote["price"]>0,"kline":len(candles),
            "features":features["feature_count"],"news":len(news),"events":len(events),"regime":regime,
            "best_model":best,"decision":model["decision"],"best_metrics":best_metrics,
            "majority_accuracy":model["models"]["MajorityBaseline"]["metrics"]["directional_accuracy"],
            "buy_hold":model["models"]["BuyAndHold"]["metrics"],
            "ensemble":model["models"].get("ValidationWeightedEnsemble",{}).get("metrics"),
            "unavailable":sorted(model["unavailable_models"]),"cutoff":model["information_cutoff"]}


async def main() -> None:
    results=[]
    for asset_type,symbol in ASSETS:
        try:results.append(await one(asset_type,symbol))
        except Exception as exc:results.append({"symbol":symbol,"asset_type":asset_type,"error":f"{type(exc).__name__}: {exc}"})
    print(json.dumps(results,ensure_ascii=False,indent=2,default=str))


if __name__=="__main__":asyncio.run(main())
