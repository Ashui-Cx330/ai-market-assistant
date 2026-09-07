from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass
class FeatureAvailability:
    available: bool
    applicable: bool = True
    source: str | None = None
    status: str = "NO_DATA"
    detail: str | None = None


class MarketDataService:
    def status(self, frame: pd.DataFrame) -> FeatureAvailability:
        ok = not frame.empty and {"open", "high", "low", "close", "volume"}.issubset(frame.columns)
        return FeatureAvailability(bool(ok), source="real OHLCV", status="AVAILABLE" if ok else "NO_DATA")


class FeatureService:
    def status(self, frame: pd.DataFrame) -> FeatureAvailability:
        required = {"rsi", "macd", "atr", "volatility"}
        ok = required.issubset(frame.columns) and not frame[list(required)].dropna().empty
        return FeatureAvailability(bool(ok), source="calculated from historical OHLCV", status="AVAILABLE" if ok else "NO_DATA")


class FlowService:
    def enrich(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        signed = np.sign(result["close"].diff()).fillna(0) * result["volume"]
        denominator = result["volume"].rolling(20, min_periods=5).sum().replace(0, np.nan)
        result["flow_pressure"] = signed.rolling(20, min_periods=5).sum() / denominator
        return result

    def status(self, frame: pd.DataFrame) -> FeatureAvailability:
        ok = "flow_pressure" in frame and frame["flow_pressure"].notna().any()
        return FeatureAvailability(bool(ok), source="real volume-price flow proxy", status="AVAILABLE" if ok else "NO_DATA")


class SentimentService:
    def enrich(self, frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        momentum = result["return_5"].rolling(20, min_periods=5).mean()
        scale = result["volatility"].replace(0, np.nan)
        result["sentiment_score"] = (momentum / scale).clip(-3, 3).fillna(0) / 3
        return result

    def status(self, frame: pd.DataFrame) -> FeatureAvailability:
        ok = "sentiment_score" in frame and frame["sentiment_score"].notna().any()
        return FeatureAvailability(bool(ok), source="real price-volume market sentiment", status="AVAILABLE" if ok else "NO_DATA")


class _UnavailableService:
    name = "external"

    def status(self, asset_type: str) -> FeatureAvailability:
        return FeatureAvailability(False, source=None, status="NO_DATA", detail=f"{self.name} source not configured")


class NewsService(_UnavailableService): name = "news"
class FundamentalService(_UnavailableService):
    name = "fundamental"

    def status(self, asset_type: str) -> FeatureAvailability:
        if asset_type == "crypto":
            return FeatureAvailability(False, applicable=False, status="NOT_APPLICABLE", detail="not applicable to crypto")
        return super().status(asset_type)


class MacroService(_UnavailableService): name = "macro"
class OnChainService(_UnavailableService):
    name = "on-chain"

    def status(self, asset_type: str) -> FeatureAvailability:
        if asset_type == "stock":
            return FeatureAvailability(False, applicable=False, status="NOT_APPLICABLE", detail="not applicable to A-shares")
        return super().status(asset_type)


class FeatureStore:
    def __init__(self) -> None:
        self.market = MarketDataService()
        self.technical = FeatureService()
        self.flow = FlowService()
        self.sentiment = SentimentService()

    def enrich(self, frame: pd.DataFrame) -> pd.DataFrame:
        return self.sentiment.enrich(self.flow.enrich(frame))

    def availability(self, frame: pd.DataFrame, asset_type: str) -> dict:
        statuses = {
            "market": self.market.status(frame),
            "technical": self.technical.status(frame),
            "news": NewsService().status(asset_type),
            "fundamental": FundamentalService().status(asset_type),
            "macro": MacroService().status(asset_type),
            "flow": self.flow.status(frame),
            "onchain": OnChainService().status(asset_type),
            "sentiment": self.sentiment.status(frame),
        }
        applicable = [value for value in statuses.values() if value.applicable]
        coverage = sum(value.available for value in applicable) / max(1, len(applicable))
        result = {
            "features": {key: value.available for key, value in statuses.items()},
            "feature_status": {key: asdict(value) for key, value in statuses.items()},
            "feature_coverage": round(coverage, 4),
            "data_status": "AVAILABLE" if coverage >= .85 else "PARTIAL_DATA" if coverage > 0 else "NO_DATA",
        }
        result.update({f"{key}_available": value.available for key, value in statuses.items()})
        return result
