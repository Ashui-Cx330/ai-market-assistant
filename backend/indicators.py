from __future__ import annotations

import numpy as np
import pandas as pd


def candle_frame(candles: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(candles).copy()
    if frame.empty:
        return frame
    for column in ("open", "high", "low", "close", "volume", "amount"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


def calculate_indicators(candles: list[dict]) -> pd.DataFrame:
    df = candle_frame(candles)
    if df.empty:
        return df
    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]
    for window in (5, 10, 20, 60):
        df[f"ma{window}"] = close.rolling(window).mean()
    df["ema12"] = close.ewm(span=12, adjust=False).mean()
    df["ema26"] = close.ewm(span=26, adjust=False).mean()
    df["macd"] = df["ema12"] - df["ema26"]
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = (df["macd"] - df["macd_signal"]) * 2

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / 14, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = (100 - 100 / (1 + rs)).fillna(50)

    low9, high9 = low.rolling(9).min(), high.rolling(9).max()
    rsv = ((close - low9) / (high9 - low9).replace(0, np.nan) * 100).fillna(50)
    df["kdj_k"] = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    df["kdj_d"] = df["kdj_k"].ewm(alpha=1 / 3, adjust=False).mean()
    df["kdj_j"] = 3 * df["kdj_k"] - 2 * df["kdj_d"]

    df["boll_mid"] = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df["boll_upper"] = df["boll_mid"] + 2 * std20
    df["boll_lower"] = df["boll_mid"] - 2 * std20

    previous = close.shift(1)
    true_range = pd.concat([(high - low), (high - previous).abs(), (low - previous).abs()], axis=1).max(axis=1)
    df["atr"] = true_range.rolling(14).mean()
    direction = np.sign(close.diff()).fillna(0)
    df["obv"] = (direction * volume).cumsum()
    df["volume_change"] = volume.pct_change() * 100
    df["return_1"] = close.pct_change()
    df["return_3"] = close.pct_change(3)
    df["return_5"] = close.pct_change(5)
    df["volatility"] = df["return_1"].rolling(20).std()
    return df


def _clean(value):
    if value is None or pd.isna(value) or np.isinf(value):
        return None
    return round(float(value), 8)


def indicator_payload(candles: list[dict]) -> dict:
    df = calculate_indicators(candles)
    if df.empty:
        raise ValueError("没有可计算的 K线数据")
    # The strategy engine owns the research-grade implementations of the
    # extended indicators.  Import lazily to avoid a module-import cycle while
    # exposing the same live values through the UI indicator payload.
    from .strategy_engine import extended_indicators
    extended = extended_indicators(candles)
    for column in ("stoch_k","stoch_d","psar","psar_trend","mfi","momentum","roc",
                   "donchian_upper_20","donchian_lower_20"):
        df[column] = extended[column]
    columns = ["ma5", "ma10", "ma20", "ma60", "ema12", "ema26", "macd", "macd_signal", "macd_hist",
               "rsi", "kdj_k", "kdj_d", "kdj_j", "boll_mid", "boll_upper", "boll_lower", "atr", "obv", "volume_change",
               "stoch_k","stoch_d","psar","psar_trend","mfi","momentum","roc","donchian_upper_20","donchian_lower_20"]
    latest = {column: _clean(df.iloc[-1].get(column)) for column in columns}
    series = [{"timestamp": row["timestamp"], **{column: _clean(row.get(column)) for column in columns}}
              for _, row in df.iterrows()]
    score = 50
    if latest["ma20"] and df.iloc[-1]["close"] > latest["ma20"]: score += 12
    if latest["macd"] is not None and latest["macd_signal"] is not None and latest["macd"] > latest["macd_signal"]: score += 12
    if latest["rsi"] is not None: score += 8 if 45 <= latest["rsi"] <= 65 else (-8 if latest["rsi"] > 75 else 0)
    if latest["volume_change"] is not None and latest["volume_change"] > 10: score += 6
    return {"latest": latest, "series": series, "score": max(0, min(100, score))}
