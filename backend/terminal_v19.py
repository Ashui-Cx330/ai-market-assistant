from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .cache import cache
from .database import (connection, list_watchlist, load_news_intelligence,
                       load_provider_health, query_news_intelligence,
                       save_news_intelligence, save_provider_health, prediction_statistics,
                       provider_health_snapshot, save_trader_briefing,
                       latest_trader_briefing, save_trader_alert,
                       list_trader_alerts, acknowledge_trader_alert)
from .indicators import calculate_indicators, indicator_payload
from .market import canonical_symbol, crypto_kline, crypto_quote, stock_kline, stock_quote
from .news_intelligence import build_intelligence, collect_news
from .strategy_engine import StrategyEngine

router = APIRouter(prefix="/api/terminal", tags=["Product Terminal v1.9"])
_ANALYSIS_CPU_SEMAPHORE = asyncio.Semaphore(2)
_BACKGROUND_TASKS: set[asyncio.Task] = set()
_BRIEFING_REFRESH = {"status":"IDLE", "started_at":None, "completed_at":None, "error":None}


def _background(coro, name: str) -> None:
    """Run bounded refresh work without making navigation wait for providers."""
    if any(task.get_name() == name and not task.done() for task in _BACKGROUND_TASKS):
        coro.close()
        return
    task=asyncio.create_task(coro,name=name)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)

ASSETS = [
    {"symbol":"NVDA","name":"NVIDIA","asset_type":"stock","market":"美股","industry":"AI / 半导体"},
    {"symbol":"600519","name":"贵州茅台","asset_type":"stock","market":"A股","industry":"消费"},
    {"symbol":"BTC","name":"Bitcoin","asset_type":"crypto","market":"Crypto","industry":"数字资产"},
    {"symbol":"AMD","name":"AMD","asset_type":"stock","market":"美股","industry":"AI / 半导体"},
    {"symbol":"300750","name":"宁德时代","asset_type":"stock","market":"A股","industry":"新能源"},
    {"symbol":"ETH","name":"Ethereum","asset_type":"crypto","market":"Crypto","industry":"智能合约"},
    {"symbol":"AAPL","name":"Apple","asset_type":"stock","market":"美股","industry":"科技"},
    {"symbol":"SOL","name":"Solana","asset_type":"crypto","market":"Crypto","industry":"智能合约"},
    {"symbol":"TSLA","name":"Tesla","asset_type":"stock","market":"美股","industry":"汽车"},
    {"symbol":"MSFT","name":"Microsoft","asset_type":"stock","market":"美股","industry":"软件 / AI"},
]


class ScannerRequest(BaseModel):
    query: str = ""
    market: str = "全部"
    industry: str = "全部"
    change: str = "全部"
    min_ai_score: int = Field(default=0, ge=0, le=100)
    min_volume_ratio: float = Field(default=0, ge=0, le=100)
    max_risk: int = Field(default=100, ge=0, le=100)
    news_direction: str = "全部"


class AssetWorkspaceRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=30)
    asset_type: str
    name: str | None = None
    interval: str = "1d"
    limit: int = Field(default=500, ge=80, le=1200)


class CopilotRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)


class AlertAcknowledgeRequest(BaseModel):
    alert_id: int = Field(gt=0)


class StrategyParseRequest(BaseModel):
    text: str = Field(min_length=2, max_length=500)


class NaturalBacktestRequest(StrategyParseRequest):
    symbol: str
    asset_type: str
    initial_cash: float = Field(default=100000, gt=0)
    fee_rate: float = Field(default=.001, ge=0, le=.05)
    slippage_rate: float = Field(default=.0005, ge=0, le=.05)


def _clamp(value: float) -> int:
    return int(round(max(0, min(100, value))))


def _mean(values: list[float], default: float = 50) -> float:
    return float(sum(values) / len(values)) if values else default


def _scanner_indicator_summary(candles: list[dict]) -> dict:
    """Compute only fields used by scanner scoring; chart series are omitted."""
    frame=calculate_indicators(candles)
    if frame.empty: raise ValueError("没有可计算的 K线数据")
    row=frame.iloc[-1]
    fields=("ma20","ma60","macd","macd_signal","rsi","volume_ratio","atr","volatility")
    latest={name:(None if pd.isna(row.get(name)) else round(float(row.get(name)),8)) for name in fields}
    score=50
    if latest["ma20"] and float(row["close"])>latest["ma20"]: score+=12
    if latest["macd"] is not None and latest["macd_signal"] is not None and latest["macd"]>latest["macd_signal"]: score+=12
    if latest["rsi"] is not None: score+=8 if 45<=latest["rsi"]<=65 else (-8 if latest["rsi"]>75 else 0)
    return {"latest":latest,"series":[],"score":max(0,min(100,score))}


def _news_dimension(symbol: str) -> tuple[int, str, list[dict]]:
    rows = load_news_intelligence(symbol, 50)
    valid = [row for row in rows if isinstance(row.get("sentiment"), dict)]
    values = [float(row["sentiment"].get("score") or 0) for row in valid]
    score = _clamp(50 + _mean(values, 0) / 2)
    label = "利好" if score >= 60 else "利空" if score <= 40 else "中性"
    return score, label, valid[:5]


def _score(quote: dict, indicators: dict, symbol: str) -> dict:
    latest = indicators.get("latest", {})
    close = float(quote.get("price") or 0)
    ma20 = latest.get("ma20")
    ma60 = latest.get("ma60")
    macd = latest.get("macd")
    signal = latest.get("macd_signal")
    rsi = latest.get("rsi")
    volume_ratio = latest.get("volume_ratio")
    atr = latest.get("atr")

    trend = 50 + (18 if ma20 and close > ma20 else -18) + (10 if ma60 and close > ma60 else -10)
    technical = float(indicators.get("score") or 50)
    momentum = 50
    if macd is not None and signal is not None:
        momentum += 18 if macd > signal else -18
    if rsi is not None:
        momentum += 10 if 45 <= rsi <= 65 else -12 if rsi >= 75 else -6 if rsi <= 30 else 0
    volume = 50 if volume_ratio is None else 50 + (float(volume_ratio) - 1) * 30
    volatility = (float(atr) / close * 100) if atr is not None and close else 0
    risk = 28 + min(42, volatility * 8)
    if rsi is not None and (rsi >= 75 or rsi <= 25):
        risk += 18
    news, news_label, news_rows = _news_dimension(symbol)
    components = {
        "trend": _clamp(trend), "technical": _clamp(technical), "news": news,
        "momentum": _clamp(momentum), "volume": _clamp(volume), "risk": _clamp(risk),
    }
    score = _clamp(.28*components["trend"] + .24*components["technical"] + .16*components["news"] +
                   .17*components["momentum"] + .15*components["volume"] - max(0, components["risk"]-50)*.12)
    factors=[]; risks=[]
    factors.append({"label":"价格位于 MA20 上方" if ma20 and close > ma20 else "价格位于 MA20 下方", "positive":bool(ma20 and close > ma20)})
    factors.append({"label":"MACD 动能改善" if macd is not None and signal is not None and macd > signal else "MACD 动能偏弱", "positive":bool(macd is not None and signal is not None and macd > signal)})
    if volume_ratio is not None:
        factors.append({"label":f"成交量比 {float(volume_ratio):.2f}x", "positive":float(volume_ratio)>=1})
    factors.append({"label":f"新闻情绪{news_label}", "positive":news>=50})
    if rsi is not None:
        factors.append({"label":f"RSI {float(rsi):.1f}", "positive":30<float(rsi)<70})
        if rsi >= 70: risks.append("RSI 高位，存在追高与回撤风险")
        if rsi <= 30: risks.append("RSI 低位，但弱势可能延续")
    if volatility >= 3: risks.append(f"ATR 波动率约 {volatility:.1f}%")
    if news <= 40: risks.append("近期新闻情绪偏负面")
    if not risks: risks.append("未发现极端指标，但市场风险始终存在")
    direction = "偏多" if score >= 60 else "偏空" if score <= 40 else "中性"
    return {"ai_score":score,"direction":direction,"components":components,"factors":factors[:5],"risks":risks,
            "news_direction":news_label,"news":news_rows,"score_definition":"当前真实量价、技术指标与已采集新闻的综合信号评分，不是预测准确率或收益保证。"}


