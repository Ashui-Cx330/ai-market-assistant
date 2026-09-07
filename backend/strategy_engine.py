from __future__ import annotations

"""Causal technical-strategy engine.

Every historical decision is made from a prefix of the candle stream.  Pivots
carry an ``available_at`` timestamp and cannot be consumed before the right-side
confirmation bars have closed.  Missing order-book/options inputs are reported,
never synthesized from OHLCV.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import math
from typing import Any

import numpy as np
import pandas as pd

from .indicators import candle_frame


SIGNAL_KEYS = (
    "trend", "breakout", "pullback", "reversal", "range", "moving_average",
    "bollinger", "rsi_breakout", "rsi_reversal", "macd", "fibonacci", "gann",
    "stochastic", "psar", "momentum", "mfi", "double_top_bottom",
    "head_shoulders", "triangle", "donchian", "wedge", "flag", "order_flow",
    "atr", "options", "ict_smc", "fvg", "bos", "choch", "fib_fvg_bos",
)


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _round(value: Any, digits: int = 6):
    try:
        number = float(value)
        return round(number, digits) if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _crossed_up(a: pd.Series, b: pd.Series | float) -> bool:
    other = b if isinstance(b, pd.Series) else pd.Series(float(b), index=a.index)
    return len(a) > 1 and _finite(a.iloc[-2]) <= _finite(other.iloc[-2]) and _finite(a.iloc[-1]) > _finite(other.iloc[-1])


def _crossed_down(a: pd.Series, b: pd.Series | float) -> bool:
    other = b if isinstance(b, pd.Series) else pd.Series(float(b), index=a.index)
    return len(a) > 1 and _finite(a.iloc[-2]) >= _finite(other.iloc[-2]) and _finite(a.iloc[-1]) < _finite(other.iloc[-1])


def _slope(series: pd.Series, bars: int = 5) -> float:
    values = series.dropna().tail(bars + 1)
    return float(values.iloc[-1] / values.iloc[0] - 1) if len(values) > 1 and values.iloc[0] else 0.0


def extended_indicators(candles: list[dict]) -> pd.DataFrame:
    df = candle_frame(candles)
    if df.empty:
        return df
    df["timestamp_utc"] = pd.to_datetime(df["timestamp"], utc=True)
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"].clip(lower=0)
    for period in (20, 50, 100, 200):
        df[f"sma{period}"] = close.rolling(period).mean()
        df[f"ema{period}"] = close.ewm(span=period, adjust=False).mean()
    weights = np.arange(1, 21, dtype=float)
    df["wma20"] = close.rolling(20).apply(lambda values: float(np.dot(values, weights) / weights.sum()), raw=True)
    delta = close.diff(); gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean(); loss = -delta.clip(upper=0).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(50)
    df["ema12"] = close.ewm(span=12, adjust=False).mean(); df["ema26"] = close.ewm(span=26, adjust=False).mean()
    df["macd"] = df["ema12"] - df["ema26"]; df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean(); df["macd_hist"] = df["macd"] - df["macd_signal"]
    previous = close.shift(1)
    df["tr"] = pd.concat([high - low, (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    df["atr"] = df["tr"].ewm(alpha=1 / 14, adjust=False).mean(); df["atr_percent"] = df["atr"] / close.replace(0, np.nan)
    plus_dm = high.diff().where((high.diff() > -low.diff()) & (high.diff() > 0), 0.0)
    minus_dm = (-low.diff()).where((-low.diff() > high.diff()) & (-low.diff() > 0), 0.0)
    plus_di = 100 * plus_dm.ewm(alpha=1 / 14, adjust=False).mean() / df["atr"].replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1 / 14, adjust=False).mean() / df["atr"].replace(0, np.nan)
    df["adx"] = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)).ewm(alpha=1 / 14, adjust=False).mean()
    middle = close.rolling(20).mean(); std = close.rolling(20).std()
    df["boll_mid"] = middle; df["boll_upper"] = middle + 2 * std; df["boll_lower"] = middle - 2 * std
    df["boll_width"] = (df["boll_upper"] - df["boll_lower"]) / middle.replace(0, np.nan); df["boll_percent_b"] = (close - df["boll_lower"]) / (df["boll_upper"] - df["boll_lower"]).replace(0, np.nan)
    low14, high14 = low.rolling(14).min(), high.rolling(14).max()
    df["stoch_k"] = (100 * (close - low14) / (high14 - low14).replace(0, np.nan)).fillna(50); df["stoch_d"] = df["stoch_k"].rolling(3).mean()
    typical = (high + low + close) / 3; raw_flow = typical * volume; positive = raw_flow.where(typical.diff() > 0, 0.0); negative = raw_flow.where(typical.diff() < 0, 0.0)
    ratio = positive.rolling(14).sum() / negative.rolling(14).sum().replace(0, np.nan); df["mfi"] = (100 - 100 / (1 + ratio)).fillna(50)
    direction = np.sign(close.diff()).fillna(0); df["obv"] = (direction * volume).cumsum()
    cumulative_volume = volume.cumsum().replace(0, np.nan); df["vwap"] = (typical * volume).cumsum() / cumulative_volume
    df["roc"] = close.pct_change(10); df["momentum"] = close - close.shift(10); df["acceleration"] = df["roc"].diff(3)
    df["volume_ratio"] = volume / volume.rolling(30).median().replace(0, np.nan)
    for period in (20, 55, 100):
        # Shifted channels exclude the current candle, preventing self-confirming breakouts.
        df[f"donchian_upper_{period}"] = high.shift(1).rolling(period).max()
        df[f"donchian_lower_{period}"] = low.shift(1).rolling(period).min()
    df["return_1"] = close.pct_change(); df["volatility"] = df["return_1"].rolling(20).std()
    df["psar"] = _parabolic_sar(df); df["psar_trend"] = np.where(close >= df["psar"], 1, -1)
    return df


def _parabolic_sar(df: pd.DataFrame, step: float = .02, maximum: float = .2) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    high, low = df["high"].to_numpy(float), df["low"].to_numpy(float)
    sar = np.zeros(len(df)); sar[0] = low[0]; up = True; extreme = high[0]; acceleration = step
    for index in range(1, len(df)):
        candidate = sar[index - 1] + acceleration * (extreme - sar[index - 1])
        if up:
            candidate = min(candidate, low[index - 1], low[index - 2] if index > 1 else low[index - 1])
            if low[index] < candidate: up = False; candidate = extreme; extreme = low[index]; acceleration = step
            elif high[index] > extreme: extreme = high[index]; acceleration = min(maximum, acceleration + step)
        else:
            candidate = max(candidate, high[index - 1], high[index - 2] if index > 1 else high[index - 1])
            if high[index] > candidate: up = True; candidate = extreme; extreme = high[index]; acceleration = step
            elif low[index] < extreme: extreme = low[index]; acceleration = min(maximum, acceleration + step)
        sar[index] = candidate
    return pd.Series(sar, index=df.index)


class CausalSwingDetector:
    def __init__(self, left: int = 3, right: int = 3):
        self.left, self.right = left, right

    def detect(self, frame: pd.DataFrame) -> list[dict]:
        swings: list[dict] = []
        for pivot in range(self.left, len(frame) - self.right):
            available = pivot + self.right
            hi = float(frame["high"].iloc[pivot]); lo = float(frame["low"].iloc[pivot])
            left_hi = frame["high"].iloc[pivot - self.left:pivot]; right_hi = frame["high"].iloc[pivot + 1:available + 1]
            left_lo = frame["low"].iloc[pivot - self.left:pivot]; right_lo = frame["low"].iloc[pivot + 1:available + 1]
            kind = "HIGH" if hi > left_hi.max() and hi >= right_hi.max() else "LOW" if lo < left_lo.min() and lo <= right_lo.min() else None
            if kind:
                price = hi if kind == "HIGH" else lo
                swings.append({"swing_id": f"{kind}-{pivot}", "kind": kind, "price": _round(price), "pivot_index": pivot,
                               "formation_time": frame["timestamp_utc"].iloc[pivot].isoformat(), "available_index": available,
                               "available_at": frame["timestamp_utc"].iloc[available].isoformat()})
        return swings


def detect_structure(frame: pd.DataFrame, swings: list[dict]) -> dict:
    events: list[dict] = []; trend = "RANGE"; last_broken: set[str] = set()
    for index in range(1, len(frame)):
        known = [s for s in swings if s["available_index"] < index]
        highs = [s for s in known if s["kind"] == "HIGH" and s["swing_id"] not in last_broken]
        lows = [s for s in known if s["kind"] == "LOW" and s["swing_id"] not in last_broken]
        close, previous = float(frame["close"].iloc[index]), float(frame["close"].iloc[index - 1])
        atr = max(_finite(frame["atr"].iloc[index], close * .002), close * .0005)
        volume_ratio = _finite(frame["volume_ratio"].iloc[index], 1)
        candidate = None; direction = None
        if highs and previous <= highs[-1]["price"] < close and close - highs[-1]["price"] >= .05 * atr:
            candidate, direction = highs[-1], "BULLISH"
        elif lows and previous >= lows[-1]["price"] > close and lows[-1]["price"] - close >= .05 * atr:
            candidate, direction = lows[-1], "BEARISH"
        if candidate:
            event_type = "CHOCH" if (trend == "DOWN" and direction == "BULLISH") or (trend == "UP" and direction == "BEARISH") else "BOS"
            confirmation = "VOLUME_CONFIRMED" if volume_ratio >= 1.2 else "CLOSE_CONFIRMED"
            events.append({"type": event_type, "swing_id": candidate["swing_id"], "break_price": _round(candidate["price"]),
                           "break_time": frame["timestamp_utc"].iloc[index].isoformat(), "break_index": index,
                           "direction": direction, "volume": _round(frame["volume"].iloc[index], 2), "volume_ratio": _round(volume_ratio, 3),
                           "confirmation": confirmation, "available_at": frame["timestamp_utc"].iloc[index].isoformat()})
            last_broken.add(candidate["swing_id"]); trend = "UP" if direction == "BULLISH" else "DOWN"
    highs = [s for s in swings if s["kind"] == "HIGH"]; lows = [s for s in swings if s["kind"] == "LOW"]
    return {"trend": trend, "events": events, "latest_bos": next((e for e in reversed(events) if e["type"] == "BOS"), None),
            "latest_choch": next((e for e in reversed(events) if e["type"] == "CHOCH"), None),
            "swing_highs": highs[-8:], "swing_lows": lows[-8:]}


def detect_fvgs(frame: pd.DataFrame) -> list[dict]:
    output: list[dict] = []
    for index in range(2, len(frame)):
        first, third = frame.iloc[index - 2], frame.iloc[index]
        if float(first["high"]) < float(third["low"]): direction, bottom, top = "BULLISH", float(first["high"]), float(third["low"])
        elif float(first["low"]) > float(third["high"]): direction, bottom, top = "BEARISH", float(third["high"]), float(first["low"])
        else: continue
        size = top - bottom; future = frame.iloc[index + 1:]
        if direction == "BULLISH": penetration = ((top - future["low"]) / max(size, 1e-12)).clip(0, 1)
        else: penetration = ((future["high"] - bottom) / max(size, 1e-12)).clip(0, 1)
        filled = float(penetration.max()) if len(penetration) else 0.0
        output.append({"fvg_id": f"{direction}-{index}", "direction": direction, "bottom": _round(bottom), "top": _round(top),
                       "size": _round(size), "size_atr": _round(size / max(_finite(frame["atr"].iloc[index], size), 1e-12), 3),
                       "creation_time": frame["timestamp_utc"].iloc[index].isoformat(), "available_at": frame["timestamp_utc"].iloc[index].isoformat(),
                       "creation_index": index, "age": len(frame) - 1 - index, "filled_percent": round(filled * 100, 2),
                       "status": "FILLED" if filled >= .999 else "PARTIALLY_FILLED" if filled > 0 else "OPEN"})
    return output


def fibonacci_structure(frame: pd.DataFrame, swings: list[dict], trend: str) -> dict:
    known = sorted(swings, key=lambda item: item["available_index"])
    if len(known) < 2:
        return {"status": "INSUFFICIENT_EVIDENCE", "levels": {}}
    pair = None
    for first, second in zip(reversed(known[:-1]), reversed(known[1:])):
        if first["kind"] != second["kind"]:
            pair = (first, second); break
    if pair is None:
        return {"status": "INSUFFICIENT_EVIDENCE", "levels": {}}
    low_swing = pair[0] if pair[0]["kind"] == "LOW" else pair[1]; high_swing = pair[0] if pair[0]["kind"] == "HIGH" else pair[1]
    low, high = float(low_swing["price"]), float(high_swing["price"]); span = max(high - low, 1e-12)
    direction = "UP" if high_swing["pivot_index"] > low_swing["pivot_index"] else "DOWN"
    ratios = (0, .236, .382, .5, .618, .786, 1, 1.272, 1.618, 2.0)
    levels = {str(ratio): _round((high - span * ratio if ratio <= 1 else low + span * ratio) if direction == "UP"
                                 else (low + span * ratio if ratio <= 1 else high - span * ratio)) for ratio in ratios}
    return {"status": "AVAILABLE", "direction": direction, "swing_low": low_swing, "swing_high": high_swing,
            "levels": levels, "formation_time": max(low_swing["formation_time"], high_swing["formation_time"]),
            "available_at": max(low_swing["available_at"], high_swing["available_at"]), "market_structure": trend}


def data_quality(frame: pd.DataFrame, source: str = "OHLCV") -> dict:
    required = ["open", "high", "low", "close", "volume"]
    completeness = 1 - float(frame[required].isna().mean().mean())
    monotonic = float(frame["timestamp_utc"].is_monotonic_increasing)
    gaps = frame["timestamp_utc"].diff().dropna(); continuity = float((gaps <= gaps.median() * 3).mean()) if len(gaps) else 0
    valid = ((frame["high"] >= frame[["open", "close"]].max(axis=1)) & (frame["low"] <= frame[["open", "close"]].min(axis=1)) & (frame["volume"] >= 0)).mean()
    latency = (pd.Timestamp.now(tz="UTC") - frame["timestamp_utc"].iloc[-1]).total_seconds() if len(frame) else math.inf
    expected = gaps.median().total_seconds() if len(gaps) else 3600; freshness = max(0.0, 1 - latency / max(expected * 20, 1))
    score = round(100 * (.3 * completeness + .2 * monotonic + .2 * continuity + .2 * valid + .1 * freshness))
    return {"score": max(0, min(100, score)), "source": source, "data_timestamp": frame["timestamp_utc"].iloc[-1].isoformat(),
            "components": {"completeness": round(completeness, 4), "time_order": monotonic, "continuity": round(continuity, 4),
                           "ohlcv_validity": round(float(valid), 4), "freshness": round(freshness, 4)},
            "status": "AVAILABLE" if score >= 60 else "LOW_QUALITY"}


def market_regime(frame: pd.DataFrame) -> dict:
    last = frame.iloc[-1]; close = float(last["close"]); atrp = _finite(last["atr_percent"])
    vol_history = frame["atr_percent"].dropna(); vol_rank = float((vol_history <= atrp).mean()) if len(vol_history) else .5
    trend_score = np.tanh((_slope(frame["ema20"], 8) + _slope(frame["ema50"], 12)) / max(atrp, 1e-6))
    adx = _finite(last["adx"])
    primary = "TREND_UP" if trend_score > .35 and adx >= 18 else "TREND_DOWN" if trend_score < -.35 and adx >= 18 else "RANGE"
    volatility = "HIGH_VOLATILITY" if vol_rank >= .8 else "LOW_VOLATILITY" if vol_rank <= .2 else "NORMAL_VOLATILITY"
    return {"primary": primary, "volatility": volatility, "trend_score": _round(trend_score, 4), "volatility_percentile": _round(vol_rank, 4), "adx": _round(adx, 2)}


@dataclass
class StrategySignal:
    strategy: str
    signal: str = "HOLD"
    strength: float = 0
    confidence: float = 0
    timeframe: str = ""
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_reward: float | None = None
    expected_value: float | None = None
    market_regime: str = ""
    reason: str = ""
    evidence: list[dict] = field(default_factory=list)
    timestamp: str = ""
    data_quality: float = 0
    status: str = "AVAILABLE"
    metadata: dict = field(default_factory=dict)

    def payload(self) -> dict:
        return asdict(self)


class BaseStrategy:
    key = "base"
    family = "price"
    minimum_bars = 60

    def unavailable(self, context: dict, status: str, reason: str) -> StrategySignal:
        return StrategySignal(self.key, timeframe=context["timeframe"], timestamp=context["timestamp"],
                              data_quality=context["quality"]["score"], market_regime=context["regime"]["primary"], status=status, reason=reason)

    def result(self, context: dict, score: float, reason: str, evidence: list[dict], metadata: dict | None = None,
               allow_trade: bool = True) -> StrategySignal:
        quality = context["quality"]["score"] / 100; adjusted = float(np.clip(score * quality, -100, 100))
        threshold = float(context.get("parameters", {}).get("signal_threshold", 24))
        signal = "BUY" if adjusted >= threshold and allow_trade else "SELL" if adjusted <= -threshold and allow_trade else "HOLD"
        strength = abs(adjusted); confidence = min(100.0, strength * .7 + context["quality"]["score"] * .3)
        return StrategySignal(self.key, signal, round(strength, 2), round(confidence, 2), context["timeframe"],
                              entry=_round(context["price"]), market_regime=context["regime"]["primary"], reason=reason,
                              evidence=evidence, timestamp=context["timestamp"], data_quality=context["quality"]["score"], metadata=metadata or {})

    def evaluate(self, context: dict) -> StrategySignal:
        raise NotImplementedError


class RuleStrategy(BaseStrategy):
    def evaluate(self, c: dict) -> StrategySignal:
        f, last, price, atr, regime = c["frame"], c["last"], c["price"], c["atr"], c["regime"]
        structure, fib, fvgs = c["structure"], c["fib"], c["fvgs"]
        score = 0.0; evidence: list[dict] = []; metadata: dict = {}; reason = self.key
        def add(name: str, value: Any, contribution: float, source: str = "calculated OHLCV"):
            nonlocal score
            score += contribution; evidence.append({"name": name, "value": value, "contribution": round(contribution, 2), "source": source, "data_timestamp": c["timestamp"]})
        if self.key == "trend":
            add("EMA20 slope", _round(_slope(f["ema20"])), 28 * np.sign(_slope(f["ema20"])))
            add("EMA alignment", "bullish" if last["ema20"] > last["ema50"] else "bearish", 25 if last["ema20"] > last["ema50"] else -25)
            add("ADX", _round(last["adx"]), (18 if last["adx"] >= 20 else 5) * np.sign(price - last["ema50"])); reason = "趋势、均线斜率与 ADX 联合判断"
        elif self.key == "breakout":
            upper, lower = last["donchian_upper_20"], last["donchian_lower_20"]; margin = (price - upper) / atr if pd.notna(upper) else 0
            direction = 1 if pd.notna(upper) and price > upper else -1 if pd.notna(lower) and price < lower else 0
            add("Donchian close confirmation", _round(margin), 35 * direction); add("volume ratio", _round(last["volume_ratio"]), 22 * direction if last["volume_ratio"] >= 1.2 else -12 * direction)
            add("ATR-normalized break", _round(abs(margin)), 18 * direction if abs(margin) >= .1 else -8 * direction)
            false_probability = float(np.clip(.65 - .22 * _finite(last["volume_ratio"], 1) - .18 * min(abs(margin), 1), .05, .9)) if direction else .5
            metadata = {"breakout_strength": round(abs(score), 2), "false_breakout_probability": round(false_probability, 4), "retest_probability": round(float(np.clip(.35 + .2 * (abs(margin) < .8), .1, .8)), 4)}; reason = "收盘突破、成交量、ATR 幅度与假突破风险联合确认"
        elif self.key == "pullback":
            trend = 1 if last["ema20"] > last["ema50"] else -1; distance = (price - last["ema20"]) / atr
            near = abs(distance) <= .65; momentum = np.sign(last["macd_hist"] - f["macd_hist"].iloc[-2])
            add("primary trend", trend, 30 * trend); add("EMA20 retest distance ATR", _round(distance), 24 * trend if near else -10 * trend); add("momentum resumes", int(momentum), 18 * momentum)
            if fib.get("status") == "AVAILABLE":
                nearest = min((abs(price - value) / atr, ratio) for ratio, value in fib["levels"].items() if ratio in {"0.382", "0.5", "0.618", "0.786"})
                add("Fibonacci pullback proximity", nearest[1], 18 * trend if nearest[0] <= .5 else 0); metadata["nearest_fib"] = nearest[1]
            reason = "主趋势中的均线/Fibonacci 回撤与动量恢复"
        elif self.key == "reversal":
            rsi_div = _divergence(f["close"], f["rsi"]); macd_div = _divergence(f["close"], f["macd"])
            choch = structure.get("latest_choch"); direction = 1 if rsi_div == "BULLISH" else -1 if rsi_div == "BEARISH" else 0
            add("RSI divergence", rsi_div, 20 * direction); add("MACD divergence", macd_div, 18 if macd_div == "BULLISH" else -18 if macd_div == "BEARISH" else 0)
            add("CHoCH confirmation", choch["direction"] if choch else "NONE", 34 if choch and choch["direction"] == "BULLISH" else -34 if choch else 0)
            if regime["primary"] != "RANGE": score *= .7
            reason = "反转必须由背离与 CHoCH 多因素确认，强趋势下降权"
        elif self.key == "range":
            high, low = f["high"].shift(1).tail(40).max(), f["low"].shift(1).tail(40).min(); position = (price - low) / max(high - low, 1e-12)
            direction = 1 if position < .2 else -1 if position > .8 else 0
            add("range position", _round(position, 4), 38 * direction); add("ADX range filter", _round(last["adx"]), 22 * direction if last["adx"] < 20 else -20 * direction)
            metadata = {"range_width": _round((high - low) / price, 4), "range_position": _round(position, 4), "distance_to_support": _round((price - low) / price, 4), "distance_to_resistance": _round((high - price) / price, 4), "mean_reversion_probability": _round(.5 + .25 * abs(position - .5) * 2, 4)}; reason = "区间位置与 ADX 过滤后的均值回归"
        elif self.key == "moving_average":
            alignment = int(last["ema20"] > last["ema50"] > last["ema100"] > last["ema200"]) - int(last["ema20"] < last["ema50"] < last["ema100"] < last["ema200"])
            cross = 1 if _crossed_up(f["ema20"], f["ema50"]) else -1 if _crossed_down(f["ema20"], f["ema50"]) else 0
            add("EMA20/50 cross", cross, 28 * cross); add("EMA20/50/100/200 alignment", alignment, 32 * alignment); add("EMA20 slope", _round(_slope(f["ema20"])), 18 * np.sign(_slope(f["ema20"])))
            reason = "交叉、四均线排列、斜率和价格距离联合判断"
        elif self.key == "bollinger":
            width_rank = float((f["boll_width"].dropna() <= last["boll_width"]).mean()); percent_b = _finite(last["boll_percent_b"], .5)
            direction = 1 if percent_b > 1 and last["volume_ratio"] >= 1.15 else -1 if percent_b < 0 and last["volume_ratio"] >= 1.15 else 1 if percent_b < .05 and regime["primary"] == "RANGE" else -1 if percent_b > .95 and regime["primary"] == "RANGE" else 0
            add("Bollinger %B", _round(percent_b), 32 * direction); add("bandwidth percentile", _round(width_rank), 18 * direction if width_rank > .35 else 8 * direction); add("volume confirmation", _round(last["volume_ratio"]), 16 * direction if last["volume_ratio"] >= 1.15 else -8 * direction)
            metadata = {"squeeze": width_rank <= .2, "bandwidth": _round(last["boll_width"]), "percent_b": _round(percent_b)}; reason = "布林位置、带宽状态、趋势与成交量联合判断"
        elif self.key in {"rsi_breakout", "rsi_reversal"}:
            if self.key == "rsi_breakout":
                direction = 1 if _crossed_up(f["rsi"], 50) else -1 if _crossed_down(f["rsi"], 50) else 0
                add("RSI 50 cross", _round(last["rsi"]), 36 * direction); add("trend context", regime["primary"], 25 if direction > 0 and regime["primary"] == "TREND_UP" else -25 if direction < 0 and regime["primary"] == "TREND_DOWN" else -8 * direction); reason = "RSI 结构突破必须与趋势环境一致"
            else:
                divergence = _divergence(f["close"], f["rsi"]); direction = 1 if divergence == "BULLISH" else -1 if divergence == "BEARISH" else 0
                add("RSI divergence", divergence, 38 * direction); add("extreme reversal", _round(last["rsi"]), 18 if last["rsi"] < 35 else -18 if last["rsi"] > 65 else 0); add("range regime", regime["primary"], 16 * direction if regime["primary"] == "RANGE" else -10 * direction); reason = "RSI 背离、极值与市场状态共同确认"
        elif self.key == "macd":
            cross = 1 if _crossed_up(f["macd"], f["macd_signal"]) else -1 if _crossed_down(f["macd"], f["macd_signal"]) else 0
            zero = 1 if _crossed_up(f["macd"], 0) else -1 if _crossed_down(f["macd"], 0) else 0; expansion = np.sign(last["macd_hist"] - f["macd_hist"].iloc[-2])
            add("DIF/DEA cross", cross, 32 * cross); add("zero-line cross", zero, 25 * zero); add("histogram expansion", int(expansion), 15 * expansion); reason = "MACD 交叉、零轴和柱体变化"
        elif self.key == "fibonacci":
            if fib.get("status") != "AVAILABLE": return self.unavailable(c, "INSUFFICIENT_EVIDENCE", "没有两个已确认且方向相反的因果 Swing")
            direction = 1 if fib["direction"] == "UP" else -1; distances = {ratio: abs(price - value) / atr for ratio, value in fib["levels"].items() if ratio in {"0.382", "0.5", "0.618", "0.786"}}
            nearest = min(distances, key=distances.get); add("retracement level", nearest, 42 * direction if distances[nearest] <= .5 else 5 * direction); add("structure alignment", structure["trend"], 25 * direction if structure["trend"] == fib["direction"] else -12 * direction)
            metadata = fib; reason = "已确认 Swing 建立的 Fibonacci 回撤/扩展结构"
        elif self.key == "gann":
            return self.unavailable(c, "INSUFFICIENT_EVIDENCE", "Gann 时间/价格尺度尚无独立样本外增量证据，不参与交易评分")
        elif self.key == "stochastic":
            cross = 1 if _crossed_up(f["stoch_k"], f["stoch_d"]) and last["stoch_k"] < 35 else -1 if _crossed_down(f["stoch_k"], f["stoch_d"]) and last["stoch_k"] > 65 else 0
            add("%K/%D confirmed cross", _round(last["stoch_k"]), 38 * cross); add("regime filter", regime["primary"], 20 * cross if regime["primary"] == "RANGE" else -10 * cross); reason = "随机指标交叉与超买超卖、状态过滤"
        elif self.key == "psar":
            flip = int(f["psar_trend"].iloc[-1] != f["psar_trend"].iloc[-2]); direction = int(last["psar_trend"])
            add("PSAR direction/flip", {"direction": direction, "flip": bool(flip)}, (38 if flip else 18) * direction); add("ADX filter", _round(last["adx"]), 20 * direction if last["adx"] >= 20 else -15 * direction); reason = "PSAR 翻转由 ATR/ADX 状态过滤"
        elif self.key == "momentum":
            direction = np.sign(last["roc"]); add("ROC", _round(last["roc"]), 30 * direction); add("acceleration", _round(last["acceleration"]), 22 * np.sign(last["acceleration"])); add("momentum divergence", _divergence(f["close"], f["roc"]), 15 if _divergence(f["close"], f["roc"]) == "BULLISH" else -15 if _divergence(f["close"], f["roc"]) == "BEARISH" else 0); reason = "ROC、价格加速度与动量背离"
        elif self.key == "mfi":
            divergence = _divergence(f["close"], f["mfi"]); direction = 1 if divergence == "BULLISH" else -1 if divergence == "BEARISH" else 1 if last["mfi"] < 25 else -1 if last["mfi"] > 75 else 0
            add("MFI", _round(last["mfi"]), 28 * direction); add("MFI divergence", divergence, 28 if divergence == "BULLISH" else -28 if divergence == "BEARISH" else 0); add("OBV confirmation", _round(_slope(f["obv"])), 15 * np.sign(_slope(f["obv"]))); reason = "真实 OHLCV 的 MFI、OBV 与价格关系"
        elif self.key in {"double_top_bottom", "head_shoulders", "triangle", "wedge", "flag"}:
            pattern = _pattern_signal(self.key, c); score = pattern["score"]; evidence.extend(pattern["evidence"]); metadata = pattern["metadata"]; reason = pattern["reason"]
        elif self.key == "donchian":
            signals = []
            for period in (20, 55, 100):
                direction = 1 if price > last[f"donchian_upper_{period}"] else -1 if price < last[f"donchian_lower_{period}"] else 0
                signals.append(direction); add(f"Donchian {period}", direction, {20: 24, 55: 22, 100: 18}[period] * direction)
            reason = "20/55/100 周期、排除当前 K 线的 Donchian 突破"
        elif self.key == "order_flow":
            flow = c.get("order_flow") or {}
            if not {"bid_volume", "ask_volume"}.issubset(flow): return self.unavailable(c, "ORDER_FLOW_DATA_UNAVAILABLE", "数据源没有逐笔主动买卖或订单簿字段，普通成交量不冒充 Order Flow")
            bid = _finite(flow.get("bid_volume")); ask = _finite(flow.get("ask_volume")); delta = ask - bid; total = ask + bid
            add("reported aggressor delta", _round(delta), 60 * np.sign(delta) * min(abs(delta) / max(total, 1), 1), "exchange order-flow feed"); metadata = {"bid_volume": bid, "ask_volume": ask, "delta": delta}; reason = "交易所报告的真实主动成交差"
        elif self.key == "atr":
            rank = float((f["atr_percent"].dropna() <= last["atr_percent"]).mean()); direction = np.sign(last["close"] - last["open"])
            add("ATR percentile", _round(rank), 25 * direction if rank >= .55 else 5 * direction); add("range expansion", _round(last["tr"] / max(last["atr"], 1e-12)), 25 * direction if last["tr"] > last["atr"] else 0); reason = "ATR 仅作为波动和风险过滤，不单独预测方向"
        elif self.key == "options":
            chain = c.get("options_chain")
            if not chain: return self.unavailable(c, "OPTIONS_DATA_UNAVAILABLE", "没有真实 Strike/Expiry/Bid/Ask/IV/Greeks 期权链，不参与评分")
            return self.unavailable(c, "OPTIONS_DATA_UNAVAILABLE", "当前行情适配器尚未提供可验证完整期权链")
        elif self.key in {"ict_smc", "bos", "choch", "fvg", "fib_fvg_bos"}:
            score, evidence, metadata, reason = _structure_strategy(self.key, c)
        else:
            return self.unavailable(c, "NOT_IMPLEMENTED", "策略未实现")
        allow_trade = self.key not in {"wedge", "atr"} or bool(metadata.get("confirmed"))
        return self.result(c, score, reason, evidence, metadata, allow_trade)


def _divergence(price: pd.Series, indicator: pd.Series, lookback: int = 30) -> str:
    p, i = price.tail(lookback), indicator.tail(lookback)
    half = max(3, len(p) // 2)
    if len(p) < 12: return "NONE"
    if p.iloc[-half:].min() < p.iloc[:-half].min() and i.iloc[-half:].min() > i.iloc[:-half].min(): return "BULLISH"
    if p.iloc[-half:].max() > p.iloc[:-half].max() and i.iloc[-half:].max() < i.iloc[:-half].max(): return "BEARISH"
    return "NONE"


def _pattern_signal(key: str, c: dict) -> dict:
    swings = sorted(c["swings"], key=lambda x: x["pivot_index"]); highs = [x for x in swings if x["kind"] == "HIGH"]; lows = [x for x in swings if x["kind"] == "LOW"]
    price, atr, volume = c["price"], c["atr"], _finite(c["last"]["volume_ratio"], 1); evidence = []; score = 0.; metadata: dict = {"confirmed": False}
    def ev(name, value, contribution): evidence.append({"name": name, "value": value, "contribution": contribution, "source": "causal confirmed swings", "data_timestamp": c["timestamp"]})
    if key == "double_top_bottom" and len(highs) >= 2 and len(lows) >= 2:
        h1, h2 = highs[-2:]; l1, l2 = lows[-2:]; top_similarity = abs(h1["price"] - h2["price"]) / atr; bottom_similarity = abs(l1["price"] - l2["price"]) / atr
        if top_similarity <= .8:
            neckline = min(x["price"] for x in lows if h1["pivot_index"] < x["pivot_index"] < h2["pivot_index"]) if any(h1["pivot_index"] < x["pivot_index"] < h2["pivot_index"] for x in lows) else None
            confirmed = neckline is not None and price < neckline; score = -65 if confirmed else 0; metadata.update({"pattern": "DOUBLE_TOP", "peak_1": h1, "peak_2": h2, "neckline": neckline, "confirmed": confirmed}); ev("double top similarity ATR", _round(top_similarity), score)
        elif bottom_similarity <= .8:
            neckline = max(x["price"] for x in highs if l1["pivot_index"] < x["pivot_index"] < l2["pivot_index"]) if any(l1["pivot_index"] < x["pivot_index"] < l2["pivot_index"] for x in highs) else None
            confirmed = neckline is not None and price > neckline; score = 65 if confirmed else 0; metadata.update({"pattern": "DOUBLE_BOTTOM", "low_1": l1, "low_2": l2, "neckline": neckline, "confirmed": confirmed}); ev("double bottom similarity ATR", _round(bottom_similarity), score)
    elif key == "head_shoulders" and len(highs) >= 3 and len(lows) >= 2:
        a, b, d = highs[-3:]; symmetry = abs(a["price"] - d["price"]) / atr; neckline = min(x["price"] for x in lows[-3:]); confirmed = b["price"] > max(a["price"], d["price"]) + .3 * atr and symmetry <= 1.2 and price < neckline
        score = -70 if confirmed else 0; metadata.update({"pattern": "HEAD_SHOULDERS", "left_shoulder": a, "head": b, "right_shoulder": d, "neckline": neckline, "shoulder_symmetry_atr": _round(symmetry), "confirmed": confirmed}); ev("neckline close confirmation", confirmed, score)
    elif key in {"triangle", "wedge"} and len(highs) >= 3 and len(lows) >= 3:
        hi_slope = np.polyfit([x["pivot_index"] for x in highs[-3:]], [x["price"] for x in highs[-3:]], 1)[0]; lo_slope = np.polyfit([x["pivot_index"] for x in lows[-3:]], [x["price"] for x in lows[-3:]], 1)[0]
        upper, lower = highs[-1]["price"], lows[-1]["price"]
        if key == "triangle": pattern = "ASCENDING_TRIANGLE" if abs(hi_slope) < abs(lo_slope) * .3 and lo_slope > 0 else "DESCENDING_TRIANGLE" if abs(lo_slope) < abs(hi_slope) * .3 and hi_slope < 0 else "SYMMETRICAL_TRIANGLE" if hi_slope < 0 < lo_slope else "NONE"
        else: pattern = "RISING_WEDGE" if hi_slope > 0 and lo_slope > hi_slope else "FALLING_WEDGE" if hi_slope < 0 and lo_slope < 0 and hi_slope < lo_slope else "NONE"
        direction = 1 if price > upper else -1 if price < lower else 0; confirmed = pattern != "NONE" and direction != 0 and volume >= 1.1
        score = 62 * direction if confirmed else 0; metadata.update({"pattern": pattern, "high_slope": _round(hi_slope), "low_slope": _round(lo_slope), "confirmed": confirmed}); ev("pattern breakout with volume", pattern, score)
    elif key == "flag" and len(c) and len(c["frame"]) >= 30:
        f = c["frame"]; pole = float(f["close"].iloc[-12] / f["close"].iloc[-25] - 1); consolidation = float(f["high"].tail(12).max() / f["low"].tail(12).min() - 1); direction = 1 if pole > 3 * consolidation else -1 if pole < -3 * consolidation else 0
        boundary = f["high"].iloc[-12:-1].max() if direction > 0 else f["low"].iloc[-12:-1].min(); confirmed = (price > boundary if direction > 0 else price < boundary) and volume >= 1.15 if direction else False
        score = 65 * direction if confirmed else 0; metadata.update({"pattern": "BULL_FLAG" if direction > 0 else "BEAR_FLAG" if direction < 0 else "NONE", "pole_return": _round(pole), "consolidation_width": _round(consolidation), "confirmed": bool(confirmed)}); ev("flag breakout", bool(confirmed), score)
    return {"score": score, "evidence": evidence, "metadata": metadata, "reason": "形态只在因果 Swing、收盘突破与成交量确认后产生交易信号"}


def _structure_strategy(key: str, c: dict):
    structure, fib, fvgs, price, atr = c["structure"], c["fib"], c["fvgs"], c["price"], c["atr"]
    bos, choch = structure.get("latest_bos"), structure.get("latest_choch"); open_fvgs = [x for x in fvgs if x["status"] != "FILLED"]
    evidence = []; components = {"structure": 0., "bos": 0., "choch": 0., "fibonacci": 0., "fvg": 0., "volume": 0., "momentum": 0., "regime": 0., "risk_reward": 0.}
    direction = 1 if structure["trend"] == "UP" else -1 if structure["trend"] == "DOWN" else 0; components["structure"] = 12 * direction
    if bos: components["bos"] = 18 if bos["direction"] == "BULLISH" else -18
    if choch and (not bos or choch["break_index"] > bos["break_index"]): components["choch"] = 10 if choch["direction"] == "BULLISH" else -10
    confluence_zone = None
    if fib.get("status") == "AVAILABLE":
        fib_direction = 1 if fib["direction"] == "UP" else -1
        distances = [(abs(price - value) / atr, ratio, value) for ratio, value in fib["levels"].items() if ratio in {"0.382", "0.5", "0.618", "0.786"}]
        nearest = min(distances); components["fibonacci"] = 14 * fib_direction if nearest[0] <= .65 else 0
        for gap in reversed(open_fvgs[-12:]):
            overlap = max(0, min(gap["top"], nearest[2] + .35 * atr) - max(gap["bottom"], nearest[2] - .35 * atr))
            if overlap > 0 and gap["direction"] == ("BULLISH" if fib_direction > 0 else "BEARISH"):
                components["fvg"] = 16 * fib_direction; confluence_zone = {"fib_ratio": nearest[1], "fib_price": nearest[2], "fvg": gap}; break
    momentum = np.sign(c["last"]["macd_hist"] - c["frame"]["macd_hist"].iloc[-2]); components["momentum"] = 7 * momentum
    if bos: components["volume"] = (7 if bos["volume_ratio"] >= 1.2 else 2) * (1 if bos["direction"] == "BULLISH" else -1)
    components["regime"] = 6 * direction if c["regime"]["primary"] != "RANGE" else 0
    selected = components.copy()
    if key == "bos": selected = {"bos": components["bos"], "volume": components["volume"]}
    elif key == "choch": selected = {"choch": components["choch"], "momentum": components["momentum"]}
    elif key == "fvg":
        latest = open_fvgs[-1] if open_fvgs else None; selected = {"fvg": 42 if latest and latest["direction"] == "BULLISH" and latest["bottom"] <= price <= latest["top"] else -42 if latest and latest["direction"] == "BEARISH" and latest["bottom"] <= price <= latest["top"] else 0}
    elif key == "ict_smc": selected = {name: components[name] for name in ("structure", "bos", "choch", "fvg", "volume")}
    score = sum(selected.values())
    for name, value in selected.items(): evidence.append({"name": name, "value": value, "contribution": value, "source": "causal ICT/SMC structure", "data_timestamp": c["timestamp"]})
    status = "HIGH_CONFLUENCE" if abs(score) >= 85 else "VALID_SETUP" if abs(score) >= 75 else "WATCH" if abs(score) >= 60 else "WEAK" if abs(score) >= 40 else "NO_TRADE"
    return score, evidence, {"score_components": components, "setup_status": status, "confluence_zone": confluence_zone, "bos": bos, "choch": choch, "open_fvgs": open_fvgs[-8:], "confirmed": bool(bos)}, "因果 Swing → BOS/CHoCH → Fibonacci → FVG 重合 → 成交量/动量确认"


# Named classes keep the public strategy API explicit and discoverable.
def _strategy_class(name: str, key: str, family: str):
    return type(name, (RuleStrategy,), {"key": key, "family": family})


TrendStrategy = _strategy_class("TrendStrategy", "trend", "trend")
BreakoutStrategy = _strategy_class("BreakoutStrategy", "breakout", "breakout")
PullbackStrategy = _strategy_class("PullbackStrategy", "pullback", "trend")
ReversalStrategy = _strategy_class("ReversalStrategy", "reversal", "reversal")
RangeStrategy = _strategy_class("RangeStrategy", "range", "range")
MovingAverageStrategy = _strategy_class("MovingAverageStrategy", "moving_average", "trend")
BollingerStrategy = _strategy_class("BollingerStrategy", "bollinger", "volatility")
RSIBreakoutStrategy = _strategy_class("RSIBreakoutStrategy", "rsi_breakout", "momentum")
RSIReversalStrategy = _strategy_class("RSIReversalStrategy", "rsi_reversal", "reversal")
MACDStrategy = _strategy_class("MACDStrategy", "macd", "momentum")
FibonacciStrategy = _strategy_class("FibonacciStrategy", "fibonacci", "structure")
GannStrategy = _strategy_class("GannStrategy", "gann", "geometry")
StochasticStrategy = _strategy_class("StochasticStrategy", "stochastic", "momentum")
PSARStrategy = _strategy_class("PSARStrategy", "psar", "trend")
MomentumStrategy = _strategy_class("MomentumStrategy", "momentum", "momentum")
MFIStrategy = _strategy_class("MFIStrategy", "mfi", "flow_proxy")
DoubleTopBottomStrategy = _strategy_class("DoubleTopBottomStrategy", "double_top_bottom", "pattern")
HeadShouldersStrategy = _strategy_class("HeadShouldersStrategy", "head_shoulders", "pattern")
TriangleStrategy = _strategy_class("TriangleStrategy", "triangle", "pattern")
DonchianStrategy = _strategy_class("DonchianStrategy", "donchian", "breakout")
WedgeStrategy = _strategy_class("WedgeStrategy", "wedge", "pattern")
FlagStrategy = _strategy_class("FlagStrategy", "flag", "pattern")
OrderFlowStrategy = _strategy_class("OrderFlowStrategy", "order_flow", "order_flow")
ATRStrategy = _strategy_class("ATRStrategy", "atr", "volatility")
OptionsStrategy = _strategy_class("OptionsStrategy", "options", "options")
ICTSMCStrategy = _strategy_class("ICTSMCStrategy", "ict_smc", "structure")
FVGStrategy = _strategy_class("FVGStrategy", "fvg", "structure")
BOSStrategy = _strategy_class("BOSStrategy", "bos", "structure")
CHoCHStrategy = _strategy_class("CHoCHStrategy", "choch", "structure")
FibFvgBosStrategy = _strategy_class("FibFvgBosStrategy", "fib_fvg_bos", "structure")


STRATEGY_CLASSES = [TrendStrategy, BreakoutStrategy, PullbackStrategy, ReversalStrategy, RangeStrategy,
    MovingAverageStrategy, BollingerStrategy, RSIBreakoutStrategy, RSIReversalStrategy, MACDStrategy,
    FibonacciStrategy, GannStrategy, StochasticStrategy, PSARStrategy, MomentumStrategy, MFIStrategy,
    DoubleTopBottomStrategy, HeadShouldersStrategy, TriangleStrategy, DonchianStrategy, WedgeStrategy,
    FlagStrategy, OrderFlowStrategy, ATRStrategy, OptionsStrategy, ICTSMCStrategy, FVGStrategy,
    BOSStrategy, CHoCHStrategy, FibFvgBosStrategy]


class StrategyConfluenceEngine:
    """Aggregate by information family first so correlated indicators do not get multiple votes."""
    def aggregate(self, signals: list[dict]) -> dict:
        available = [item for item in signals if item["status"] == "AVAILABLE"]
        by_family: dict[str, list[float]] = {}
        family_by_key = {cls.key: cls.family for cls in STRATEGY_CLASSES}
        for item in available:
            signed = item["strength"] * (1 if item["signal"] == "BUY" else -1 if item["signal"] == "SELL" else 0)
            by_family.setdefault(family_by_key[item["strategy"]], []).append(signed)
        family_scores = {name: float(np.mean(values)) for name, values in by_family.items()}
        score = float(np.mean(list(family_scores.values()))) if family_scores else 0.0
        return {"score": round(abs(score), 2), "direction": "UP" if score >= 15 else "DOWN" if score <= -15 else "RANGE",
                "signal": "BUY" if score >= 24 else "SELL" if score <= -24 else "HOLD",
                "family_scores": {k: round(v, 2) for k, v in family_scores.items()},
                "redundancy_control": "mean within information family, then equal-weight family mean",
                "available_strategies": len(available), "unavailable_strategies": len(signals) - len(available)}


class StrategyEngine:
    def __init__(self, swing_left: int = 3, swing_right: int = 3):
        self.swing_detector = CausalSwingDetector(swing_left, swing_right)
        self.strategies = {cls.key: cls() for cls in STRATEGY_CLASSES}

    def analyze(self, candles: list[dict], timeframe: str, source: str = "real OHLCV", strategy_keys: list[str] | None = None,
                order_flow: dict | None = None, options_chain: list[dict] | None = None, parameters: dict | None = None) -> dict:
        frame = extended_indicators(candles)
        if len(frame) < 60: raise ValueError("技术策略至少需要 60 根真实 K 线")
        swings = self.swing_detector.detect(frame); structure = detect_structure(frame, swings); fvgs = detect_fvgs(frame)
        fib = fibonacci_structure(frame, swings, structure["trend"]); quality = data_quality(frame, source); regime = market_regime(frame)
        last = frame.iloc[-1]; context = {"frame": frame, "last": last, "price": float(last["close"]),
            "atr": max(_finite(last["atr"]), float(last["close"]) * .001), "timeframe": timeframe,
            "timestamp": frame["timestamp_utc"].iloc[-1].isoformat(), "quality": quality, "regime": regime,
            "swings": swings, "structure": structure, "fvgs": fvgs, "fib": fib,
            "order_flow": order_flow, "options_chain": options_chain, "parameters": parameters or {}}
        keys = strategy_keys or list(self.strategies)
        signals = [self.strategies[key].evaluate(context).payload() for key in keys if key in self.strategies]
        confluence = StrategyConfluenceEngine().aggregate(signals)
        risk = self._risk_plan(context, confluence)
        for item in signals:
            if item["status"] == "AVAILABLE":
                item.update({"stop_loss": risk["stop_loss"], "take_profit": risk["take_profits"][0]["price"],
                             "risk_reward": risk["take_profits"][0]["risk_reward"], "expected_value": risk["expected_value"]})
        bullish = [e for s in signals for e in s["evidence"] if e["contribution"] > 0]
        bearish = [e for s in signals for e in s["evidence"] if e["contribution"] < 0]
        neutral = [{"name": s["strategy"], "value": s["status"]} for s in signals if s["status"] != "AVAILABLE" or s["signal"] == "HOLD"]
        return {"engine_version": "5.0", "strategy_count": len(self.strategies), "signals": signals, "confluence": confluence,
                "market_regime": regime, "data_quality": quality, "structure": structure, "fibonacci": fib, "fvgs": fvgs[-20:],
                "risk_plan": risk, "strategy_correlation": strategy_correlation_matrix(frame),
                "evidence_chain": {"bullish": bullish[:20], "bearish": bearish[:20], "neutral": neutral[:20]},
                "unavailable": {s["strategy"]: s["status"] for s in signals if s["status"] != "AVAILABLE"},
                "causality": {"swing_confirmation": f"right_bars={self.swing_detector.right}", "formation_and_available_time_separate": True,
                              "historical_execution": "signal close T, execute open T+1"}}

    def analyze_multi_timeframe(self, candles_by_timeframe: dict[str, list[dict]], sources: dict[str, str] | None = None) -> dict:
        matrix = {}; sources = sources or {}
        for timeframe, rows in candles_by_timeframe.items():
            try:
                result = self.analyze(rows, timeframe, sources.get(timeframe, "real OHLCV"),
                                      ["trend", "breakout", "fibonacci", "bos", "fvg", "fib_fvg_bos"])
                matrix[timeframe] = {"status": "AVAILABLE", "direction": result["confluence"]["direction"],
                                     "score": result["confluence"]["score"], "regime": result["market_regime"],
                                     "data_timestamp": result["data_quality"]["data_timestamp"], "source": sources.get(timeframe)}
            except (ValueError, KeyError) as exc:
                matrix[timeframe] = {"status": "INSUFFICIENT_HISTORICAL_DATA", "reason": str(exc)}
        available = [item["direction"] for item in matrix.values() if item["status"] == "AVAILABLE"]
        directional = [item for item in available if item != "RANGE"]
        alignment = max(directional.count("UP"), directional.count("DOWN")) / len(directional) if directional else 0.0
        conflict = "UP" in directional and "DOWN" in directional
        return {"matrix": matrix, "alignment": round(alignment, 4), "conflict": conflict,
                "confidence_factor": .65 if conflict else .85 if alignment < .6 else 1.0,
                "hierarchy": {"higher": ["1d", "4h"], "middle": ["1h"], "entry": ["15m", "5m"]}}

    def _risk_plan(self, c: dict, confluence: dict) -> dict:
        price, atr, direction = c["price"], c["atr"], confluence["direction"]
        side = 1 if direction == "UP" else -1 if direction == "DOWN" else 0
        relevant_swings = c["structure"]["swing_lows"] if side > 0 else c["structure"]["swing_highs"]
        structure_level = relevant_swings[-1]["price"] if relevant_swings else price - side * 1.5 * atr
        gaps = [g for g in c["fvgs"] if g["direction"] == ("BULLISH" if side > 0 else "BEARISH")]
        fvg_level = (gaps[-1]["bottom"] if side > 0 else gaps[-1]["top"]) if gaps else structure_level
        if side == 0: stop = price - 1.5 * atr; side = 1
        else: stop = min(structure_level, fvg_level) - .2 * atr if side > 0 else max(structure_level, fvg_level) + .2 * atr
        risk = max(abs(price - stop), .5 * atr); targets = []
        fib_levels = c["fib"].get("levels", {})
        candidates = ([fib_levels.get("1.272"), fib_levels.get("1.618")] if side > 0 else [fib_levels.get("1.272"), fib_levels.get("1.618")])
        for index, rr in enumerate((1.0, 2.0, 3.0), 1):
            target = price + side * risk * rr
            if index > 1 and candidates[index - 2] is not None and (candidates[index - 2] - price) * side > .5 * risk: target = float(candidates[index - 2])
            targets.append({"name": f"TP{index}", "price": _round(target), "risk_reward": _round(abs(target - price) / risk, 3)})
        histories = []
        horizon = 8
        f = c["frame"]
        for index in range(60, len(f) - horizon):
            entry = float(f["close"].iloc[index]); unit = max(_finite(f["atr"].iloc[index]), entry * .001); future = f.iloc[index + 1:index + horizon + 1]
            favorable = (float(future["high"].max()) - entry) / unit if side > 0 else (entry - float(future["low"].min())) / unit
            adverse = (entry - float(future["low"].min())) / unit if side > 0 else (float(future["high"].max()) - entry) / unit
            histories.append((favorable, adverse))
        observations = np.asarray(histories); probabilities = []
        for target in targets:
            target_r = target["risk_reward"]; probability = float((observations[:, 0] >= target_r).mean()) if len(observations) else None
            target["probability"] = _round(probability, 4); probabilities.append(probability or 0)
        p_stop = float((observations[:, 1] >= risk / atr).mean()) if len(observations) else 0.5
        fee_slippage_r = .0015 * price / risk; ev = sum(probabilities[i] * targets[i]["risk_reward"] * weight for i, weight in enumerate((.5, .3, .2))) - p_stop - fee_slippage_r
        return {"entry": _round(price), "stop_loss": _round(stop), "stop_sources": {"structure": structure_level, "fvg": fvg_level, "atr_buffer": _round(.2 * atr)},
                "take_profits": targets, "stop_probability": _round(p_stop, 4), "expected_value": _round(ev, 4),
                "expected_value_method": "empirical forward MFE/MAE probabilities minus fees/slippage", "historical_samples": len(histories),
                "invalidation_conditions": [f"close crosses structural invalidation {_round(stop)}", "latest BOS/FVG invalidated", "confluence direction changes"]}


def strategy_correlation_matrix(frame: pd.DataFrame) -> dict:
    atr = frame["atr"].replace(0, np.nan); close = frame["close"].replace(0, np.nan)
    values = pd.DataFrame({
        "RSI": (frame["rsi"] - 50) / 50,
        "MACD": frame["macd_hist"] / atr,
        "Momentum": frame["roc"],
        "MA": (frame["ema20"] - frame["ema50"]) / close,
        "Bollinger": frame["boll_percent_b"] - .5,
        "Breakout": np.where(frame["close"] > frame["donchian_upper_20"], 1, np.where(frame["close"] < frame["donchian_lower_20"], -1, 0)),
        "BOS": np.where(frame["close"] > frame["high"].shift(1).rolling(40).max(), 1,
                        np.where(frame["close"] < frame["low"].shift(1).rolling(40).min(), -1, 0)),
        "FVG": np.where(frame["high"].shift(2) < frame["low"], 1,
                        np.where(frame["low"].shift(2) > frame["high"], -1, 0)),
    }).replace([np.inf, -np.inf], np.nan).dropna()
    if len(values) < 30: return {"status": "INSUFFICIENT_HISTORICAL_DATA", "samples": len(values), "matrix": {}}
    correlation = values.corr()
    return {"status": "AVAILABLE", "samples": len(values), "matrix": {row:{column:_round(correlation.loc[row,column],4) for column in correlation.columns} for row in correlation.index},
            "order_flow": "ORDER_FLOW_DATA_UNAVAILABLE", "use": "redundancy audit only; confluence voting is grouped by information family"}


def strategy_backtest(candles: list[dict], strategy: str, timeframe: str, fee_rate: float = .001,
                      slippage_rate: float = .0005, horizon_bars: int = 8, minimum_history: int = 80,
                      parameters: dict | None = None) -> dict:
    if strategy not in SIGNAL_KEYS: raise ValueError("未知 V5 策略")
    raw = candle_frame(candles); frame = extended_indicators(raw.to_dict("records")); trades = []; index = minimum_history
    parameters = parameters or {}; engine = StrategyEngine(int(parameters.get("swing_left", 3)), int(parameters.get("swing_right", 3)))
    all_swings = engine.swing_detector.detect(frame); full_structure = detect_structure(frame, all_swings); all_fvgs = detect_fvgs(frame)
    while index < len(frame) - horizon_bars - 1:
        prefix = frame.iloc[:index + 1]; known_swings = [item for item in all_swings if item["available_index"] <= index]
        known_events = [item for item in full_structure["events"] if item["break_index"] <= index]
        latest_bos = next((event for event in reversed(known_events) if event["type"] == "BOS"), None)
        latest_choch = next((event for event in reversed(known_events) if event["type"] == "CHOCH"), None)
        trend = ("UP" if known_events[-1]["direction"] == "BULLISH" else "DOWN") if known_events else "RANGE"
        structure = {"trend": trend, "events": known_events, "latest_bos": latest_bos, "latest_choch": latest_choch,
                     "swing_highs": [s for s in known_swings if s["kind"] == "HIGH"][-8:],
                     "swing_lows": [s for s in known_swings if s["kind"] == "LOW"][-8:]}
        fvgs = _fvgs_as_of(frame, all_fvgs, index); fib = fibonacci_structure(prefix, known_swings, trend)
        quality = data_quality(prefix, "historical OHLCV"); regime = market_regime(prefix); last = prefix.iloc[-1]
        context = {"frame": prefix, "last": last, "price": float(last["close"]), "atr": max(_finite(last["atr"]), float(last["close"]) * .001),
                   "timeframe": timeframe, "timestamp": frame["timestamp_utc"].iloc[index].isoformat(), "quality": quality,
                   "regime": regime, "swings": known_swings, "structure": structure, "fvgs": fvgs, "fib": fib,
                   "order_flow": None, "options_chain": None, "parameters": parameters}
        signal = engine.strategies[strategy].evaluate(context).payload()
        if signal["status"] != "AVAILABLE" or signal["signal"] == "HOLD": index += 1; continue
        side = 1 if signal["signal"] == "BUY" else -1; execution = index + 1; entry = float(frame["open"].iloc[execution]) * (1 + side * slippage_rate)
        atr = context["atr"]; relevant = structure["swing_lows"] if side > 0 else structure["swing_highs"]
        structural = float(relevant[-1]["price"]) if relevant else entry - side * 1.5 * atr
        stop = min(structural - .2 * atr, entry - .75 * atr) if side > 0 else max(structural + .2 * atr, entry + .75 * atr)
        risk = abs(entry - stop); target = entry + side * risk * 1.75; path = frame.iloc[execution:execution + horizon_bars]
        exit_price = float(path["close"].iloc[-1]); outcome = "TIME"
        for _, row in path.iterrows():
            stop_hit = float(row["low"]) <= stop if side > 0 else float(row["high"]) >= stop
            target_hit = float(row["high"]) >= target if side > 0 else float(row["low"]) <= target
            if stop_hit: exit_price, outcome = stop, "SL"; break  # conservative if both touched in one bar
            if target_hit: exit_price, outcome = target, "TP"; break
        gross = side * (exit_price / entry - 1); net = gross - 2 * fee_rate - slippage_rate
        favorable = (float(path["high"].max()) / entry - 1) if side > 0 else (1 - float(path["low"].min()) / entry)
        adverse = (float(path["low"].min()) / entry - 1) if side > 0 else (1 - float(path["high"].max()) / entry)
        trades.append({"signal_index": index, "signal_time": frame["timestamp"].iloc[index], "execution_index": execution,
                       "execution_time": frame["timestamp"].iloc[execution], "side": signal["signal"], "entry": entry,
                       "exit": exit_price, "return": net, "outcome": outcome, "mae": adverse, "mfe": favorable})
        index += horizon_bars
    returns = np.asarray([t["return"] for t in trades], dtype=float); wins = returns[returns > 0]; losses = returns[returns <= 0]
    curve = np.cumprod(1 + returns) if len(returns) else np.asarray([]); peaks = np.maximum.accumulate(np.r_[1, curve])[1:] if len(curve) else np.asarray([])
    drawdown = float(np.max(1 - curve / peaks)) if len(curve) else 0.; downside = returns[returns < 0]
    sharpe = float(np.sqrt(len(returns)) * returns.mean() / returns.std(ddof=1)) if len(returns) > 1 and returns.std(ddof=1) else 0.
    sortino = float(np.sqrt(len(returns)) * returns.mean() / downside.std(ddof=1)) if len(downside) > 1 and downside.std(ddof=1) else 0.
    profit_factor = float(wins.sum() / abs(losses.sum())) if len(losses) and losses.sum() else None
    return {"strategy": strategy, "status": "AVAILABLE" if trades else "INSUFFICIENT_HISTORICAL_DATA", "number_of_trades": len(trades),
            "win_rate": _round((returns > 0).mean() if len(returns) else 0, 4), "profit_factor": _round(profit_factor, 4),
            "expectancy": _round(returns.mean() if len(returns) else 0, 6), "average_win": _round(wins.mean() if len(wins) else 0, 6),
            "average_loss": _round(losses.mean() if len(losses) else 0, 6), "max_drawdown": _round(drawdown, 4),
            "sharpe": _round(sharpe, 4), "sortino": _round(sortino, 4), "calmar": _round((returns.mean() / drawdown) if len(returns) and drawdown else None, 4),
            "mae": _round(np.mean([t["mae"] for t in trades]) if trades else None, 6), "mfe": _round(np.mean([t["mfe"] for t in trades]) if trades else None, 6),
            "trades": trades, "validation": "causal expanding-prefix; signal close T; execution open T+1; non-overlapping horizon",
            "mock_count": 0, "random_signal_count": 0}


def _fvgs_as_of(frame: pd.DataFrame, fvgs: list[dict], index: int) -> list[dict]:
    output = []
    for source in fvgs:
        if source["creation_index"] > index: continue
        item = dict(source); size = max(float(item["top"] - item["bottom"]), 1e-12)
        future = frame.iloc[item["creation_index"] + 1:index + 1]
        penetration = ((item["top"] - future["low"]) / size).clip(0, 1) if item["direction"] == "BULLISH" else ((future["high"] - item["bottom"]) / size).clip(0, 1)
        filled = float(penetration.max()) if len(penetration) else 0.0
        item.update({"age": index - item["creation_index"], "filled_percent": round(filled * 100, 2),
                     "status": "FILLED" if filled >= .999 else "PARTIALLY_FILLED" if filled > 0 else "OPEN"})
        output.append(item)
    return output


def optimize_strategy_parameters(candles: list[dict], strategy: str, timeframe: str,
                                 fee_rate: float = .001, slippage_rate: float = .0005) -> dict:
    frame = candle_frame(candles)
    if len(frame) < 360:
        return {"status": "INSUFFICIENT_HISTORICAL_DATA", "required_bars": 360, "available_bars": len(frame)}
    train_end, validation_end = int(len(frame) * .55), int(len(frame) * .75); embargo = 12
    candidates = [{"swing_left": swing, "swing_right": swing, "signal_threshold": threshold}
                  for swing in (2, 3, 4) for threshold in (20, 28, 36)]
    train_rows = frame.iloc[:train_end].to_dict("records"); validation_rows = frame.iloc[:validation_end].to_dict("records")
    screened = []
    for params in candidates:
        train = strategy_backtest(train_rows, strategy, timeframe, fee_rate, slippage_rate, parameters=params)
        if train["number_of_trades"] >= 2:
            screened.append((params, train))
    if not screened:
        return {"status": "INSUFFICIENT_HISTORICAL_DATA", "stage": "TRAIN", "tested": len(candidates)}
    validation = []
    for params, train in screened:
        result = strategy_backtest(validation_rows, strategy, timeframe, fee_rate, slippage_rate,
                                   minimum_history=train_end + embargo, parameters=params)
        score = _finite(result["expectancy"]) + .05 * _finite(result["sharpe"]) - .1 * _finite(result["max_drawdown"])
        validation.append({"parameters": params, "train": {k: train[k] for k in ("number_of_trades", "expectancy", "sharpe", "max_drawdown")},
                           "validation": {k: result[k] for k in ("number_of_trades", "expectancy", "sharpe", "max_drawdown")}, "selection_score": score})
    eligible = [item for item in validation if item["validation"]["number_of_trades"] >= 2]
    if not eligible:
        return {"status": "INSUFFICIENT_HISTORICAL_DATA", "stage": "VALIDATION", "experiments": validation}
    selected = max(eligible, key=lambda item: item["selection_score"]); locked = selected["parameters"]
    out_of_sample = strategy_backtest(frame.to_dict("records"), strategy, timeframe, fee_rate, slippage_rate,
                                      minimum_history=validation_end + embargo, parameters=locked)
    return {"status": "PASS" if out_of_sample["number_of_trades"] >= 3 else "INSUFFICIENT_HISTORICAL_DATA",
            "method": "train candidate screen → validation select → lock → embargo → untouched out-of-sample",
            "train_end": frame["timestamp"].iloc[train_end - 1], "validation_end": frame["timestamp"].iloc[validation_end - 1],
            "embargo_bars": embargo, "locked_parameters": locked, "selected_validation": selected,
            "out_of_sample": out_of_sample, "experiments": validation}


def walk_forward_strategy(candles: list[dict], strategy: str, timeframe: str, folds: int = 4) -> dict:
    frame = candle_frame(candles); minimum = 120
    if len(frame) < minimum + 80: return {"status": "INSUFFICIENT_HISTORICAL_DATA", "folds": []}
    boundaries = np.linspace(minimum, len(frame), folds + 1, dtype=int); results = []
    for fold in range(folds):
        train_end, test_end = boundaries[fold], boundaries[fold + 1]
        # The expanding prefix represents retraining/parameter lock. The test
        # starts after an embargo equal to the trade horizon.
        embargo = 8; sample = frame.iloc[:test_end].to_dict("records")
        result = strategy_backtest(sample, strategy, timeframe, minimum_history=train_end + embargo)
        results.append({"fold": fold + 1, "train_end": frame["timestamp"].iloc[train_end - 1],
                        "test_start": frame["timestamp"].iloc[min(train_end + embargo, test_end - 1)], "test_end": frame["timestamp"].iloc[test_end - 1],
                        "embargo_bars": embargo, **{k: result[k] for k in ("number_of_trades", "win_rate", "expectancy", "sharpe", "max_drawdown")}})
    samples = sum(x["number_of_trades"] for x in results)
    return {"status": "PASS" if samples >= 8 else "INSUFFICIENT_HISTORICAL_DATA", "method": "expanding train → parameter lock → embargo → next test",
            "folds": results, "out_of_sample_trades": samples, "purged": True, "embargo": True}


def strategy_incremental_experiment(candles: list[dict], timeframe: str) -> dict:
    variants = ["fibonacci", "fvg", "bos", "fib_fvg_bos"]
    results = {name: strategy_backtest(candles, name, timeframe) for name in variants}
    baseline = strategy_backtest(candles, "trend", timeframe)
    combined = results["fib_fvg_bos"]
    metrics = ("win_rate", "expectancy", "sharpe", "max_drawdown")
    incremental = {metric: _round(_finite(combined.get(metric)) - _finite(baseline.get(metric)), 6) for metric in metrics}
    status = "VALIDATED" if baseline["number_of_trades"] >= 5 and combined["number_of_trades"] >= 5 else "NOT_VALIDATED"
    return {"status": status, "baseline": baseline, "variants": results, "fib_fvg_bos_incremental": incremental,
            "conclusion": "增量仅来自因果样本外交易；样本不足时不声明有效。"}


def ml_ict_incremental_experiment(candles: list[dict], timeframe: str, asset_type: str, horizon: str = "4H") -> dict:
    """Fixed-model ablation on one untouched chronological holdout."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from .ai_engine import (_PlattCalibrator, _aligned_dataset, _metrics,
                            _probabilities, _purged_slices, feature_frame)
    from .horizons import horizon_bar_count

    frame = feature_frame(candles); x, y, meta = _aligned_dataset(frame, asset_type, timeframe, horizon)
    embargo = max(1, horizon_bar_count(asset_type, timeframe, horizon)); slices = _purged_slices(meta, embargo_rows=embargo)
    tr0, tr1 = slices["train"]; ca0, ca1 = slices["calibration"]; te0, te1 = slices["test"]
    if min(tr1-tr0, ca1-ca0, te1-te0) < 25:
        return {"status": "INSUFFICIENT_HISTORICAL_DATA", "samples": len(x), "slices": slices}
    core = [name for name in x.columns if name not in {"causal_bos", "fvg_imbalance", "fib_0618_distance"}]
    variants = {"baseline": core, "fib": core + ["fib_0618_distance"], "fvg": core + ["fvg_imbalance"],
                "bos": core + ["causal_bos"], "fib_fvg": core + ["fib_0618_distance", "fvg_imbalance"],
                "fib_bos": core + ["fib_0618_distance", "causal_bos"], "fvg_bos": core + ["fvg_imbalance", "causal_bos"],
                "fib_fvg_bos": list(x.columns)}
    output = {}
    for name, columns in variants.items():
        model = make_pipeline(StandardScaler(), LogisticRegression(C=.75, class_weight="balanced", max_iter=1200, random_state=42))
        try:
            model.fit(x.iloc[tr0:tr1][columns], y.iloc[tr0:tr1])
            calibrator = _PlattCalibrator().fit(_probabilities(model, x.iloc[ca0:ca1][columns]), y.iloc[ca0:ca1])
            probabilities = calibrator.transform(_probabilities(model, x.iloc[te0:te1][columns])); metrics = _metrics(y.iloc[te0:te1], probabilities)
            direction = np.asarray([-1, 0, 1])[np.argmax(probabilities, axis=1)]
            future = meta["future_return"].iloc[te0:te1].to_numpy(float); returns = direction * future - np.where(direction != 0, .0015, 0)
            curve = np.cumprod(1 + returns); peaks = np.maximum.accumulate(np.r_[1,curve])[1:]
            metrics.update({"ev": _round(returns.mean(), 6),
                            "sharpe": _round(np.sqrt(len(returns))*returns.mean()/returns.std(ddof=1) if len(returns)>1 and returns.std(ddof=1) else 0, 4),
                            "max_drawdown": _round(np.max(1-curve/peaks) if len(curve) else 0, 4), "test_samples": len(returns)})
            output[name] = metrics
        except ValueError as exc:
            output[name] = {"status": "INSUFFICIENT_CLASS_COVERAGE", "reason": str(exc)}
    if "accuracy" not in output.get("baseline", {}) or "accuracy" not in output.get("fib_fvg_bos", {}):
        return {"status": "NOT_VALIDATED", "experiments": output, "slices": slices}
    before, after = output["baseline"], output["fib_fvg_bos"]
    keys = ("accuracy", "f1_macro", "auc_ovr", "brier_score", "ev", "sharpe", "max_drawdown")
    incremental = {key: _round(_finite(after.get(key)) - _finite(before.get(key)), 6) for key in keys}
    useful = incremental["f1_macro"] > 0 and incremental["brier_score"] < 0 and incremental["ev"] > 0
    tradeable = useful and after["ev"] > 0 and after["sharpe"] > 0
    status = "PASS" if tradeable else "INCREMENTAL_VALUE_NOT_TRADEABLE" if useful else "NO_INCREMENTAL_VALUE"
    return {"status": status, "horizon": horizon,
            "validation": "fixed LogisticRegression; train/calibration/untouched test; purged horizon embargo",
            "slices": slices, "experiments": output, "before": before, "after": after, "incremental": incremental,
            "conclusion": ("ICT features improved required dimensions and produced positive OOS EV" if tradeable else
                           "Metrics improved incrementally, but absolute OOS EV/Sharpe remains non-tradeable" if useful else
                           "Fib/FVG/BOS did not improve F1, calibration and EV together on this holdout")}
