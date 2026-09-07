"""Real news collection, explainable analysis and point-in-time backtesting."""
from __future__ import annotations

import asyncio, hashlib, html, math, re, time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree as ET
import httpx

HEADERS={"User-Agent":"Mozilla/5.0 AI-Market-Assistant/1.7","Accept":"application/json, application/rss+xml, application/xml, */*"}
ANALYSIS_VERSION="financial-event-rules-v2"

def now_utc(): return datetime.now(timezone.utc).isoformat()
def _published(value:Any):
    if value in (None,""): return None
    if isinstance(value,(int,float)) or str(value).isdigit():
        try:return datetime.fromtimestamp(float(value),timezone.utc).isoformat()
        except (ValueError,OSError,OverflowError):return None
    text=str(value).strip()
    try:return parsedate_to_datetime(text).astimezone(timezone.utc).isoformat()
    except (TypeError,ValueError,OverflowError):
        try:
            out=datetime.fromisoformat(text.replace("Z","+00:00"));return (out.replace(tzinfo=timezone.utc) if out.tzinfo is None else out.astimezone(timezone.utc)).isoformat()
        except (TypeError,ValueError):return None
def _plain(value:Any,limit=400):return re.sub(r"\s+"," ",html.unescape(re.sub(r"<[^>]+>"," ",str(value or "")))).strip()[:limit]
def _identity(title,url):return hashlib.sha256(f"{title}|{url}".encode()).hexdigest()[:24]
def _valid(text):return bool(text.strip()) and text.count("�")<=max(1,len(text)//30)

@dataclass(slots=True)
class NewsQuery:
    symbol:str|None=None;name:str|None=None;sector:str|None=None;keyword:str|None=None;market:str|None=None;limit:int=30;page:int=1

class NewsProvider(ABC):
    provider_type="NewsProvider";markets=("全球",)
    @abstractmethod
    async def fetch_latest_news(self,q:NewsQuery)->list[dict[str,Any]]:...
    async def fetch_news_by_symbol(self,q):return await self.fetch_latest_news(q)
    async def fetch_news_by_sector(self,q):return await self.fetch_latest_news(q)
    async def fetch_news_by_keyword(self,q):return await self.fetch_latest_news(q)
    async def fetch_historical_news(self,q):return await self.fetch_latest_news(q)
    async def search_news(self,q):return await self.fetch_news_by_keyword(q)
    # Public contract aliases.
    async def fetchLatestNews(self,q):return await self.fetch_latest_news(q)
    async def fetchNewsBySymbol(self,q):return await self.fetch_news_by_symbol(q)
    async def fetchNewsBySector(self,q):return await self.fetch_news_by_sector(q)
    async def fetchNewsByKeyword(self,q):return await self.fetch_news_by_keyword(q)
    async def fetchHistoricalNews(self,q):return await self.fetch_historical_news(q)
    async def searchNews(self,q):return await self.search_news(q)

ENTITY_ALIASES={
 "600519":("600519","贵州茅台","茅台"),"300750":("300750","宁德时代"),"002594":("002594","比亚迪"),"000858":("000858","五粮液"),
 "NVDA":("nvda","nvidia","英伟达"),"AMD":("amd","advanced micro devices","超威"),"TSLA":("tsla","tesla","特斯拉"),
 "AAPL":("aapl","apple","苹果公司"),"MSFT":("msft","microsoft","微软"),"GOOGL":("googl","google","alphabet","谷歌"),
 "BTC":("btc","bitcoin","比特币"),"ETH":("eth","ethereum","以太坊"),"SOL":("solana",),"BNB":("bnb","binance coin")}

def _filter(rows,q):
    needle=(q.keyword or q.sector or "").strip().lower()
    if needle:rows=[x for x in rows if needle in f"{x.get('title','')} {x.get('summary','')} {' '.join(x.get('sectors',[]))}".lower()]
    if q.symbol:
        aliases=ENTITY_ALIASES.get(q.symbol.upper(),(q.symbol,q.name or ""));rows=[x for x in rows if q.symbol in x.get("symbols",[]) or any(a and a.lower() in f"{x.get('title','')} {x.get('summary','')}".lower() for a in aliases)]
    return rows

class RSSNewsProvider(NewsProvider):
    def __init__(self,name,url,market,scope="market",limit=30):self.provider_type=name;self.url=url;self.markets=(market,);self.scope=scope;self.limit=limit
    async def fetch_latest_news(self,q):
        async with httpx.AsyncClient(timeout=18,headers=HEADERS,follow_redirects=True) as c:r=await c.get(self.url);r.raise_for_status()
        root=ET.fromstring(r.content);rows=[]
        for n in root.findall("./channel/item")[:min(q.limit,self.limit)]:
            title,url=_plain(n.findtext("title"),240),_plain(n.findtext("link"),1000)
            if not title or not url or not _valid(title):continue
            sn=n.find("source");source=_plain(sn.text if sn is not None else self.provider_type,100)
            summary=_plain(n.findtext("description") or n.findtext("summary"),420)
            rows.append({"id":_identity(title,url),"title":title,"summary":summary or title,"url":url,"source":source or self.provider_type,"provider":self.provider_type,"scope":self.scope,"market":self.markets[0],"published_at":_published(n.findtext("pubDate") or n.findtext("published")),"collected_at":now_utc(),"symbols":[],"sectors":[]})
        return _filter(rows,q)

class EastmoneyAnnouncementProvider(NewsProvider):
    provider_type="EastmoneyAnnouncementProvider";markets=("A股",);endpoint="https://np-anotice-stock.eastmoney.com/api/security/ann"
    async def _fetch(self,q,historical=False):
        p={"sr":-1,"page_size":min(100,q.limit),"page_index":q.page,"ann_type":"A","client_source":"web"}
        if q.symbol and re.fullmatch(r"\d{6}",q.symbol):p["stock_list"]=q.symbol
        async with httpx.AsyncClient(timeout=18,headers={**HEADERS,"Referer":"https://data.eastmoney.com/"},follow_redirects=True) as c:r=await c.get(self.endpoint,params=p);r.raise_for_status();payload=r.json()
        rows=[]
        for x in (payload.get("data") or {}).get("list",[]) or []:
            title=_plain(x.get("title"),240);codes=[str(v.get("stock_code")) for v in x.get("codes",[]) if v.get("stock_code")]
            if not title or not _valid(title):continue
            art=str(x.get("art_code") or "");primary=q.symbol if q.symbol in codes else (codes[0] if codes else "")
            url=f"https://data.eastmoney.com/notices/detail/{primary}/{art}.html" if primary else "https://data.eastmoney.com/notices/"
            rows.append({"id":_identity(title,art or url),"title":title,"summary":title,"url":url,"source":"东方财富公告（交易所公告聚合）","provider":self.provider_type,"scope":"announcement","market":"A股","published_at":_published(x.get("notice_date")),"collected_at":now_utc(),"symbols":codes,"sectors":[],"historical":historical})
        return _filter(rows,q)
    async def fetch_latest_news(self,q):return await self._fetch(q)
    async def fetch_news_by_symbol(self,q):return await self._fetch(q)
    async def fetch_historical_news(self,q):return await self._fetch(q,True)

RSS_PROVIDERS=(
 RSSNewsProvider("CoinDeskProvider","https://www.coindesk.com/arc/outboundfeeds/rss/","加密货币"),
 RSSNewsProvider("CointelegraphProvider","https://cointelegraph.com/rss","加密货币"),
 RSSNewsProvider("CNBCMarketsProvider","https://www.cnbc.com/id/10000664/device/rss/rss.html","美股"),
 RSSNewsProvider("BBCBusinessProvider","https://feeds.bbci.co.uk/news/business/rss.xml","全球","macro"),
 RSSNewsProvider("YahooFinanceProvider","https://finance.yahoo.com/news/rssindex","美股"))

def providers_for(q,historical=False):
    if historical:return [EastmoneyAnnouncementProvider()] if q.symbol and re.fullmatch(r"\d{6}",q.symbol) else []
    out=[EastmoneyAnnouncementProvider()]
    for p in RSS_PROVIDERS:
        if q.market and q.market not in ("全部","全球") and q.market not in p.markets:continue
        if q.symbol:
            crypto=not re.fullmatch(r"\d{6}",q.symbol)
            if crypto != ("加密货币" in p.markets):continue
        out.append(p)
    return out

def _dedupe(rows):
    groups=[]
    for item in sorted(rows,key=lambda x:x.get("published_at") or "",reverse=True):
        norm=re.sub(r"[^\w\u4e00-\u9fff]+","",re.sub(r"\s*[-|]\s*[^-|]{2,30}$","",item["title"].lower()));match=None
        for old in groups:
            if SequenceMatcher(None,norm,old["_norm"]).ratio()>=.86 or (norm and (norm in old["_norm"] or old["_norm"] in norm)):match=old;break
        ref={"source":item.get("source"),"url":item.get("url"),"published_at":item.get("published_at")}
        if match:
            if ref not in match["related_sources"]:match["related_sources"].append(ref)
            match["symbols"]=sorted(set(match.get("symbols",[]))|set(item.get("symbols",[])))
        else:
            item=dict(item);item["_norm"]=norm;item["related_sources"]=[ref];groups.append(item)
    for x in groups:x.pop("_norm",None);x["related_source_count"]=len(x["related_sources"])
    return groups

async def _collect(q,historical=False):
    ps=providers_for(q,historical);started=time.perf_counter();calls=[p.fetch_historical_news(q) if historical else (p.fetch_news_by_symbol(q) if q.symbol else p.fetch_latest_news(q)) for p in ps]
    results=await asyncio.gather(*calls,return_exceptions=True);rows=[];status=[]
    for p,r in zip(ps,results):
        if isinstance(r,BaseException):status.append({"provider":p.provider_type,"status":"ERROR","count":0,"latency_ms":round((time.perf_counter()-started)*1000),"error":type(r).__name__,"markets":p.markets})
        else:rows.extend(r);status.append({"provider":p.provider_type,"status":"HEALTHY","count":len(r),"latency_ms":round((time.perf_counter()-started)*1000),"error":None,"markets":p.markets})
    return _dedupe(rows),status
async def collect_news(symbol=None,name=None,market=None,keyword=None,limit=30):return await _collect(NewsQuery(symbol,name,keyword=keyword,market=market,limit=limit))
async def collect_historical_news(symbol,name=None,limit=100,pages=3):
    rows=[];statuses=[]
    for page in range(1,pages+1):
        got,health=await _collect(NewsQuery(symbol=symbol,name=name,limit=min(100,limit),page=page),True);rows+=got;statuses+=health
        if len(got)<min(100,limit):break
    return _dedupe(rows),statuses

SECTOR_RULES={"半导体":("芯片","半导体","semiconductor","gpu","晶圆"),"AI算力":("人工智能"," ai ","artificial intelligence","算力","服务器","data center"),"新能源":("锂电","电池","光伏","风电","electric vehicle"),"消费":("白酒","消费","零售"),"金融":("银行","券商","保险","利率","bank"),"数字资产":("比特币","btc","bitcoin","以太坊","eth","ethereum","加密","crypto"),"黄金":("黄金","gold"),"原油":("原油","oil","opec")}
CATEGORY_RULES={"财报":("财报","业绩","earnings","revenue","profit"),"公告":("公告","回购","增持","减持","分红","停牌"),"政策":("政策","监管","法案","禁令","regulation","tariff"),"宏观":("美联储","降息","加息","cpi","gdp","非农","inflation"),"行业":("行业","产业","供需","芯片","半导体"),"地缘政治":("战争","冲突","制裁","war","sanction")}
POSITIVE={"大增":32,"超预期":30,"获批":28,"回购":23,"增持":20,"重大合同":23,"突破":18,"增长":14,"上涨":12,"降息":16,"创新高":18,"改善":12,"利好":18,"beats":28,"surge":22,"rally":16,"approval":20,"record high":18}
NEGATIVE={"暴跌":-35,"处罚":-30,"调查":-25,"违约":-35,"爆雷":-38,"亏损":-22,"减持":-18,"下调":-16,"下跌":-12,"加息":-16,"限制":-20,"风险":-12,"召回":-22,"misses":-28,"plunge":-30,"lawsuit":-22,"ban":-25}

class EventExtractionEngine:
    method=f"{ANALYSIS_VERSION} deterministic rules (not FinBERT/LLM)"
    def analyze(self,item,symbol=None,name=None):
        if item.get("analysis_version")==ANALYSIS_VERSION and item.get("event"):return item
        title=_plain(item.get("title"),240);summary=_plain(item.get("summary") or item.get("raw_summary") or title,420);text=f" {title} {summary} ".lower()
        contrib=[(w,s) for w,s in {**POSITIVE,**NEGATIVE}.items() if w in text];score=max(-100,min(100,sum(s for _,s in contrib)))
        category=next((c for c,ws in CATEGORY_RULES.items() if any(w in text for w in ws)),"市场")
        sectors=sorted(set(item.get("sectors",[]))|{s for s,ws in SECTOR_RULES.items() if any(w in text for w in ws)})
        symbols={str(x).upper() for x in item.get("symbols",[]) if x}
        for code,aliases in ENTITY_ALIASES.items():
            if any(a.lower() in text for a in aliases if a):symbols.add(code)
        if symbol:
            aliases=ENTITY_ALIASES.get(symbol.upper(),(symbol,name or ""))
            if symbol in item.get("symbols",[]) or any(a and a.lower() in text for a in aliases):symbols.add(symbol.upper())
        symbols=sorted(symbols);direction="强利好" if score>=45 else "利好" if score>=10 else "强利空" if score<=-45 else "利空" if score<=-10 else "中性";label="bullish" if score>=10 else "bearish" if score<=-10 else "neutral"
        event_type=contrib[0][0] if contrib else next((w for ws in CATEGORY_RULES.values() for w in ws if w in text),"一般资讯");confidence=min(.95,.45+.08*len(contrib)+(.1 if item.get("published_at") else 0)+(.08 if symbols else 0));magnitude=min(5,max(1,math.ceil(abs(score)/20))) if score else 1
        reasons=[f"识别到方向词“{w}”（权重 {s:+d}）" for w,s in contrib]
        if symbols:reasons.append(f"标题、摘要或公告元数据明确提及：{'、'.join(symbols)}")
        if sectors:reasons.append(f"行业关键词映射到：{'、'.join(sectors)}")
        if not reasons:reasons=["未识别到足以判断方向的明确事件词，因此保持中性"]
        direct=[{"target":x,"direction":direction,"score":abs(score),"reason":"新闻明确提及该标的"} for x in symbols];indirect=[{"target":x,"direction":direction if score else "中性","score":max(5,abs(score)-10),"reason":f"事件与{x}产业链相关"} for x in sectors];risk=[]
        if score>=20:risk=[{"target":"高估值/近期涨幅较大标的","direction":"潜在利空","reason":"正面信息可能已被提前定价，存在利好兑现风险"}]
        if score<=-20:risk=[{"target":"替代供应商或避险资产","direction":"潜在利好","reason":"负面冲击可能带来替代或避险需求"}]
        impact=min(100,round(abs(score)*.58+magnitude*7+len(symbols)*5+len(sectors)*4+(6 if item.get("scope")=="macro" else 0)))
        return {**item,"summary":summary,"one_sentence_summary":summary or title,"category":category,"analysis_version":ANALYSIS_VERSION,"analysis_status":"RULE_ENGINE_ANALYZED","symbols":symbols,"sectors":sectors,"reason":reasons,"event":{"subject":symbols[0] if symbols else (sectors[0] if sectors else "市场"),"event_type":event_type,"event_time":item.get("published_at"),"direction":direction,"sentiment":label,"affected_objects":symbols,"affected_symbols":symbols,"affected_sectors":sectors,"magnitude":magnitude,"confidence":round(confidence,2)},"sentiment":{"score":score,"direction":direction,"label":label,"method":self.method,"evidence":[{"keyword":w,"weight":s} for w,s in contrib]},"impact":{"score":impact,"level":"极高" if impact>=80 else "高" if impact>=60 else "中" if impact>=35 else "低","primary":direct,"secondary":indirect,"counter":risk,"method":"deterministic entity and causal mapping; requires human review"}}

class TradingDecisionEngine:
    def decide(self,news_score,technical_score=None,volume_ratio=None,sample_count=0):
        tech=0 if technical_score is None else (technical_score-50)*.6;volume=0 if volume_ratio is None else max(-10,min(10,(volume_ratio-1)*10));composite=max(-100,min(100,news_score*.45+tech+volume));overbought=technical_score is not None and technical_score>=75
        buy=round(max(0,min(100,50+composite*.65)));avoid=round(max(0,min(100,50-composite*.65)));hold=max(0,100-max(buy,avoid));total=max(1,buy+hold+avoid);scores={"buy":round(buy/total*100),"hold":round(hold/total*100),"avoid":round(avoid/total*100)}
        view,advice=("利好但不建议追高","等待回撤或技术面再次确认。") if composite>=25 and overbought else (("偏多","关注，不追高；等待成交量与趋势确认。") if composite>=25 else (("偏空","短期风险较高，优先控制风险。") if composite<=-25 else ("观望","暂无明确优势。")))
        grade="A" if sample_count>=100 and abs(composite)>=40 else "B" if sample_count>=30 else "C" if sample_count>=10 else "D"
        return {"scores":scores,"view":view,"advice":advice,"composite_evidence_score":round(composite,2),"confidence_grade":grade,"historical_samples":sample_count,"model_historical_accuracy":None,"inputs":{"news_score":news_score,"technical_score":technical_score,"volume_ratio":volume_ratio},"why_not_buy":[x for x in ["技术评分处于过热区，当前不建议追高" if overbought else None,"新闻方向不明确" if abs(news_score)<10 else None,"缺少成交量确认" if volume_ratio is None or volume_ratio<1 else None] if x],"notice":"证据融合分数不是已校准上涨概率；历史准确率仅在真实样本结算后展示。"}

def prediction_horizons(composite,sample_count):
    out={}
    for h,d in (("T+1",1),("T+3",.78),("T+5",.62)):
        edge=max(-30,min(30,composite*d*.3));up=33.3+edge;down=33.3-edge;out[h]={"up":round(up,1),"flat":round(100-up-down,1),"down":round(down,1),"type":"uncalibrated_evidence_estimate","validated_samples":sample_count}
    return out

def build_intelligence(items,symbol=None,name=None,technical_score=None,volume_ratio=None,sample_count=0):
    analyzed=[EventExtractionEngine().analyze(x,symbol,name) for x in items if _valid(str(x.get("title") or ""))];analyzed.sort(key=lambda x:(x["impact"]["score"],x.get("published_at") or ""),reverse=True);scores=[x["sentiment"]["score"] for x in analyzed];market=round(sum(scores)/len(scores),1) if scores else 0;positive=sum(x>=10 for x in scores);negative=sum(x<=-10 for x in scores);sectors={}
    for item in analyzed:
        for sector in item["sectors"]:
            b=sectors.setdefault(sector,{"positive":0,"negative":0,"neutral":0,"score":0});key="positive" if item["sentiment"]["score"]>=10 else "negative" if item["sentiment"]["score"]<=-10 else "neutral";b[key]+=1;b["score"]+=item["sentiment"]["score"]
    decision=TradingDecisionEngine().decide(market,technical_score,volume_ratio,sample_count)
    return {"status":"AVAILABLE" if analyzed else "NO_DATA","generated_at":now_utc(),"method":EventExtractionEngine.method,"radar":{"market_sentiment":market,"positive":positive,"negative":negative,"neutral":len(scores)-positive-negative,"major":sum(x["impact"]["score"]>=55 for x in analyzed)},"top_news":analyzed[:10],"all_news":analyzed,"sector_impact":sectors,"watch_list":[x for x in analyzed if x["sentiment"]["score"]>=20][:8],"risk_list":[x for x in analyzed if x["sentiment"]["score"]<=-20][:8],"historical_similar_events":[],"decision":decision,"predictions":prediction_horizons(decision["composite_evidence_score"],sample_count),"point_in_time":"Only immutable publication time and information available then are eligible; execution uses first later trading bar."}

def _dt(v):
    out=datetime.fromisoformat(str(v).replace("Z","+00:00"));return out.replace(tzinfo=timezone.utc) if out.tzinfo is None else out.astimezone(timezone.utc)
def event_backtest(events,candles,event_type=None,direction="all",min_impact=0,min_confidence=0,selected_horizon=5):
    usable=[];wanted=direction.lower()
    for x in events:
        label=str(x.get("sentiment",{}).get("label") or "neutral").lower()
        if not x.get("published_at") or (event_type and x.get("event",{}).get("event_type")!=event_type):continue
        if wanted not in ("all","全部") and label!=wanted:continue
        if float(x.get("impact",{}).get("score") or 0)<min_impact or float(x.get("event",{}).get("confidence") or 0)<min_confidence:continue
        usable.append(x)
    bars=sorted(candles,key=lambda x:x["timestamp"]);times=[_dt(x["timestamp"]) for x in bars];horizons=(1,3,5,10,20);outcomes=[]
    for item in usable:
        event_time=_dt(item["published_at"]);index=next((i for i,t in enumerate(times) if t>event_time),None)
        if index is None:continue
        entry=float(bars[index]["open"]);row={"news_id":item["id"],"title":item.get("title"),"direction":item.get("sentiment",{}).get("label","neutral"),"event_time":item["published_at"],"entry_time":bars[index]["timestamp"],"entry_price":entry,"returns":{}}
        for h in horizons:
            ix=index+h-1
            if ix<len(bars):value=float(bars[ix]["close"])/entry-1;row["returns"][f"T+{h}"]=value;row[f"t{h}_return"]=value
        if f"T+{selected_horizon}" in row["returns"]:outcomes.append(row)
    metrics={}
    for h in horizons:
        pts=[(x["returns"].get(f"T+{h}"),x["direction"]) for x in outcomes];pts=[x for x in pts if x[0] is not None]
        if not pts:continue
        raw=[x[0] for x in pts];directional=[-v if d=="bearish" else v for v,d in pts if d!="neutral"];wins=[v for v in directional if v>0];losses=[v for v in directional if v<0]
        metrics[f"T+{h}"]={"samples":len(pts),"directional_samples":len(directional),"win_rate":round(len(wins)/len(directional),4) if directional else None,"average_return":round(sum(raw)/len(raw),6),"max_return":round(max(raw),6),"min_return":round(min(raw),6),"profit_loss_ratio":round((sum(wins)/len(wins))/abs(sum(losses)/len(losses)),4) if wins and losses else None}
    chosen=metrics.get(f"T+{selected_horizon}",{});curve=[]
    for row in sorted(outcomes,key=lambda x:x["event_time"]):
        v=row["returns"][f"T+{selected_horizon}"];curve.append(-v if row["direction"]=="bearish" else v) if row["direction"]!="neutral" else None
    equity=peak=1.;draw=0.
    for v in curve:equity*=1+v;peak=max(peak,equity);draw=min(draw,equity/peak-1)
    result={"status":"AVAILABLE" if len(outcomes)>=10 else "DATA_INSUFFICIENT","samples":len(outcomes),"minimum_samples":10,"selected_horizon":f"T+{selected_horizon}","metrics":metrics,"win_rate":chosen.get("win_rate"),"average_return":chosen.get("average_return"),"max_return":chosen.get("max_return"),"min_return":chosen.get("min_return"),"profit_loss_ratio":chosen.get("profit_loss_ratio"),"max_drawdown":round(draw,6),"causality":"publication timestamp; first strictly later trading-bar open; T+N uses observed trading bars","outcomes":outcomes}
    if len(outcomes)<10:result["notice"]="历史新闻数据不足，无法进行可靠回测。小样本结果仅用于审计。"
    return result