async def _compose_analysis(meta: dict, quote: dict, candles: list[dict], source: str,
                            indicators: dict | None = None, compact: bool = False) -> dict:
    canonical = canonical_symbol(meta["symbol"], meta["asset_type"])
    asset_type = meta["asset_type"]
    async with _ANALYSIS_CPU_SEMAPHORE:
        indicators = indicators or await asyncio.to_thread(_scanner_indicator_summary if compact else indicator_payload,candles)
        analysis = await asyncio.to_thread(_score,quote,indicators,canonical)
        def record_score() -> int | None:
            with connection() as conn:
                previous=conn.execute("SELECT score FROM ai_score_history WHERE symbol=? AND asset_type=? ORDER BY id DESC LIMIT 1",(canonical,asset_type)).fetchone()
                prior=int(previous[0]) if previous else None
                if prior != analysis["ai_score"]:
                    conn.execute("INSERT INTO ai_score_history(symbol,asset_type,score) VALUES(?,?,?)",(canonical,asset_type,analysis["ai_score"]))
                return analysis["ai_score"]-prior if prior is not None else None
        score_change=await asyncio.to_thread(record_score)
    return {**quote,**meta,**analysis,"canonical_symbol":canonical,"kline_source":source,
            "score_change":score_change,
            "volume_ratio":indicators["latest"].get("volume_ratio"),"rsi":indicators["latest"].get("rsi"),
            "volatility":indicators["latest"].get("volatility"),
            "preview":candles[-30:],"data_cutoff":candles[-1]["timestamp"]}


async def _market_pair(symbol: str, asset_type: str, interval: str, limit: int) -> tuple[dict,list[dict],str]:
    quote_call=crypto_quote(symbol) if asset_type=="crypto" else stock_quote(symbol)
    kline_call=crypto_kline(symbol,interval,limit) if asset_type=="crypto" else stock_kline(symbol,interval,limit)
    quote_result,kline_result=await asyncio.gather(quote_call,kline_call,return_exceptions=True)
    if isinstance(kline_result,BaseException): raise kline_result
    candles,source=kline_result
    if not candles: raise RuntimeError("行情源没有返回真实K线")
    if isinstance(quote_result,BaseException):
        # A provider's 1-minute quote route may be blocked while its historical
        # route is healthy. Use the latest real candle explicitly as a delayed
        # fallback instead of discarding the whole workspace or inventing data.
        latest=candles[-1];previous=candles[-2] if len(candles)>1 else latest
        price=float(latest["close"]);prior=float(previous["close"])
        is_a_share=asset_type=="stock" and (symbol.isdigit() or symbol.endswith((".SH",".SZ")))
        quote_result={"symbol":symbol,"canonical_symbol":symbol,"name":symbol,"asset_type":asset_type,
                      "market":"Crypto" if asset_type=="crypto" else "A股" if is_a_share else "美股",
                      "currency":"USDT" if asset_type=="crypto" else "CNY" if is_a_share else "USD",
                      "price":price,"change":price-prior,"change_percent":((price/prior)-1)*100 if prior else 0,
                      "open":float(latest["open"]),"previous_close":prior,"high":float(latest["high"]),
                      "low":float(latest["low"]),"volume":float(latest["volume"]),"amount":latest.get("amount"),
                      "source":source+"（最新真实K线降级报价）","updated_at":latest["timestamp"],
                      "quote_status":"DELAYED_KLINE_FALLBACK","quote_error":type(quote_result).__name__}
    return quote_result,candles,source


async def analyze_asset(meta: dict) -> dict:
    symbol, asset_type = meta["symbol"], meta["asset_type"]
    canonical = canonical_symbol(symbol, asset_type)
    analysis_key = f"terminal-analysis-v19:{asset_type}:{canonical}"
    if saved := cache.get(analysis_key):
        return {**saved, **meta}
    quote,candles,source = await _market_pair(canonical,asset_type,"1d",240)
    result = await _compose_analysis(meta, quote, candles, source, compact=True)
    cache.set(analysis_key, result, 120)
    return result


