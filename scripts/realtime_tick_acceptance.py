"""30-second production WebSocket acceptance check (no fixtures or random data)."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.realtime import RealtimeDataManager


async def main() -> None:
    manager = RealtimeDataManager()
    states = {interval: await manager.store.get_or_create("crypto", "BTC", interval)
              for interval in manager.OKX_BARS}
    await manager._bootstrap(states["1m"])
    samples, updates, started = [], 0, None
    targets = [0, 5, 10, 30]
    async with websockets.connect(manager.OKX_PUBLIC, ping_interval=15, ping_timeout=12) as socket:
        await socket.send(json.dumps({"op":"subscribe","args":[{"channel":"trades","instId":"BTC-USDT"}]}))
        while len(samples) < len(targets):
            message = json.loads(await asyncio.wait_for(socket.recv(), 15))
            for row in message.get("data", []):
                started = started or time.monotonic()
                for state in states.values():
                    await manager.process_trade(state, row)
                updates += 1
                elapsed = time.monotonic() - started
                if elapsed >= targets[len(samples)]:
                    state = states["1m"]
                    latest = (state.indicators or {}).get("latest", {})
                    samples.append({"second":targets[len(samples)], "observed_after":round(elapsed, 2),
                                    "price":state.candles[-1]["close"], "volume":state.candles[-1]["volume"],
                                    "tick_count":state.candles[-1].get("tick_count"), "rsi":latest.get("rsi"),
                                    "macd":latest.get("macd"), "periods":{
                                        interval:{"timestamp":target.candles[-1]["timestamp"],
                                                  "close":target.candles[-1]["close"],"volume":target.candles[-1]["volume"]}
                                        for interval,target in states.items()}})
                if len(samples) == len(targets):
                    break
    changed = lambda key: len({sample[key] for sample in samples}) > 1
    print(json.dumps({"source":"OKX trades WebSocket","duration_seconds":30,"trade_messages":updates,
                      "price_changed":changed("price"),"volume_changed":changed("volume"),
                      "indicator_changed":changed("rsi") or changed("macd"),"samples":samples},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
