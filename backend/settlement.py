"""Market-aware, idempotent settlement for immutable prediction snapshots."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import pandas as pd

from .database import connection
from .horizons import INTERVAL_MINUTES
from .symbol_master import SymbolIdentity, resolve


@dataclass
class SettlementResult:
    status: str
    market: str
    canonical_symbol: str
    settlement_timestamp: str | None = None
    settlement_price: float | None = None
    return_value: float | None = None
    direction: str | None = None
    risk_outcome: dict | None = None
    reason: str | None = None
    source: str | None = None


class TradingCalendar:
    DAILY_STEPS = {"1D": 1, "T+1": 1, "5D": 5, "T+5": 5, "20D": 20, "T+20": 20, "7D": 7}
    CRYPTO_MINUTES = {"1H": 60, "4H": 240, "24H": 1440, "1D": 1440, "7D": 10080}

    @classmethod
    def settlement_index(cls, identity: SymbolIdentity, prediction_time: str,
                         interval: str, horizon: str, bars: list[dict]) -> tuple[int | None, str | None]:
        if not bars:
            return None, "MISSING_CANDLES"
        stamps = pd.to_datetime([row["timestamp"] for row in bars], utc=True)
        predicted = pd.Timestamp(prediction_time)
        predicted = predicted.tz_localize("UTC") if predicted.tzinfo is None else predicted.tz_convert("UTC")
        first_after = int(stamps.searchsorted(predicted, side="right"))
        if identity.market in {"CN", "US"} or interval == "1d":
            steps = cls.DAILY_STEPS.get(horizon)
            if steps is None:
                return None, "UNSUPPORTED_HORIZON"
            index = first_after + steps - 1
            return (index, None) if index < len(bars) else (None, "TARGET_NOT_OBSERVED")
        minutes = cls.CRYPTO_MINUTES.get(horizon)
        if minutes is None:
            return None, "UNSUPPORTED_HORIZON"
        target = predicted + timedelta(minutes=minutes)
        index = int(stamps.searchsorted(target, side="left"))
        if index >= len(bars):
            return None, "TARGET_NOT_OBSERVED"
        tolerance = timedelta(minutes=max(1, INTERVAL_MINUTES.get(interval, 1)) * 1.1)
        if stamps[index] - target > tolerance:
            return None, "CANDLE_GAP_AT_TARGET"
        return index, None


class PredictionSettlementEngine:
    def settle(self, prediction: dict, candles: list[dict], source: str | None = None) -> SettlementResult:
        identity = resolve(prediction["symbol"], prediction.get("asset_type"))
        ordered = sorted(candles, key=lambda row: pd.Timestamp(row["timestamp"]))
        index, reason = TradingCalendar.settlement_index(
            identity, prediction["prediction_time"], prediction["interval"], prediction["horizon"], ordered)
        if index is None:
            return SettlementResult("PENDING" if reason == "TARGET_NOT_OBSERVED" else "UNAVAILABLE",
                                    identity.market, identity.canonical_symbol, reason=reason, source=source)
        price = float(ordered[index]["close"])
        entry = float(prediction["entry_price"])
        change = price / entry - 1
        threshold = float(prediction["threshold"])
        direction = "UP" if change > threshold else "DOWN" if change < -threshold else "FLAT"
        stamps = pd.to_datetime([row["timestamp"] for row in ordered], utc=True)
        predicted = pd.Timestamp(prediction["prediction_time"])
        predicted = predicted.tz_localize("UTC") if predicted.tzinfo is None else predicted.tz_convert("UTC")
        start = int(stamps.searchsorted(predicted, side="right"))
        path = ordered[start:index + 1]
        side = "LONG" if prediction["prediction"] == "UP" else "SHORT" if prediction["prediction"] == "DOWN" else "FLAT"
        stop, target = prediction.get("stop_loss"), prediction.get("tp1")
        stop_hit = bool(path and stop is not None and
            (min(float(row["low"]) for row in path) <= float(stop) if side == "LONG" else
             max(float(row["high"]) for row in path) >= float(stop) if side == "SHORT" else False))
        target_hit = bool(path and target is not None and
            (max(float(row["high"]) for row in path) >= float(target) if side == "LONG" else
             min(float(row["low"]) for row in path) <= float(target) if side == "SHORT" else False))
        signed_return = change if side == "LONG" else -change if side == "SHORT" else 0.0
        risk = abs(entry - float(stop)) if stop is not None else 0.0
        risk_outcome = {"side": side, "stop_hit": stop_hit, "target_hit": target_hit,
                        "realized_r": signed_return * entry / risk if risk else 0.0}
        return SettlementResult("SETTLED", identity.market, identity.canonical_symbol,
            pd.Timestamp(ordered[index]["timestamp"]).isoformat(), price, change, direction,
            risk_outcome, source=source)


def pending_predictions(limit: int = 5000) -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute("""SELECT * FROM prediction_history
            WHERE actual IS NULL ORDER BY prediction_time LIMIT ?""", (limit,))]


def persist_result(prediction: dict, result: SettlementResult) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    payload = asdict(result)
    with connection() as conn:
        conn.execute("""INSERT OR IGNORE INTO prediction_settlement_audit
            (prediction_id,attempted_at,status,market,canonical_symbol,settlement_timestamp,
             settlement_price,source,reason,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (prediction["id"], now, result.status, result.market, result.canonical_symbol,
             result.settlement_timestamp, result.settlement_price, result.source, result.reason,
             json.dumps(payload, ensure_ascii=False)))
        if result.status != "SETTLED":
            conn.execute("""UPDATE prediction_history SET market=COALESCE(market,?),
                settlement_status=?,settlement_attempted_at=?,settlement_source=?
                WHERE id=? AND actual IS NULL""", (result.market, result.status, now, result.source, prediction["id"]))
            return False
        risk = result.risk_outcome or {}
        correct = int(result.direction == prediction["prediction"])
        cursor = conn.execute("""UPDATE prediction_history SET actual=?,actual_return=?,correct=?,
            stop_hit=?,tp_hit=?,realized_r=?,failure_reason=?,resolved_at=?,expired_at=?,status='RESOLVED',
            market=COALESCE(market,?),settlement_status='SETTLED',settlement_attempted_at=?,settlement_source=?
            WHERE id=? AND actual IS NULL""", (result.direction, result.return_value, correct,
            int(bool(risk.get("stop_hit"))), int(bool(risk.get("target_hit"))), risk.get("realized_r"),
            None if correct else "WRONG_DIRECTION_OR_MAGNITUDE",
            now, now, result.market, now, result.source, prediction["id"]))
        return cursor.rowcount == 1