async def scan_assets(request: ScannerRequest, limit: int = 20, provider_concurrency: int = 3) -> dict:
    candidates = list(ASSETS)
    existing={(x["symbol"],x["asset_type"]) for x in candidates}
    for row in list_watchlist():
        key=(row["symbol"],row["asset_type"])
        if key not in existing:
            market="Crypto" if row["asset_type"]=="crypto" else "美股" if re.match(r"^[A-Z]",row["symbol"]) else "A股"
            candidates.append({"symbol":row["symbol"],"name":row.get("name") or row["symbol"],"asset_type":row["asset_type"],"market":market,"industry":"自选"})
    cache_payload={"filters":request.model_dump(),"limit":limit,
                   "watchlist":[(x["symbol"],x["asset_type"]) for x in candidates if x.get("industry")=="自选"]}
    scan_key="terminal-scan-v19:"+hashlib.sha256(json.dumps(cache_payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if saved := cache.get(scan_key):
        return {**saved,"cache_status":"FRESH"}
    query=request.query.strip().lower()
    natural=any(token in query for token in ("找出","筛选","趋势","板块","score","成交量","放大","风险"))
    if "美股" in query: candidates=[x for x in candidates if x["market"]=="美股"]
    elif "a股" in query or "A股" in request.query: candidates=[x for x in candidates if x["market"]=="A股"]
    elif "crypto" in query or "加密" in query: candidates=[x for x in candidates if x["market"]=="Crypto"]
    if "ai" in query and natural: candidates=[x for x in candidates if "ai" in x["industry"].lower() or "半导体" in x["industry"]]
    score_match=re.search(r"(?:AI\s*SCORE|评分)\s*(?:>|大于|高于)\s*(\d+)",request.query,re.I)
    if score_match: request.min_ai_score=max(request.min_ai_score,int(score_match.group(1)))
    if query and not natural:
        candidates=[x for x in candidates if query in x["symbol"].lower() or query in x["name"].lower() or query in x["industry"].lower()]
    if request.market!="全部":candidates=[x for x in candidates if x["market"]==request.market]
    if request.industry!="全部":candidates=[x for x in candidates if request.industry.lower() in x["industry"].lower()]
    # A broad scan must not open twenty provider connections at once: on
    # constrained/proxied networks that can starve the event loop itself.
    # Return the completed real rows within one bounded page-load budget and
    # report timed-out symbols explicitly.
    provider_slots=asyncio.Semaphore(max(1,provider_concurrency))
    async def bounded_analysis(meta: dict) -> dict:
        async with provider_slots:
            return await analyze_asset(meta)
    tasks=[asyncio.create_task(bounded_analysis(x)) for x in candidates[:limit]]
    done,pending=await asyncio.wait(tasks,timeout=18)
    for task in pending: task.cancel()
    if pending: await asyncio.gather(*pending,return_exceptions=True)
    results=[task.result() if task in done and not task.cancelled() and task.exception() is None
             else task.exception() if task in done and not task.cancelled()
             else TimeoutError("provider budget exceeded") for task in tasks]
    rows=[];errors=[]
    for meta,result in zip(candidates[:limit],results):
        if isinstance(result,Exception): errors.append({"symbol":meta["symbol"],"error":f"{type(result).__name__}: {str(result)[:160]}"})
        else: rows.append(result)
    if request.change=="上涨":rows=[x for x in rows if float(x.get("change_percent") or 0)>0]
    elif request.change=="下跌":rows=[x for x in rows if float(x.get("change_percent") or 0)<0]
    rows=[x for x in rows if x["ai_score"]>=request.min_ai_score and x["components"]["risk"]<=request.max_risk and
          float(x.get("volume_ratio") or 0)>=request.min_volume_ratio]
    if request.news_direction!="全部":rows=[x for x in rows if x["news_direction"]==request.news_direction]
    if "趋势向上" in query: rows=[x for x in rows if x["components"]["trend"]>=60]
    if "成交量放大" in query or "放量" in query: rows=[x for x in rows if float(x.get("volume_ratio") or 0)>1]
    rows.sort(key=lambda x:(x["ai_score"],float(x.get("change_percent") or -999)),reverse=True)
    result={"rows":rows,"errors":errors,"requested":len(candidates[:limit]),"available":len(rows),
            "universe":"curated liquid cross-market universe plus local watchlist; every row is fetched from a public market source",
            "generated_at":datetime.now(timezone.utc).isoformat(),"cache_status":"MISS"}
    if rows:
        cache.set(scan_key, result, 60)
    return result


def _market_status() -> list[dict]:
    now_utc=datetime.now(timezone.utc); sh=now_utc.astimezone(ZoneInfo("Asia/Shanghai")); ny=now_utc.astimezone(ZoneInfo("America/New_York"))
    weekday=sh.weekday()<5
    a_open=weekday and (time(9,30)<=sh.time()<=time(11,30) or time(13)<=sh.time()<=time(15))
    us_weekday=ny.weekday()<5
    us_open=us_weekday and time(9,30)<=ny.time()<=time(16)
    pre=us_weekday and time(4)<=ny.time()<time(9,30)
    return [
        {"market":"A股","status":"Trading" if a_open else "Closed","time":sh.strftime("%H:%M:%S"),"timezone":"Asia/Shanghai"},
        {"market":"美股","status":"Trading" if us_open else "Pre-market" if pre else "Closed","time":ny.strftime("%H:%M:%S"),"timezone":"America/New_York"},
        {"market":"Crypto","status":"Trading","time":now_utc.strftime("%H:%M:%S"),"timezone":"UTC"},
    ]


@router.post("/scanner")
async def scanner(body: ScannerRequest) -> dict:
    return {"success":True,"data":await scan_assets(body),"source":"public market APIs + locally persisted public news"}


@router.post("/asset-workspace")
async def asset_workspace(body: AssetWorkspaceRequest) -> dict:
    """Load one detail workspace without fetching quote/K-line data twice."""
    asset_type=body.asset_type.lower()
    if asset_type not in {"stock","crypto"}: raise HTTPException(422,"asset_type 仅支持 stock 或 crypto")
    canonical=canonical_symbol(body.symbol,asset_type)
    try:
        quote,candles,source=await asyncio.wait_for(
            _market_pair(canonical,asset_type,body.interval,body.limit),timeout=30)
    except TimeoutError as exc:
        raise HTTPException(504,"公开行情源响应超过30秒，请稍后重试") from exc
    indicators=await asyncio.to_thread(indicator_payload,candles)
    market="Crypto" if asset_type=="crypto" else "A股" if canonical.isdigit() else "美股"
    meta={"symbol":canonical,"name":body.name or quote.get("name") or canonical,"asset_type":asset_type,
          "market":market,"industry":"详情资产"}
    analysis=await _compose_analysis(meta,quote,candles,source,indicators)
    return {"success":True,"data":{"quote":quote,"candles":candles,"indicators":indicators,"analysis":analysis,
            "source":source,"data_cutoff":candles[-1]["timestamp"]},"source":source}


async def _build_dashboard(provider_concurrency: int = 3) -> dict:
    scanned=await scan_assets(ScannerRequest(),provider_concurrency=provider_concurrency)
    rows=scanned["rows"]
    if not rows: raise HTTPException(503,"所有公开行情源暂时不可用")
    trend=_clamp(_mean([x["components"]["trend"] for x in rows]));sentiment=_clamp(_mean([x["components"]["news"] for x in rows]))
    volume=_clamp(_mean([x["components"]["volume"] for x in rows]));risk=_clamp(_mean([x["components"]["risk"] for x in rows]));news=sentiment
    pulse=_clamp(.30*trend+.20*sentiment+.18*volume+.17*news+.15*(100-risk))
    stance="偏多" if pulse>=60 else "偏空" if pulse<=40 else "中性"
    leaders=sorted(rows,key=lambda x:float(x.get("change_percent") or 0),reverse=True)
    high_risk=sorted(rows,key=lambda x:x["components"]["risk"],reverse=True)
    headlines=[]
    seen=set()
    for row in rows:
        for item in row.get("news",[]):
            if item.get("id") not in seen:seen.add(item.get("id"));headlines.append(item)
    headlines.sort(key=lambda x:(x.get("impact") or {}).get("score",0),reverse=True)
    brief=(f"跨市场综合信号为{stance}（{pulse}/100）。趋势维度 {trend}，量能维度 {volume}，"
           f"新闻情绪维度 {news}，风险维度 {risk}。当前较强标的是 {leaders[0]['symbol']}；"
           f"高分只代表当前可观测信号一致，不构成上涨保证。")
    result={"market_status":_market_status(),"pulse":{"score":pulse,"stance":stance,"trend":trend,"sentiment":sentiment,"volume":volume,"news":news,"risk":risk},
            "brief":brief,"movers":{"gainers":leaders[:5],"losers":list(reversed(leaders[-5:])),"volume":sorted(rows,key=lambda x:float(x.get("volume_ratio") or 0),reverse=True)[:5]},
            "opportunities":sorted(rows,key=lambda x:x["ai_score"],reverse=True)[:5],"risk_watch":high_risk[:5],"breaking_news":headlines[:5],
            "data_cutoff":max((x.get("updated_at") or "" for x in rows),default=""),"generated_at":datetime.now(timezone.utc).isoformat(),
            "errors":scanned["errors"],"method":"deterministic aggregation of real quotes, OHLCV indicators and persisted public news"}
    cache.set("terminal-v19-dashboard",result,30)
    return result


async def _refresh_dashboard() -> None:
    try:
        # One provider/indicator job at a time keeps the API event loop and the
        # Electron renderer responsive while the old observed snapshot remains
        # visible.
        await _build_dashboard(provider_concurrency=1)
    except Exception:
        # A stale observed snapshot remains preferable to a blank terminal when
        # a public provider is temporarily blocked.
        return


@router.get("/dashboard")
async def dashboard(force: bool = False) -> dict:
    fresh=cache.get("terminal-v19-dashboard")
    if fresh and not force:
        return {"success":True,"data":{**fresh,"refresh_status":"FRESH"},"source":"short-lived terminal cache"}
    stale=cache.get_stale("terminal-v19-dashboard")
    if stale:
        if force:
            _background(_refresh_dashboard(),"refresh:dashboard")
        status="REFRESHING_IN_BACKGROUND" if force else "STALE_SNAPSHOT"
        return {"success":True,"data":{**stale,"refresh_status":status},
                "source":"persisted observed snapshot"+("; background refresh started" if force else "")}
    result=await _build_dashboard()
    return {"success":True,"data":{**result,"refresh_status":"FRESH"},"source":"public market APIs + locally persisted public news"}


async def _refresh_watchlist_news() -> None:
    slots=asyncio.Semaphore(3)
    async def one(asset: dict) -> None:
        async with slots:
            rows,statuses=await collect_news(asset["symbol"],asset.get("name"),limit=30)
            if rows:
                analyzed=build_intelligence(rows,asset["symbol"],asset.get("name"))["all_news"]
                await asyncio.to_thread(save_news_intelligence,analyzed,asset["symbol"])
            await asyncio.to_thread(save_provider_health,statuses)
    await asyncio.gather(*(one(asset) for asset in list_watchlist()),return_exceptions=True)


def _watchlist_news_payload(direction: str | None, hours: int) -> dict:
    assets=list_watchlist();items=[];seen=set()
    for asset in assets:
        canonical=canonical_symbol(asset["symbol"],asset["asset_type"])
        feed=query_news_intelligence(canonical,direction=direction,hours=hours,page_size=100)
        for item in feed["items"]:
            identity=item.get("id") or item.get("url") or item.get("title")
            if identity in seen: continue
            seen.add(identity)
            copy=dict(item);copy["matched_watchlist_symbols"]=sorted(set(item.get("symbols",[])) &
                {canonical,asset["symbol"]}) or [asset["symbol"]]
            items.append(copy)
    items.sort(key=lambda x:x.get("published_at") or x.get("collected_at") or "",reverse=True)
    scores=[float(x.get("sentiment",{}).get("score") or 0) for x in items]
    average=round(sum(scores)/len(scores),1) if scores else None
    return {"items":items[:100],"total":len(items),"assets":assets,"hours":hours,
            "radar":{"market_sentiment":average,"positive":sum(x>=10 for x in scores),
                     "negative":sum(x<=-10 for x in scores),"neutral":sum(-10<x<10 for x in scores)},
            "scope":"ONLY_EXPLICIT_WATCHLIST_RELATIONS",
            "generated_at":datetime.now(timezone.utc).isoformat()}


@router.get("/watchlist-news")
async def watchlist_news(direction: str | None = None, hours: int = Query(default=168,ge=1,le=8760),
                         refresh: bool = False) -> dict:
    """Return persisted breaking news immediately; refresh providers off-path."""
    if refresh:
        _background(_refresh_watchlist_news(),"refresh:watchlist-news")
    payload=await asyncio.to_thread(_watchlist_news_payload,direction,hours)
    if not payload["items"] and hours<720:
        payload=await asyncio.to_thread(_watchlist_news_payload,direction,720)
        payload["fallback_window"]=True
    payload["refresh_status"]="REFRESHING_IN_BACKGROUND" if refresh else "LOCAL_SNAPSHOT"
    return {"success":True,"data":payload,"source":"local normalized news database + background public-provider refresh"}


def _weighted_news_score(items: list[dict]) -> float | None:
    now=datetime.now(timezone.utc);weighted=[]
    for item in items:
        try:
            stamp=datetime.fromisoformat(str(item.get("published_at")).replace("Z","+00:00"))
            if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
            age=max(0,(now-stamp.astimezone(timezone.utc)).total_seconds()/3600)
        except (TypeError,ValueError): age=168
        recency=math.exp(-age/96);impact=.5+float(item.get("impact",{}).get("score") or 0)/100
        weighted.append((float(item.get("sentiment",{}).get("score") or 0),recency*impact))
    total=sum(weight for _,weight in weighted)
    return round(sum(score*weight for score,weight in weighted)/total,2) if total else None


@router.get("/watchlist-report")
async def watchlist_report(symbol: str, asset_type: str, name: str | None = None) -> dict:
    """Auditable news + V5 mathematical/technical decision report for one watch asset."""
    if asset_type not in {"stock","crypto"}: raise HTTPException(422,"asset_type 仅支持 stock 或 crypto")
    canonical=canonical_symbol(symbol,asset_type);key=f"watch-report-v1:{asset_type}:{canonical}"
    if saved:=cache.get(key):
        return {"success":True,"data":{**saved,"cache_status":"FRESH"},"source":saved["data_source"]}
    quote,candles,source=await asyncio.wait_for(_market_pair(canonical,asset_type,"1d",500),timeout=30)
    indicators=await asyncio.to_thread(indicator_payload,candles)
    market="Crypto" if asset_type=="crypto" else "A股" if canonical.split(".")[0].isdigit() else "美股"
    meta={"symbol":canonical,"name":name or quote.get("name") or canonical,"asset_type":asset_type,
          "market":market,"industry":"自选"}
    terminal=await _compose_analysis(meta,quote,candles,source,indicators)
    strategy=await asyncio.to_thread(StrategyEngine().analyze,candles,"1d",source)
    feed=await asyncio.to_thread(query_news_intelligence,canonical,None,None,None,None,168,1,100)
    if not feed["items"]:
        feed=await asyncio.to_thread(query_news_intelligence,canonical,None,None,None,None,720,1,100)
    news_score=_weighted_news_score(feed["items"])
    technical_score=float(strategy["confluence"]["score"])
    terminal_score=(float(terminal["ai_score"])-50)*2
    if news_score is None:
        combined=.7*technical_score+.3*terminal_score;weights={"v5_technical":.7,"terminal_factors":.3,"news":0}
    else:
        combined=.55*technical_score+.25*terminal_score+.20*news_score;weights={"v5_technical":.55,"terminal_factors":.25,"news":.20}
    combined=round(max(-100,min(100,combined)),2)
    direction="偏多" if combined>=15 else "偏空" if combined<=-15 else "中性"
    action="做多观察" if direction=="偏多" else "看空/规避" if direction=="偏空" else "等待确认"
    risk=dict(strategy["risk_plan"]);entry=float(risk["entry"]);atr=float(indicators["latest"].get("atr") or entry*.02)
    # The V5 engine defaults a range to a long-side defensive line. If news
    # fusion changes the final side to bearish, mirror risk geometry above the
    # observed entry instead of presenting a contradictory long stop.
    if direction=="偏空" and float(risk["stop_loss"])<entry:
        unit=max(1.5*atr,entry*.015);risk["stop_loss"]=round(entry+unit,8)
        risk["take_profits"]=[{"name":f"TP{i}","price":round(entry-unit*i,8),"risk_reward":float(i)} for i in (1,2,3)]
        risk["stop_sources"]={"method":"bearish ATR geometry after news/technical fusion","atr":atr}
    positive=sum(float(x.get("sentiment",{}).get("score") or 0)>=10 for x in feed["items"])
    negative=sum(float(x.get("sentiment",{}).get("score") or 0)<=-10 for x in feed["items"])
    summary=(f"最近新闻共 {len(feed['items'])} 条（利好 {positive}、利空 {negative}），"
             f"时间衰减影响分为 {news_score if news_score is not None else '无可用方向分'}；"
             f"V5 技术共识 {technical_score:+.2f}，综合评估 {combined:+.2f}，当前结论：{action}。")
    signals=sorted([x for x in strategy["signals"] if x["status"]=="AVAILABLE"],
                   key=lambda x:float(x.get("confidence") or 0),reverse=True)[:8]
    report={"symbol":canonical,"name":meta["name"],"asset_type":asset_type,"currency":quote.get("currency"),
            "current_price":float(quote["price"]),"verdict":direction,"action":action,
            "score":combined,"summary":summary,"news":{"items":feed["items"][:20],"count":len(feed["items"]),
            "positive":positive,"negative":negative,"weighted_score":news_score,"window_hours":168 if feed["items"] else 720},
            "components":{"v5_technical":technical_score,"terminal_factors":terminal_score,"news":news_score,"weights":weights},
            "risk_plan":{**risk,"exit_line":risk["stop_loss"],"exit_rule":"日线收盘有效越过失效线，或 BOS/FVG/共识方向反转时离场"},
            "market_regime":strategy["market_regime"],"top_signals":signals,
            "evidence":{"bullish":strategy["evidence_chain"]["bullish"][:6],"bearish":strategy["evidence_chain"]["bearish"][:6]},
            "model_basis":["30类V5因果技术策略","ICT/SMC + BOS/CHoCH + FVG","Fibonacci结构","ATR风险距离",
                           "历史MFE/MAE目标触达与期望值","近期新闻时间衰减与影响分"],
            "data_source":source,"data_cutoff":candles[-1]["timestamp"],"generated_at":datetime.now(timezone.utc).isoformat(),
            "notice":"这是基于可观测数据的研究评估，不是收益保证；新闻规则情绪尚不是校准概率。"}
    cache.set(key,report,300)
    return {"success":True,"data":{**report,"cache_status":"MISS"},"source":source}


def _parse_utc(value: str | None) -> datetime | None:
    try:
        stamp=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
    except (TypeError,ValueError):
        return None


def _briefing_item(report: dict, sample_count: int) -> tuple[dict,list[dict]]:
    now=datetime.now(timezone.utc);cutoff=_parse_utc(report.get("data_cutoff"))
    age_hours=round((now-cutoff).total_seconds()/3600,1) if cutoff else None
    stale_limit=8 if report["asset_type"]=="crypto" else 96
    stale=age_hours is None or age_hours>stale_limit
    price=float(report.get("current_price") or report["risk_plan"]["entry"])
    exit_line=float(report["risk_plan"]["exit_line"])
    bullish=report["verdict"]=="偏多";bearish=report["verdict"]=="偏空"
    breached=(bullish and price<=exit_line) or (bearish and price>=exit_line)
    headlines=report.get("news",{}).get("items",[])[:3]
    important=[x for x in headlines if float(x.get("impact",{}).get("score") or 0)>=80]
    evidence_grade="C" if sample_count>=100 and not stale else "D"
    blockers=["生产模型状态为 NO EDGE，方向仅供研究观察"]
    if sample_count<100: blockers.append(f"本机已结算样本仅 {sample_count}，不足以证明优势")
    if stale: blockers.append("行情数据已过新鲜度阈值，禁止据此行动")
    if report.get("news",{}).get("count",0)==0: blockers.append("近期没有明确关联新闻")
    if breached: gate="RISK_REVIEW";next_action="价格已越过失效线：先复核或退出模拟仓位"
    elif stale: gate="NO_ACTION";next_action="等待行情恢复后再评估"
    elif important: gate="RISK_REVIEW";next_action="存在高影响快讯：核对原文与价格确认"
    elif bullish or bearish: gate="WATCH_ONLY";next_action="等待价格、结构与成交量确认，不追单"
    else: gate="NO_ACTION";next_action="没有一致证据，保持观察"
    priority=100 if breached else 80 if important else 70 if stale else 45 if bullish or bearish else 20
    item={"symbol":report["symbol"],"name":report["name"],"asset_type":report["asset_type"],
          "currency":report.get("currency"),"current_price":price,"verdict":report["verdict"],
          "action":report["action"],"score":report["score"],"decision_gate":gate,
          "next_action":next_action,"priority":priority,"data_cutoff":report.get("data_cutoff"),
          "age_hours":age_hours,"is_stale":stale,"evidence_grade":evidence_grade,
          "resolved_samples":sample_count,"risk_plan":report["risk_plan"],
          "components":report["components"],"summary":report["summary"],"headlines":headlines,
          "blockers":blockers,"data_source":report.get("data_source")}
    alerts=[];created=now.isoformat();suffix=str(report.get("data_cutoff") or "unknown")
    if breached:
        alerts.append({"fingerprint":f"exit:{report['asset_type']}:{report['symbol']}:{suffix}",
            "symbol":report["symbol"],"asset_type":report["asset_type"],"alert_type":"EXIT_LINE_BREACH",
            "severity":"CRITICAL","title":f"{report['symbol']} 已越过失效线",
            "detail":f"现价 {price:g}，失效线 {exit_line:g}。请先复核，不自动下单。",
            "data_cutoff":report.get("data_cutoff"),"created_at":created})
    if stale:
        alerts.append({"fingerprint":f"stale:{report['asset_type']}:{report['symbol']}:{suffix}",
            "symbol":report["symbol"],"asset_type":report["asset_type"],"alert_type":"STALE_DATA",
            "severity":"WARNING","title":f"{report['symbol']} 数据过期",
            "detail":f"数据距今 {age_hours if age_hours is not None else '未知'} 小时，决策门已关闭。",
            "data_cutoff":report.get("data_cutoff"),"created_at":created})
    for news in important:
        news_id=str(news.get("id") or hashlib.sha256(str(news.get("title")).encode()).hexdigest()[:16])
        alerts.append({"fingerprint":f"news:{report['symbol']}:{news_id}","symbol":report["symbol"],
            "asset_type":report["asset_type"],"alert_type":"HIGH_IMPACT_NEWS","severity":"WARNING",
            "title":f"{report['symbol']} 出现高影响快讯","detail":str(news.get("title") or "请核对新闻原文"),
            "data_cutoff":report.get("data_cutoff"),"created_at":created})
    return item,alerts


async def _refresh_trader_briefing() -> None:
    _BRIEFING_REFRESH.update(status="RUNNING",started_at=datetime.now(timezone.utc).isoformat(),error=None)
    previous=await asyncio.to_thread(latest_trader_briefing)
    prior={(x["asset_type"],x["symbol"]):x for x in (previous or {}).get("items",[])}
    assets=list_watchlist();slots=asyncio.Semaphore(2);items=[];errors=[];alerts=[]
    with connection() as conn:
        sample_rows=conn.execute("""SELECT symbol,asset_type,COUNT(*) samples FROM prediction_history
            WHERE status='RESOLVED' GROUP BY symbol,asset_type""").fetchall()
    samples={(x["symbol"],x["asset_type"]):int(x["samples"]) for x in sample_rows}
    async def one(asset: dict) -> None:
        async with slots:
            try:
                response=await asyncio.wait_for(watchlist_report(asset["symbol"],asset["asset_type"],asset.get("name")),timeout=38)
                item,new_alerts=_briefing_item(response["data"],samples.get((asset["symbol"],asset["asset_type"]),0))
                old=prior.get((item["asset_type"],item["symbol"]))
                if old and (old.get("decision_gate"),old.get("verdict")) != (item["decision_gate"],item["verdict"]):
                    new_alerts.append({"fingerprint":f"state:{item['asset_type']}:{item['symbol']}:{item['data_cutoff']}:{item['decision_gate']}:{item['verdict']}",
                        "symbol":item["symbol"],"asset_type":item["asset_type"],"alert_type":"STATE_CHANGE",
                        "severity":"INFO","title":f"{item['symbol']} 研究状态发生变化",
                        "detail":f"{old.get('verdict')} / {old.get('decision_gate')} → {item['verdict']} / {item['decision_gate']}",
                        "data_cutoff":item["data_cutoff"],"created_at":datetime.now(timezone.utc).isoformat()})
                items.append(item);alerts.extend(new_alerts)
            except Exception as exc:
                errors.append({"symbol":asset["symbol"],"asset_type":asset["asset_type"],"error":str(exc)})
    await asyncio.gather(*(one(asset) for asset in assets))
    items.sort(key=lambda x:(-x["priority"],x["symbol"]))
    generated=datetime.now(timezone.utc).isoformat()
    payload={"snapshot_id":str(hashlib.sha256(generated.encode()).hexdigest()[:24]),"generated_at":generated,
        "data_cutoff":max((x.get("data_cutoff") or "" for x in items),default=None),"items":items,"errors":errors,
        "coverage":{"requested":len(assets),"completed":len(items),"failed":len(errors)},
        "research_status":"NO EDGE","production_model":"NONE","decision_policy":"RISK_FIRST_NO_AUTO_TRADING",
        "notice":"决策台用于压缩研究与风险复核时间，不是买卖指令或收益承诺。"}
    await asyncio.to_thread(save_trader_briefing,payload)
    for alert in alerts: await asyncio.to_thread(save_trader_alert,alert)
    cache.set("trader-briefing-v1",payload,300)
    _BRIEFING_REFRESH.update(status="COMPLETED",completed_at=generated,error=None)


def _start_briefing_refresh() -> None:
    if _BRIEFING_REFRESH["status"]!="RUNNING":
        async def guarded() -> None:
            try:
                await _refresh_trader_briefing()
            except Exception as exc:
                _BRIEFING_REFRESH.update(status="FAILED",completed_at=datetime.now(timezone.utc).isoformat(),error=str(exc))
        _background(guarded(),"refresh:trader-briefing")


@router.get("/trader-briefing")
async def trader_briefing(refresh: bool = False) -> dict:
    payload=cache.get("trader-briefing-v1") or await asyncio.to_thread(latest_trader_briefing)
    generated=_parse_utc((payload or {}).get("generated_at"))
    expired=not generated or (datetime.now(timezone.utc)-generated)>timedelta(minutes=15)
    if refresh or expired: _start_briefing_refresh()
    if not payload:
        payload={"snapshot_id":None,"generated_at":None,"data_cutoff":None,"items":[],"errors":[],
            "coverage":{"requested":len(list_watchlist()),"completed":0,"failed":0},"research_status":"NO EDGE",
            "production_model":"NONE","decision_policy":"RISK_FIRST_NO_AUTO_TRADING",
            "notice":"首次决策简报正在后台生成；页面不会等待外部数据源。"}
    return {"success":True,"data":{**payload,"refresh":dict(_BRIEFING_REFRESH),
        "alerts":await asyncio.to_thread(list_trader_alerts,True,100)},"source":"persistent local decision-desk snapshots"}


@router.post("/trader-briefing/refresh")
async def refresh_trader_briefing() -> dict:
    _start_briefing_refresh()
    return {"success":True,"data":{"status":_BRIEFING_REFRESH["status"]}}


@router.post("/trader-alerts/acknowledge")
async def acknowledge_alert(body: AlertAcknowledgeRequest) -> dict:
    if not await asyncio.to_thread(acknowledge_trader_alert,body.alert_id):
        raise HTTPException(404,"提醒不存在")
    return {"success":True,"data":{"alert_id":body.alert_id,"status":"ACKNOWLEDGED"}}


@router.get("/model-lab")
def model_lab(symbol: str | None = None) -> dict:
    with connection() as conn:
        rows=[dict(x) for x in conn.execute("SELECT symbol,horizon,COUNT(*) samples,AVG(correct) accuracy,AVG(ABS(actual_return)) mae FROM prediction_history WHERE status='RESOLVED' GROUP BY symbol,horizon ORDER BY symbol,horizon")]
    live={}
    for row in rows:
        live.setdefault(row["symbol"],[]).append({"horizon":row["horizon"],"samples":row["samples"],"accuracy":round(float(row["accuracy"])*100,2) if row["accuracy"] is not None else None,
                                                  "mae":round(float(row["mae"])*100,3) if row["mae"] is not None else None,"source":"local resolved prediction history"})
    statistics=prediction_statistics();assets=[]
    for name,history in live.items():
        periods=[]
        for item in history:
            metric=statistics["by_horizon"].get(item["horizon"],{})
            periods.append({"horizon":item["horizon"],"accuracy":item["accuracy"],"baseline":None,"edge":None,
                "assessment":"NO_EDGE" if metric.get("samples",0)<100 else "REQUIRES_BENCHMARK",
                "evidence_level":"D — Experimental" if metric.get("samples",0)<100 else "C — Requires baseline comparison",
                "precision":metric.get("precision_macro"),"recall":metric.get("recall_macro"),"f1":metric.get("f1_macro"),
                "brier_score":metric.get("brier_score"),"log_loss":metric.get("log_loss"),"ic":metric.get("ic"),
                "rank_ic":metric.get("rank_ic"),"icir":metric.get("icir"),"sharpe":metric.get("sharpe"),
                "confidence_interval_95":None,"note":"仅来自本机不可变结算历史；未达到生产晋级条件。"})
        assets.append({"symbol":name,"status":"EXPERIMENTAL","model_version":"6.0 Quant Intelligence V2",
                       "periods":periods,"resolved_history":history,"sample_count":sum(x["samples"] for x in history),
                       "training_range":None,"test_range":None,"notice":"不再展示旧版静态审计常量；缺失指标保持为空。"})
    if symbol: assets=[x for x in assets if x["symbol"]==symbol.upper()]
    return {"success":True,"data":{"assets":assets,"overall":statistics["overall"],"validation":"Immutable resolved history + purged expanding walk-forward benchmark; no random split and no static showcase metrics",
                                     "generated_at":datetime.now(timezone.utc).isoformat()}}


@router.get("/data-health")
async def data_health() -> dict:
    providers=provider_health_snapshot(); now=datetime.now(timezone.utc).isoformat()
    checks=await asyncio.gather(stock_quote("000001"),stock_quote("NVDA"),crypto_quote("BTC"),return_exceptions=True)
    def health(index:int,source:str,mode:str,realtime:str) -> dict:
        value=checks[index]
        if isinstance(value,Exception):return {"status":"WARNING","source":source,"mode":mode,"realtime":realtime,"last_update":None,"error":f"{type(value).__name__}: {str(value)[:160]}"}
        return {"status":"CONNECTED","source":value.get("source") or source,"mode":mode,"realtime":realtime,"last_update":value.get("updated_at")}
    items=[
        {"name":"A股",**health(0,"东方财富 / 腾讯证券备用","增量轮询","公开行情，交易时段轮询")},
        {"name":"美股",**health(1,"Yahoo Finance public chart API","增量轮询","可能延迟，不是交易所授权逐笔行情")},
        {"name":"Crypto",**health(2,"OKX / Coinbase备用","WebSocket + REST fallback","交易所公开流")},
        {"name":"News","status":"CONNECTED" if any(x.get("status")=="CONNECTED" for x in providers) else "STALE" if any(x.get("status")=="STALE" for x in providers) else "DEGRADED","mode":"多源采集 + SQLite缓存","source":"independent public providers","last_update":max((x.get("last_check") or "" for x in providers),default=""),"details":providers},
        {"name":"AI","status":"CONNECTED","mode":"本地模型","source":"scikit-learn ensemble / optional boosters","last_update":now},
    ]
    return {"success":True,"data":{"items":items,"checked_at":now,"database":"SQLite user data directory","notice":"连接状态表示服务链路可用，不代表每个外部源在所有网络环境都无延迟。"}}


def parse_strategy_text(text: str) -> dict:
    normalized=text.upper().replace("＜","<").replace("＞",">")
    threshold=30.0
    found=re.search(r"RSI\s*(?:低于|小于|<)\s*(\d+(?:\.\d+)?)",normalized,re.I)
    if found:threshold=float(found.group(1))
    hold=5
    found=re.search(r"(?:持有|HOLD)\s*(\d+)\s*(?:天|DAY|D)",normalized,re.I)
    if found:hold=int(found.group(1))
    if "RSI" in normalized:
        return {"status":"PARSED","entry":{"indicator":"RSI(14)","operator":"<","value":threshold},"action":"BUY","exit":{"type":"HOLD_BARS","bars":hold},"strategy":"rsi_hold","interval":"1d","causality":"signal at close T; execution at open T+1","unsupported":[]}
    if "MACD" in normalized:
        return {"status":"PARSED","entry":{"indicator":"MACD","operator":"CROSS_ABOVE","value":"SIGNAL"},"action":"BUY","exit":{"type":"CROSS_BELOW"},"strategy":"macd","interval":"1d","causality":"signal at close T; execution at open T+1","unsupported":[]}
    if "均线" in text or "MA" in normalized:
        return {"status":"PARSED","entry":{"indicator":"MA5","operator":"ABOVE","value":"MA20"},"action":"BUY","exit":{"type":"CROSS_BELOW"},"strategy":"ma","interval":"1d","causality":"signal at close T; execution at open T+1","unsupported":[]}
    return {"status":"UNSUPPORTED","strategy":None,"unsupported":["当前仅支持 RSI阈值+持有期、MACD交叉、MA5/MA20 规则"],"message":"无法安全转换为可执行规则；未启动回测。"}


@router.post("/strategy/parse")
def strategy_parse(body: StrategyParseRequest) -> dict:
    return {"success":True,"data":parse_strategy_text(body.text)}


def _natural_backtest(candles: list[dict], rule: dict, initial: float, fee: float, slippage: float) -> dict:
    frame=calculate_indicators(candles)
    if len(frame)<80: raise ValueError("回测至少需要 80 根真实 K线")
    threshold=float(rule["entry"].get("value") or 30);hold=int(rule["exit"].get("bars") or 5)
    cash=float(initial);quantity=0.0;entry_cost=0.0;held=0;trades=[];curve=[];benchmark=[];drawdowns=[];peak=initial
    first=float(frame.iloc[0]["close"])
    signals=[False]+[bool(v<threshold) for v in frame["rsi"].iloc[:-1]]
    for (_,row),entry_signal in zip(frame.iterrows(),signals):
        open_price=float(row["open"]);close=float(row["close"])
        if not quantity and entry_signal:
            px=open_price*(1+slippage);quantity=cash/(px*(1+fee));gross=quantity*px;paid=gross*fee;cash-=gross+paid;entry_cost=gross+paid;held=0
            trades.append({"side":"BUY","timestamp":row["timestamp"],"price":px,"quantity":quantity,"fee":paid})
        elif quantity:
            held+=1
            if held>=hold:
                px=open_price*(1-slippage);gross=quantity*px;paid=gross*fee;cash+=gross-paid;pnl=cash-entry_cost
                trades.append({"side":"SELL","timestamp":row["timestamp"],"price":px,"quantity":quantity,"fee":paid,"pnl":pnl});quantity=0;entry_cost=0
        equity=cash+quantity*close;peak=max(peak,equity);dd=(peak-equity)/peak if peak else 0
        curve.append({"timestamp":row["timestamp"],"equity":round(equity,2)});drawdowns.append({"timestamp":row["timestamp"],"drawdown":round(-dd*100,4)})
        benchmark.append({"timestamp":row["timestamp"],"equity":round(initial*close/first,2)})
    if quantity:
        px=float(frame.iloc[-1]["close"])*(1-slippage);gross=quantity*px;paid=gross*fee;cash+=gross-paid
        trades.append({"side":"SELL","timestamp":frame.iloc[-1]["timestamp"],"price":px,"quantity":quantity,"fee":paid,"pnl":cash-entry_cost});curve[-1]["equity"]=round(cash,2)
    closed=[x for x in trades if x["side"]=="SELL"];profits=[x["pnl"] for x in closed if x["pnl"]>0];losses=[x["pnl"] for x in closed if x["pnl"]<=0]
    values=np.asarray([x["equity"] for x in curve]);returns=np.diff(values)/np.maximum(values[:-1],1e-12)
    sharpe=float(np.sqrt(252)*returns.mean()/returns.std(ddof=1)) if len(returns)>1 and returns.std(ddof=1)>0 else 0
    elapsed=max(1,(pd.Timestamp(frame.iloc[-1]["timestamp"])-pd.Timestamp(frame.iloc[0]["timestamp"])).days);years=max(elapsed/365.25,1/365.25)
    ret=(cash/initial-1)*100;bench=(float(frame.iloc[-1]["close"])/first-1)*100;max_dd=abs(min((x["drawdown"] for x in drawdowns),default=0))
    return {"strategy":"rsi_hold","parsed_rule":rule,"initial_cash":initial,"final_cash":round(cash,2),"return_percent":round(ret,2),"net_return_percent":round(ret,2),
            "annualized_return_percent":round(((cash/initial)**(1/years)-1)*100,2) if cash>0 else -100,"benchmark_return_percent":round(bench,2),"excess_return_percent":round(ret-bench,2),
            "max_drawdown_percent":round(max_dd,2),"win_rate_percent":round(len(profits)/len(closed)*100,2) if closed else 0,
            "profit_factor":round(sum(profits)/abs(sum(losses)),3) if losses else (999 if profits else None),"profit_loss_ratio":round((sum(profits)/len(profits))/(abs(sum(losses))/len(losses)),3) if profits and losses else None,
            "sharpe_ratio":round(sharpe,3),"trade_count":len(closed),"equity_curve":curve,"benchmark_curve":benchmark,"drawdown_curve":drawdowns,"trades":trades,
            "data_start":frame.iloc[0]["timestamp"],"data_end":frame.iloc[-1]["timestamp"],"execution_timing":"signal at close T, execution at open T+1","notice":"真实历史K线回测，含手续费和滑点；结果不代表未来收益。"}


@router.post("/strategy/natural-backtest")
async def natural_backtest(body: NaturalBacktestRequest) -> dict:
    rule=parse_strategy_text(body.text)
    if rule["status"]!="PARSED": raise HTTPException(422,rule["message"])
    if rule["strategy"]!="rsi_hold": raise HTTPException(422,"该规则可解析，但请使用标准策略回测执行")
    symbol=canonical_symbol(body.symbol,body.asset_type)
    candles,source=await (crypto_kline(symbol,"1d",1200) if body.asset_type=="crypto" else stock_kline(symbol,"1d",1200))
    result=await asyncio.to_thread(_natural_backtest,candles,rule,body.initial_cash,body.fee_rate,body.slippage_rate)
    result.update({"symbol":symbol,"asset_type":body.asset_type,"interval":"1d","data_source":source})
    return {"success":True,"data":result,"source":source}


async def _copilot_analysis(symbol: str, asset_type: str) -> dict:
    meta=next((x for x in ASSETS if x["symbol"]==symbol),{"symbol":symbol,"name":symbol,"asset_type":asset_type,"market":"Crypto" if asset_type=="crypto" else "美股","industry":"未知"})
    row=await analyze_asset(meta)
    evidence=[x["label"] for x in row["factors"]]
    answer=(f"{row['symbol']} 最新公开行情价 {row['price']:.4f} {row.get('currency','')}，日变动 {row.get('change_percent',0):+.2f}%。"
            f"AI Score {row['ai_score']}/100，观点{row['direction']}。依据：{'；'.join(evidence)}。"
            f"风险：{'；'.join(row['risks'])}。数据截止 {row.get('updated_at')}。")
    return {"answer":answer,"rows":[row],"tool_calls":[{"tool":"market.quote","status":"SUCCESS","source":row.get("source")},{"tool":"market.kline_indicators","status":"SUCCESS","source":row.get("kline_source")},{"tool":"news.lookup","status":"SUCCESS","records":len(row.get("news",[]))}],"data_cutoff":row.get("updated_at")}


@router.post("/copilot")
async def copilot(body: CopilotRequest) -> dict:
    text=body.message.strip(); upper=text.upper()
    symbols=re.findall(r"\b(?:NVDA|AMD|AAPL|TSLA|MSFT|BTC|ETH|SOL|600519|300750)\b",upper)
    if any(word in text for word in ("筛选","找出","值得关注","最强")):
        minimum=70 if re.search(r"(?:>|大于|高于)\s*70",text) else 0
        result=await scan_assets(ScannerRequest(min_ai_score=minimum))
        top=result["rows"][:5]
        answer="筛选完成："+("；".join(f"{x['symbol']} {x['ai_score']}/100 {x['direction']} 风险{x['components']['risk']}" for x in top) if top else "当前真实数据下没有符合条件的标的。")
        return {"success":True,"data":{"answer":answer,"rows":top,"tool_calls":[{"tool":"terminal.scanner","status":"SUCCESS","available":result["available"]}],"data_cutoff":result["generated_at"]}}
    if len(symbols)>=2 or "比较" in text:
        if len(symbols)<2: raise HTTPException(422,"请明确输入两个支持的标的，例如“比较 NVDA 和 AMD”")
        rows=await asyncio.gather(*(_copilot_analysis(s,"crypto" if s in {"BTC","ETH","SOL"} else "stock") for s in symbols[:2]))
        a,b=rows[0]["rows"][0],rows[1]["rows"][0]
        answer=f"{a['symbol']} AI Score {a['ai_score']}、风险 {a['components']['risk']}；{b['symbol']} AI Score {b['ai_score']}、风险 {b['components']['risk']}。当前综合信号更强的是 {a['symbol'] if a['ai_score']>=b['ai_score'] else b['symbol']}，但评分不是收益保证。"
        return {"success":True,"data":{"answer":answer,"rows":[a,b],"tool_calls":[call for x in rows for call in x["tool_calls"]],"data_cutoff":max(a.get("updated_at") or "",b.get("updated_at") or "")}}
    symbol=symbols[0] if symbols else "BTC" if "币" in text else "NVDA"
    asset_type="crypto" if symbol in {"BTC","ETH","SOL"} else "stock"
    return {"success":True,"data":await _copilot_analysis(symbol,asset_type)}
