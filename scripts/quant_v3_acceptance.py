from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.market import crypto_kline, stock_kline
from backend.quant_v3 import dataset_audit, run_research

UNIVERSES = {
    "CN": ["600519", "000001", "300750", "000858", "601318"],
    "US": ["NVDA", "AMD", "AVGO", "TSM", "MU"],
    "CRYPTO": ["BTC", "ETH", "SOL", "BNB", "XRP"],
}


async def fetch_market(market: str, interval: str) -> tuple[dict, dict]:
    async def one(symbol: str):
        candles, source = await (crypto_kline(symbol, interval, 1200) if market == "CRYPTO"
                                 else stock_kline(symbol, interval, 1200))
        return symbol, candles, source
    rows = await asyncio.gather(*(one(symbol) for symbol in UNIVERSES[market]), return_exceptions=True)
    universe, sources, errors = {}, {}, []
    for row in rows:
        if isinstance(row, Exception):
            errors.append(f"{type(row).__name__}: {row}")
        elif len(row[1]) >= 260:
            universe[row[0]], sources[row[0]] = row[1], row[2]
        else:
            errors.append(f"{row[0]} only {len(row[1])} rows")
    return universe, {"sources": sources, "errors": errors}


async def main() -> None:
    result = {"runs": [], "fetch": {}}
    plans = [("CN", "1d", ["1D", "T+5", "T+20"]),
             ("US", "1d", ["1D", "T+5", "T+20"]),
             ("CRYPTO", "1h", ["1H", "4H", "1D"]),
             ("CRYPTO", "1d", ["7D"])]
    cache = {}
    for market, interval, horizons in plans:
        key = f"{market}-{interval}"
        if key not in cache:
            cache[key] = await fetch_market(market, interval)
            result["fetch"][key] = cache[key][1]
        universe = cache[key][0]
        result.setdefault("audits", {})[key] = dataset_audit(universe, market, interval)
        for horizon in horizons:
            try:
                study = await asyncio.to_thread(run_research, universe, market, interval, horizon, 5)
                result["runs"].append(study)
                print(f"PASS {market} {interval} {horizon}: {study['decision']}", flush=True)
            except Exception as exc:
                result["runs"].append({"market": market, "interval": interval, "horizon": horizon,
                                       "error": f"{type(exc).__name__}: {exc}"})
                print(f"FAIL {market} {interval} {horizon}: {exc}", flush=True)
    target = ROOT / "work" / "quant-v3-acceptance.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    asyncio.run(main())