async def settle_pending(fetcher: Callable[[dict, SymbolIdentity], Awaitable[tuple[list[dict], str]]],
                         limit: int = 5000, cancelled: Callable[[], bool] | None = None) -> dict:
    engine = PredictionSettlementEngine(); rows = pending_predictions(limit)
    summary = {"checked": 0, "settled": 0, "pending": 0, "unavailable": 0, "by_asset": {}}
    grouped: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        grouped.setdefault((row["asset_type"], row["symbol"], row["interval"]), []).append(row)
    for group in grouped.values():
        if cancelled and cancelled():
            summary["cancelled"] = True; break
        identity = resolve(group[0]["symbol"], group[0]["asset_type"])
        try:
            candles, source = await fetcher(group[0], identity)
        except Exception as exc:
            candles, source = [], f"{type(exc).__name__}: {exc}"
        for row in group:
            result = engine.settle(row, candles, source)
            changed = persist_result(row, result)
            summary["checked"] += 1; summary["settled"] += int(changed)
            summary["pending" if result.status == "PENDING" else "unavailable"] += int(result.status != "SETTLED")
            key = f"{result.market}:{result.canonical_symbol}:{row['horizon']}"
            summary["by_asset"].setdefault(key, {"checked": 0, "settled": 0, "status": result.status})
            summary["by_asset"][key]["checked"] += 1
            summary["by_asset"][key]["settled"] += int(changed)
            summary["by_asset"][key]["status"] = result.status
    return summary


def settlement_status() -> dict:
    with connection() as conn:
        rows = [dict(row) for row in conn.execute("""SELECT COALESCE(market,'UNKNOWN') market,
            asset_type,symbol,horizon,COUNT(*) total,SUM(CASE WHEN actual IS NOT NULL THEN 1 ELSE 0 END) settled,
            SUM(CASE WHEN actual IS NULL THEN 1 ELSE 0 END) pending
            FROM prediction_history GROUP BY market,asset_type,symbol,horizon ORDER BY market,symbol,horizon""")]
    return {"assets": rows, "total": sum(row["total"] for row in rows),
            "settled": sum(row["settled"] for row in rows), "pending": sum(row["pending"] for row in rows)}


def settle_asset(symbol: str, asset_type: str, interval: str, candles: list[dict], source: str) -> int:
    engine = PredictionSettlementEngine(); changed = 0
    with connection() as conn:
        rows = [dict(row) for row in conn.execute("""SELECT * FROM prediction_history
            WHERE symbol=? AND asset_type=? AND interval=? AND actual IS NULL""",
            (symbol, asset_type, interval))]
    for row in rows:
        changed += int(persist_result(row, engine.settle(row, candles, source)))
    return changed
