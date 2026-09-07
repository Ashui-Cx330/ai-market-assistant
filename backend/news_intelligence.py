"""Auditable market-news intelligence built only from observed public headlines.

This module deliberately distinguishes a deterministic event lexicon from an
NLP model.  No model accuracy is reported until point-in-time outcomes exist.
"""
from __future__ import annotations

import asyncio
import hashlib
import math
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
from xml.etree import ElementTree as ET

import httpx

HEADERS = {"User-Agent": "Mozilla/5.0 AI-Market-Assistant/1.6"}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _published(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            return None


class NewsProvider(ABC):
    provider_type = "NewsProvider"

    @abstractmethod
    async def fetch(self, symbol: str | None = None, name: str | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError


class RSSProvider(NewsProvider):
    provider_type = "RSSProvider"

    def __init__(self, query: str, scope: str, limit: int = 20) -> None:
        self.query, self.scope, self.limit = query, scope, limit

    async def fetch(self, symbol: str | None = None, name: str | None = None) -> list[dict[str, Any]]:
        query = self.query.format(symbol=symbol or "", name=name or symbol or "")
        async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as client:
            response = await client.get("https://news.google.com/rss/search",
                                        params={"q": query, "hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"})
            response.raise_for_status()
        root = ET.fromstring(response.content)
        rows = []
        for node in root.findall("./channel/item")[:self.limit]:
            title = (node.findtext("title") or "").strip()
            link = (node.findtext("link") or "").strip()
            if not title or not link:
                continue
            source_node = node.find("source")
            source = (source_node.text or "Google News RSS").strip() if source_node is not None else "Google News RSS"
            identity = hashlib.sha256(f"{title}|{link}".encode("utf-8")).hexdigest()[:24]
            rows.append({"id": identity, "title": title, "url": link, "source": source,
                         "provider": self.provider_type, "scope": self.scope,
                         "published_at": _published(node.findtext("pubDate")), "collected_at": now_utc(),
                         "symbol": symbol, "raw_summary": None})
        return rows


class MarketNewsProvider(RSSProvider):
    provider_type = "MarketNewsProvider"

    def __init__(self) -> None:
        super().__init__("A股 港股 美股 数字货币 市场 when:1d", "market")


class CompanyNewsProvider(RSSProvider):
    provider_type = "CompanyNewsProvider"

    def __init__(self) -> None:
        super().__init__("{name} {symbol} 公司 财报 公告 when:7d", "company")


class MacroNewsProvider(RSSProvider):
    provider_type = "MacroNewsProvider"

    def __init__(self) -> None:
        super().__init__("美联储 CPI GDP 利率 汇率 原油 黄金 地缘政治 when:3d", "macro")


class AnnouncementProvider(RSSProvider):
    provider_type = "AnnouncementProvider"

    def __init__(self) -> None:
        super().__init__("{name} {symbol} 公告 回购 增持 减持 业绩 when:30d", "announcement")


CATEGORY_RULES = {
    "公司事件": ("财报", "业绩", "回购", "增持", "减持", "高管", "并购", "重组", "定增", "股权激励", "合同", "盈利", "亏损"),
    "行业事件": ("行业", "产业", "供需", "原材料", "技术突破", "库存", "景气", "芯片", "半导体", "服务器", "新能源"),
    "宏观事件": ("美联储", "降息", "加息", "cpi", "ppi", "gdp", "非农", "汇率", "原油", "黄金", "地缘", "关税"),
    "市场事件": ("指数", "北向", "外资", "主力资金", "板块轮动", "市场情绪", "成交量", "牛市", "熊市"),
}
POSITIVE = {"大增": 32, "超预期": 30, "获批": 28, "回购": 23, "增持": 20, "重大合同": 23,
            "突破": 18, "增长": 14, "上涨": 12, "降息": 16, "创新高": 18, "改善": 12, "利好": 18}
NEGATIVE = {"暴跌": -35, "处罚": -30, "调查": -25, "违约": -35, "爆雷": -38, "亏损": -22,
            "减持": -18, "下调": -16, "下跌": -12, "加息": -16, "限制": -20, "风险": -12, "召回": -22}
SECTOR_RULES = {
    "半导体": ("芯片", "半导体", "gpu", "晶圆", "光刻"),
    "AI算力": ("人工智能", "ai ", "算力", "服务器", "大模型"),
    "新能源": ("锂电", "电池", "光伏", "风电", "新能源"),
    "消费": ("白酒", "消费", "零售", "食品"),
    "金融": ("银行", "券商", "保险", "利率"),
    "数字资产": ("比特币", "btc", "以太坊", "eth", "加密", "crypto"),
    "黄金": ("黄金", "gold"),
    "原油": ("原油", "oil", "opec"),
}


class EventExtractionEngine:
    method = "auditable financial event lexicon v1 (not FinBERT/LLM)"

    def analyze(self, item: dict[str, Any], symbol: str | None = None, name: str | None = None) -> dict[str, Any]:
        title = re.sub(r"\s+", " ", str(item.get("title") or "")).strip()
        lower = title.lower()
        contributions = [(word, score) for word, score in {**POSITIVE, **NEGATIVE}.items() if word in lower]
        score = max(-100, min(100, sum(value for _, value in contributions)))
        category = next((category for category, words in CATEGORY_RULES.items() if any(word in lower for word in words)), "市场事件")
        sectors = [sector for sector, words in SECTOR_RULES.items() if any(word in lower for word in words)]
        direction = "强利好" if score >= 45 else "利好" if score >= 10 else "强利空" if score <= -45 else "利空" if score <= -10 else "中性"
        event_type = contributions[0][0] if contributions else next((word for words in CATEGORY_RULES.values() for word in words if word in lower), "一般资讯")
        subject = name or symbol or (title.split("：", 1)[0][:24] if title else "未知")
        confidence = min(0.92, 0.42 + 0.1 * len(contributions) + (0.12 if item.get("published_at") else 0))
        magnitude = min(5, max(1, math.ceil(abs(score) / 20))) if score else 1
        primary = [{"target": subject, "direction": direction, "reason": f"标题包含可审计事件词：{', '.join(x[0] for x in contributions) or '无明确方向词'}"}]
        secondary = [{"target": sector, "direction": "利好" if score > 0 else "利空" if score < 0 else "中性",
                      "reason": f"事件与{sector}关键词映射相关"} for sector in sectors]
        counter = []
        if score >= 20:
            counter.append({"target": "短期高位资产", "direction": "潜在利空", "reason": "正面信息可能已被定价，存在利好兑现风险"})
        elif score <= -20:
            counter.append({"target": "替代供应方/避险资产", "direction": "潜在利好", "reason": "负面冲击可能带来替代或避险需求"})
        impact_score = min(100, round(abs(score) * .55 + magnitude * 8 + len(sectors) * 5 + (8 if item.get("scope") == "macro" else 0)))
        return {**item, "one_sentence_summary": title, "category": category,
                "event": {"subject": subject, "event_type": event_type, "event_time": item.get("published_at"),
                          "direction": direction, "affected_objects": [subject], "affected_sectors": sectors,
                          "magnitude": magnitude, "confidence": round(confidence, 2)},
                "sentiment": {"score": score, "direction": direction, "method": self.method,
                              "evidence": [{"keyword": word, "weight": value} for word, value in contributions]},
                "impact": {"score": impact_score, "primary": primary, "secondary": secondary, "counter": counter,
                           "method": "deterministic causal mapping; requires human review"}}


class TradingDecisionEngine:
    def decide(self, news_score: float, technical_score: float | None = None,
               volume_ratio: float | None = None, sample_count: int = 0) -> dict[str, Any]:
        technical = 0.0 if technical_score is None else (technical_score - 50) * .6
        volume = 0.0 if volume_ratio is None else max(-10, min(10, (volume_ratio - 1) * 10))
        composite = max(-100, min(100, news_score * .45 + technical + volume))
        buy = round(max(0, min(100, 50 + composite * .65)))
        avoid = round(max(0, min(100, 50 - composite * .65)))
        hold = max(0, 100 - max(buy, avoid))
        total = max(1, buy + hold + avoid)
        scores = {"buy": round(buy / total * 100), "hold": round(hold / total * 100), "avoid": round(avoid / total * 100)}
        action = "偏多，等待技术确认后关注" if composite >= 25 else "偏空，优先控制风险" if composite <= -25 else "观望，暂无明确交易优势"
        grade = "A" if sample_count >= 100 and abs(composite) >= 40 else "B" if sample_count >= 30 else "C" if sample_count >= 10 else "D"
        return {"scores": scores, "view": action, "composite_evidence_score": round(composite, 2),
                "confidence_grade": grade, "historical_samples": sample_count,
                "model_historical_accuracy": None,
                "notice": "证据融合分数不是已校准上涨概率；历史准确率仅在真实样本结算后展示。"}


def prediction_horizons(composite: float, sample_count: int) -> dict[str, Any]:
    result = {}
    for horizon, decay in (("T+1", 1.0), ("T+3", .78), ("T+5", .62)):
        edge = max(-30, min(30, composite * decay * .3))
        up, down = 33.3 + edge, 33.3 - edge
        flat = 100 - up - down
        result[horizon] = {"up": round(up, 1), "flat": round(flat, 1), "down": round(down, 1),
                           "type": "uncalibrated_evidence_estimate", "validated_samples": sample_count}
    return result


async def collect_news(symbol: str | None = None, name: str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    providers: list[NewsProvider] = [MarketNewsProvider(), MacroNewsProvider()]
    if symbol:
        providers.extend([CompanyNewsProvider(), AnnouncementProvider()])
    results = await asyncio.gather(*(provider.fetch(symbol, name) for provider in providers), return_exceptions=True)
    rows: dict[str, dict[str, Any]] = {}
    errors = []
    for provider, result in zip(providers, results):
        if isinstance(result, BaseException):
            errors.append({"provider": provider.provider_type, "error": type(result).__name__})
            continue
        for item in result:
            rows.setdefault(item["id"], item)
    return list(rows.values()), errors


def build_intelligence(items: list[dict[str, Any]], symbol: str | None = None, name: str | None = None,
                       technical_score: float | None = None, volume_ratio: float | None = None,
                       sample_count: int = 0) -> dict[str, Any]:
    engine = EventExtractionEngine()
    analyzed = [engine.analyze(item, symbol, name) for item in items]
    analyzed.sort(key=lambda item: (item["impact"]["score"], item.get("published_at") or ""), reverse=True)
    scores = [item["sentiment"]["score"] for item in analyzed]
    market_score = round(sum(scores) / len(scores), 1) if scores else 0.0
    positive = sum(score >= 10 for score in scores); negative = sum(score <= -10 for score in scores)
    neutral = len(scores) - positive - negative
    sectors: dict[str, dict[str, int]] = {}
    for item in analyzed:
        for sector in item["event"]["affected_sectors"]:
            bucket = sectors.setdefault(sector, {"positive": 0, "negative": 0, "neutral": 0, "score": 0})
            direction = "positive" if item["sentiment"]["score"] >= 10 else "negative" if item["sentiment"]["score"] <= -10 else "neutral"
            bucket[direction] += 1; bucket["score"] += item["sentiment"]["score"]
    similar_events = []
    for current in analyzed[:5]:
        current_time = current.get("published_at")
        if not current_time:
            continue
        candidates = []
        for previous in analyzed:
            if not previous.get("published_at") or previous["published_at"] >= current_time or previous["id"] == current["id"]:
                continue
            common_sectors = set(current["event"]["affected_sectors"]) & set(previous["event"]["affected_sectors"])
            score = (2 if current["event"]["event_type"] == previous["event"]["event_type"] else 0) + \
                    (1 if current["category"] == previous["category"] else 0) + len(common_sectors)
            if score:
                candidates.append({"news_id":previous["id"],"event_time":previous["published_at"],
                                   "title":previous["title"],"similarity_evidence":score,
                                   "outcome_status":"NOT_YET_ALIGNED"})
        if candidates:
            similar_events.append({"current_news_id":current["id"],"matches":sorted(candidates,key=lambda row:row["similarity_evidence"],reverse=True)[:3]})
    decision = TradingDecisionEngine().decide(market_score, technical_score, volume_ratio, sample_count)
    return {"status": "AVAILABLE" if analyzed else "NO_DATA", "generated_at": now_utc(),
            "method": engine.method, "radar": {"market_sentiment": market_score, "positive": positive,
            "negative": negative, "neutral": neutral, "major": sum(item["impact"]["score"] >= 55 for item in analyzed)},
            "top_news": analyzed[:10], "all_news": analyzed, "sector_impact": sectors,
            "watch_list": [item for item in analyzed if item["sentiment"]["score"] >= 20][:5],
            "risk_list": [item for item in analyzed if item["sentiment"]["score"] <= -20][:5],
            "historical_similar_events": similar_events,
            "decision": decision, "predictions": prediction_horizons(decision["composite_evidence_score"], sample_count),
            "point_in_time": "Only published_at <= decision time is eligible; missing timestamps are excluded from backtests."}


def event_backtest(events: list[dict[str, Any]], candles: list[dict[str, Any]], event_type: str | None = None) -> dict[str, Any]:
    usable = [item for item in events if item.get("published_at") and (not event_type or item.get("event", {}).get("event_type") == event_type)]
    bars = sorted(candles, key=lambda row: row["timestamp"])
    outcomes = []
    for item in usable:
        event_time = datetime.fromisoformat(item["published_at"].replace("Z", "+00:00"))
        index = next((i for i, bar in enumerate(bars) if datetime.fromisoformat(bar["timestamp"].replace("Z", "+00:00")) > event_time), None)
        if index is None or index + 20 >= len(bars):
            continue
        entry = float(bars[index]["open"])
        row = {"news_id": item["id"], "event_time": item["published_at"], "entry_time": bars[index]["timestamp"]}
        for horizon in (1, 3, 5, 20):
            row[f"t{horizon}_return"] = float(bars[index + horizon]["close"]) / entry - 1
        outcomes.append(row)
    if len(outcomes) < 10:
        return {"status": "DATA_INSUFFICIENT", "samples": len(outcomes), "minimum_samples": 10,
                "notice": "不展示胜率或模型准确率，避免小样本误导。", "outcomes": outcomes}
    t5 = [row["t5_return"] for row in outcomes]
    equity, peak, max_drawdown = 1.0, 1.0, 0.0
    for value in t5:
        equity *= 1 + value; peak = max(peak, equity); max_drawdown = min(max_drawdown, equity / peak - 1)
    wins = [value for value in t5 if value > 0]; losses = [value for value in t5 if value < 0]
    return {"status": "AVAILABLE", "samples": len(outcomes), "win_rate_t5": round(len(wins) / len(t5), 4),
            "average_return_t5": round(sum(t5) / len(t5), 6), "max_drawdown": round(max_drawdown, 6),
            "profit_loss_ratio": round((sum(wins) / len(wins)) / abs(sum(losses) / len(losses)), 4) if wins and losses else None,
            "causality": "event published_at; execution at first strictly later candle open", "outcomes": outcomes}
