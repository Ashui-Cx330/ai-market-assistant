from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

UTC = timezone.utc
SHANGHAI = ZoneInfo("Asia/Shanghai")
INTERVAL_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60, "4h": 240, "1d": 1440}
HORIZON_MINUTES = {"1H": 60, "4H": 240, "1D": 1440}


def utc_timestamps(values: list[dict] | list[str]) -> pd.DatetimeIndex:
    raw = [v["timestamp"] if isinstance(v, dict) else v for v in values]
    parsed: list[pd.Timestamp] = []
    for value in raw:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize(SHANGHAI)
        parsed.append(stamp.tz_convert(UTC))
    return pd.DatetimeIndex(parsed)


def supported_horizons(interval: str) -> dict[str, int]:
    if interval not in INTERVAL_MINUTES:
        raise ValueError(f"不支持的 K 线周期：{interval}")
    bar = INTERVAL_MINUTES[interval]
    result: dict[str, int] = {}
    for label, duration in HORIZON_MINUTES.items():
        if duration >= bar and duration % bar == 0:
            result[label] = duration // bar
    return result


def horizon_bar_count(asset_type: str, interval: str, horizon: str) -> int:
    """Nominal bars for display; alignment always remains timestamp based."""
    supported_horizons(interval)[horizon]
    if asset_type == "stock" and horizon == "1D" and interval != "1d":
        return 240 // INTERVAL_MINUTES[interval]
    return HORIZON_MINUTES[horizon] // INTERVAL_MINUTES[interval]


def _next_weekday(value: date) -> date:
    current = value + timedelta(days=1)
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current


def add_stock_trading_minutes(value: datetime | pd.Timestamp, minutes: int) -> pd.Timestamp:
    """Add mainland-China *trading* minutes, skipping lunch, nights and weekends.

    Exchange holidays are resolved by target alignment against actual candles; this
    function deliberately does not invent a holiday calendar.
    """
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize(SHANGHAI) if stamp.tzinfo is None else stamp.tz_convert(SHANGHAI)
    remaining = int(minutes)
    day = stamp.date()
    cursor = stamp
    while remaining > 0:
        while day.weekday() >= 5:
            day = _next_weekday(day)
        morning_start = pd.Timestamp(datetime.combine(day, time(9, 30)), tz=SHANGHAI)
        morning_end = pd.Timestamp(datetime.combine(day, time(11, 30)), tz=SHANGHAI)
        afternoon_start = pd.Timestamp(datetime.combine(day, time(13, 0)), tz=SHANGHAI)
        afternoon_end = pd.Timestamp(datetime.combine(day, time(15, 0)), tz=SHANGHAI)
        if cursor < morning_start:
            cursor = morning_start
        elif morning_end <= cursor < afternoon_start:
            cursor = afternoon_start
        elif cursor >= afternoon_end:
            day = _next_weekday(day)
            cursor = pd.Timestamp(datetime.combine(day, time(9, 30)), tz=SHANGHAI)
            continue
        session_end = morning_end if cursor < morning_end else afternoon_end
        available = max(0, int((session_end - cursor).total_seconds() // 60))
        used = min(remaining, available)
        cursor += timedelta(minutes=used)
        remaining -= used
        if remaining and cursor >= morning_end and cursor < afternoon_start:
            cursor = afternoon_start
        elif remaining and cursor >= afternoon_end:
            day = _next_weekday(day)
            cursor = pd.Timestamp(datetime.combine(day, time(9, 30)), tz=SHANGHAI)
    return cursor.tz_convert(UTC)


def future_timestamp(value: datetime | pd.Timestamp, asset_type: str, interval: str, horizon: str) -> pd.Timestamp:
    if horizon not in supported_horizons(interval):
        raise ValueError(f"{interval} K 线无法严格表达未来 {horizon}")
    stamp = pd.Timestamp(value)
    stamp = stamp.tz_localize(UTC) if stamp.tzinfo is None else stamp.tz_convert(UTC)
    if asset_type == "crypto":
        return stamp + timedelta(minutes=HORIZON_MINUTES[horizon])
    if interval == "1d" or horizon == "1D":
        # A-share 1D means the same point in the next trading session, not 1,440
        # exchange-open minutes (six sessions). Actual holiday gaps are handled
        # by alignment against the observed candle timestamps.
        local = stamp.tz_convert(SHANGHAI)
        next_day = _next_weekday(local.date())
        return pd.Timestamp(datetime.combine(next_day, local.time()), tz=SHANGHAI).tz_convert(UTC)
    return add_stock_trading_minutes(stamp, HORIZON_MINUTES[horizon])


def target_indices(timestamps: pd.DatetimeIndex, asset_type: str, interval: str, horizon: str) -> np.ndarray:
    """Return the first real candle at/after every timestamp target, or -1.

    Crypto alignment rejects gaps larger than one bar. A-share alignment accepts
    weekend/holiday gaps but only advances over actual future trading candles.
    """
    supported_horizons(interval)[horizon]
    result = np.full(len(timestamps), -1, dtype=int)
    if interval == "1d" and asset_type == "stock":
        steps = supported_horizons(interval)[horizon]
        for index in range(len(timestamps) - steps):
            result[index] = index + steps
        return result
    bar_delta = timedelta(minutes=int(INTERVAL_MINUTES[interval]))
    for index, stamp in enumerate(timestamps):
        target = future_timestamp(stamp, asset_type, interval, horizon)
        found = int(timestamps.searchsorted(target, side="left"))
        if found >= len(timestamps) or found <= index:
            continue
        if asset_type == "crypto" and timestamps[found] - target > bar_delta * 1.1:
            continue
        result[index] = found
    return result
