<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";
import {
  DataAnalysis,
  Bell,
  HomeFilled,
  Refresh,
  Search,
  Setting,
  Star,
  TrendCharts,
  Wallet,
} from "@element-plus/icons-vue";
import { ElMessage } from "element-plus";
import KlineChart from "./KlineChart.vue";
import EquityChart from "./EquityChart.vue";
import {
  assetLabel,
  post,
  request,
  type Asset,
  type Candle,
  type IndicatorSet,
  type Quote,
} from "./api";
import { realtimeMarketStore, type RealtimeEvent } from "./realtime";

type Page = "home" | "market" | "detail" | "news" | "prediction" | "strategy" | "paper" | "watchlist" | "settings";
const page = ref<Page>("home"),
  items = ref<Asset[]>([]),
  appVersion = ref("0.3.0"),
  loading = ref(false),
  error = ref(""),
  lastUpdate = ref("");
const query = ref(""),
  searching = ref(false),
  searchError = ref(""),
  searchResults = ref<Asset[]>([]),
  searchOpen = ref(false);
const selected = ref<Asset | null>(null),
  quote = ref<Quote | null>(null),
  candles = ref<Candle[]>([]),
  indicators = ref<IndicatorSet | null>(null),
  interval = ref("1h"),
  detailLoading = ref(false),
  detailError = ref("");
const aiLoading = ref(false),
  aiResult = ref<any>(null),
  aiError=ref(""),
  livePredictionHistory = ref<any[]>([]),
  backtestLoading = ref(false),
  backtestResult = ref<any>(null),
  strategyLeaderboard = ref<any[]>([]),
  strategy = ref("ma"),
  initialCash = ref(10000);
const marketContext = ref<any>(null),
  predictionStats = ref<any>(null),
  portfolioRisk = ref<any>(null),
  accountEquity = ref(100000),
  maxRiskPercent = ref(1),
  leverage = ref(1);
const newsIntelligence = ref<any>(null),
  newsLoading = ref(false),
  newsError = ref(""),
  newsBacktest = ref<any>(null), newsSelected=ref<any>(null), newsDialogOpen=ref(false),
  newsMarket=ref("全部"),newsCategory=ref("全部"),newsDirection=ref("全部"),newsHours=ref(168),
  newsKeyword=ref(""),newsPage=ref(1),newsBacktestDirection=ref("bullish"),
  newsBacktestImpact=ref(70),newsBacktestConfidence=ref(60),newsBacktestHorizon=ref(5);
const orderAmount = ref(1000),
  orderLoading = ref(false),
  orderQuantity=ref(1),orderType=ref("MARKET"),orderLimitPrice=ref<number|null>(null),
  watchlist = ref<any[]>([]),
  paperAccounts = ref<any[]>([]),
  positions = ref<any[]>([]),
  orders = ref<any[]>([]),
  paperLoading = ref(false);
let paperTimer:number|null=null;
const updateChecking = ref(false),
  updateStatus = ref("启动时会自动检查更新；也可以在这里手动检查。");
const cryptos = computed(() =>
    items.value.filter((x) => x.asset_type === "crypto"),
  ),
  stocks = computed(() => items.value.filter((x) => x.asset_type !== "crypto"));
const inWatchlist = computed(
  () =>
    selected.value &&
    watchlist.value.some(
      (x) =>
        x.symbol === selected.value?.symbol &&
        x.asset_type === selected.value?.asset_type,
    ),
);
const periods = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];
const selectedLiveState = computed(() => realtimeMarketStore.states[selectedRealtimeKey()] || {});
const predictionRows=computed(()=>Object.entries(aiResult.value?.predictions||{}).map(([h,p]:any)=>({horizon:h==='1D'?'T+1':h,...p})));
const liveStatus = computed(() => selectedLiveState.value.connectionStatus || realtimeMarketStore.connectionStatus.value);
const v5BacktestStrategies=["breakout","pullback","moving_average","bollinger","rsi_reversal","fibonacci","bos","fvg","fib_fvg_bos"];
function price(value: number | null | undefined, currency = "") {
  if (value == null) return "—";
  return `${currency === "CNY" ? "¥" : "$"}${value.toLocaleString("zh-CN", { maximumFractionDigits: value < 10 ? 4 : 2 })}`;
}
function compact(value: number | null | undefined) {
  if (value == null) return "—";
  return Intl.NumberFormat("zh-CN", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(value);
}
function trendClass(value: number | null | undefined) {
  return (value || 0) >= 0 ? "positive" : "negative";
}
function probability(value: number | null | undefined) {
  return `${((value || 0) * 100).toFixed(1)}%`;
}
function availabilityLabel(status: any) {
  return status?.available
    ? "可用"
    : status?.applicable === false
      ? "不适用"
      : "暂无数据";
}
const strategyNames:Record<string,string>={trend:'趋势',breakout:'突破',pullback:'回撤',reversal:'反转',range:'区间',moving_average:'移动平均',bollinger:'布林带',rsi_breakout:'RSI突破',rsi_reversal:'RSI反转',macd:'MACD',fibonacci:'Fibonacci',gann:'Gann',stochastic:'随机指标',psar:'PSAR',momentum:'动量',mfi:'MFI',double_top_bottom:'双顶/双底',head_shoulders:'头肩形态',triangle:'三角形',donchian:'Donchian',wedge:'楔形',flag:'旗形',order_flow:'Order Flow',atr:'ATR',options:'期权',ict_smc:'ICT/SMC',fvg:'FVG',bos:'BOS',choch:'CHoCH',fib_fvg_bos:'Fib+FVG+BOS'};
function strategyLabel(key:string){return strategyNames[key]||key}
function signalClass(signal:string){return signal==='BUY'?'positive':signal==='SELL'?'negative':'neutral'}
function rotationSymbols(items: any[]) {
  return (items || [])
    .slice(0, 3)
    .map((item: any) => item.symbol)
    .join(" → ");
}
async function loadHome() {
  loading.value = true;
  error.value = "";
  try {
    const [overview, health, context] = await Promise.all([
      fetch("/api/market/overview").then((r) => r.json()),
      fetch("/api/health").then((r) => r.json()),
      request<any>("/api/ai/market-context").catch(() => null),
    ]);
    items.value = overview.items || [];
    if(!items.value.some((item)=>item.asset_type==="crypto"&&item.symbol==="BTC"))
      items.value.unshift({symbol:"BTC",name:"比特币",asset_type:"crypto",source:"实时订阅中"});
    items.value.forEach((item)=>realtimeMarketStore.subscribe(item.asset_type,item.symbol,item.asset_type==="crypto"?"1m":"1d"));
    appVersion.value = health.version || appVersion.value;
    marketContext.value = context;
    lastUpdate.value = new Date().toLocaleTimeString("zh-CN");
    await loadWatchlist();
    void loadNews();
  } catch (e) {
    error.value = e instanceof Error ? e.message : "行情数据获取失败";
  } finally {
    loading.value = false;
  }
}
async function searchAssets() {
  const q = query.value.trim();
  if (!q) return;
  searching.value = true;
  searchError.value = "";
  searchOpen.value = true;
  try {
    const [s, c] = await Promise.allSettled([
      request<Asset[]>(`/api/market/stock/search?q=${encodeURIComponent(q)}`),
      request<Asset[]>(`/api/market/crypto/search?q=${encodeURIComponent(q)}`),
    ]);
    searchResults.value = [
      ...(s.status === "fulfilled" ? s.value : []),
      ...(c.status === "fulfilled" ? c.value : []),
    ];
    if (!searchResults.value.length)
      searchError.value = "没有找到匹配资产，请检查名称或代码";
  } catch (e) {
    searchError.value = e instanceof Error ? e.message : "数据获取失败";
  } finally {
    searching.value = false;
  }
}
function selectSearchAsset(asset:Asset){
  if(page.value==='paper'){selected.value=asset;orderLimitPrice.value=asset.price||null;realtimeMarketStore.subscribe(asset.asset_type,asset.symbol,asset.asset_type==='crypto'?'1m':'1m');return}
  if(page.value==='prediction'){selected.value=asset;interval.value=asset.asset_type==='crypto'?'1h':'1d';aiResult.value=null;void Promise.all([loadQuote(),loadKline()]);return}
  if(page.value==='strategy'){selected.value=asset;interval.value=asset.asset_type==='crypto'?'1h':'1d';backtestResult.value=null;void loadKline();return}
  openAsset(asset)
}
async function openAsset(asset: Asset, action?: "ai" | "backtest", updateUrl=true) {
  selected.value = asset;
  page.value = "detail";
  if(updateUrl)history.pushState({},"",`/${asset.asset_type==='crypto'?'crypto':'stock'}/${encodeURIComponent(asset.symbol)}`);
  searchOpen.value = false;
  quote.value = null;
  candles.value = [];
  indicators.value = null;
  aiResult.value = null;
  backtestResult.value = null;
  interval.value = asset.asset_type === "crypto" ? "1h" : "1d";
  await Promise.all([loadQuote(), loadKline()]);
  realtimeMarketStore.subscribe(asset.asset_type, asset.symbol, interval.value);
  void loadNews(asset);
  if (action === "ai") await runAI();
  if (action === "backtest") await nextTick();
}

async function loadNews(asset?: Asset) {
  newsLoading.value = true;
  newsError.value = "";
  try {
    const target = asset || (page.value === "detail" ? selected.value || undefined : undefined);
    const queryParams=new URLSearchParams();
    if(target){queryParams.set('symbol',target.symbol);queryParams.set('asset_type',target.asset_type);queryParams.set('name',target.name)}
    if(!target){if(newsMarket.value!=='全部')queryParams.set('market',newsMarket.value);if(newsCategory.value!=='全部')queryParams.set('category',newsCategory.value);if(newsDirection.value!=='全部')queryParams.set('direction',newsDirection.value);if(newsHours.value)queryParams.set('hours',String(newsHours.value));if(newsKeyword.value.trim())queryParams.set('keyword',newsKeyword.value.trim());queryParams.set('page',String(newsPage.value));queryParams.set('page_size','20')}
    const result=await request<any>(`/api/news/intelligence?${queryParams}`);
    if(target && (page.value!=='detail'||selected.value?.symbol!==target.symbol))return;
    newsIntelligence.value = result;
  } catch (e) {
    newsError.value = e instanceof Error ? e.message : "新闻数据源暂不可用";
  } finally {
    newsLoading.value = false;
  }
}

async function showNews() {
  page.value = "news";
  newsPage.value=1;
  await loadNews();
}

function openNews(item:any){const outcome=(newsBacktest.value?.outcomes||[]).find((x:any)=>x.news_id===item.id);newsSelected.value=outcome?{...item,historical_outcome:outcome}:item;newsDialogOpen.value=true}
function assetFromSymbol(symbol:string):Asset{const crypto=['BTC','ETH','SOL','BNB'].includes(symbol);return {symbol,name:symbol,asset_type:crypto?'crypto':'stock'}}
function openNewsSymbol(symbol:string){newsDialogOpen.value=false;openAsset(assetFromSymbol(symbol))}
async function tradeNewsSymbol(symbol:string){newsDialogOpen.value=false;selected.value=assetFromSymbol(symbol);await showPaper()}
function newsClass(item:any){return item?.sentiment?.label==='bullish'?'positive':item?.sentiment?.label==='bearish'?'negative':'neutral'}
function stars(score:number){return '★'.repeat(Math.max(1,Math.ceil((score||0)/20)))+'☆'.repeat(Math.max(0,5-Math.ceil((score||0)/20)))}
async function applyNewsFilters(){newsPage.value=1;await loadNews()}
async function loadMoreNews(){if(!newsIntelligence?.value?.has_more)return;newsPage.value+=1;const old=[...(newsIntelligence.value.items||[])];await loadNews();newsIntelligence.value.items=[...old,...(newsIntelligence.value.items||[])];newsIntelligence.value.all_news=newsIntelligence.value.items}

async function runNewsBacktest() {
  if (!selected.value) return;
  newsBacktest.value = await post<any>("/api/news/backtest", {
    symbol: selected.value.symbol,
    asset_type: selected.value.asset_type,
    interval: interval.value,
    direction:newsBacktestDirection.value,min_impact:newsBacktestImpact.value,
    min_confidence:newsBacktestConfidence.value,horizon:newsBacktestHorizon.value,
  }).catch((e) => ({ status: "ERROR", notice: e instanceof Error ? e.message : "回测失败" }));
}
async function loadQuote() {
  if (!selected.value) return;
  try {
    quote.value = await request<Quote>(
      `/api/market/${selected.value.asset_type}/quote?symbol=${encodeURIComponent(selected.value.symbol)}`,
    );
  } catch (e) {
    detailError.value = e instanceof Error ? e.message : "行情数据获取失败";
  }
}
async function loadKline() {
  if (!selected.value) return;
  detailLoading.value = true;
  detailError.value = "";
  try {
    const data = await request<any>(
      `/api/market/${selected.value.asset_type}/kline?symbol=${encodeURIComponent(selected.value.symbol)}&interval=${interval.value}&limit=500`,
    );
    candles.value = data.candles;
    indicators.value = data.indicators;
  } catch (e) {
    detailError.value = e instanceof Error ? e.message : "K线数据获取失败";
  } finally {
    detailLoading.value = false;
  }
}
async function changeInterval(value: string) {
  interval.value = value;
  aiResult.value = null;
  await loadKline();
  if(selected.value) realtimeMarketStore.subscribe(selected.value.asset_type, selected.value.symbol, interval.value);
}
async function runAI(options?:{silent?:boolean;reasons?:string[]}) {
  if (!selected.value) return;
  aiLoading.value = true;
  aiError.value="";
  aiResult.value = null;
  try {
    aiResult.value = await post<any>("/api/ai/decision", {
      symbol: selected.value.symbol,
      asset_type: selected.value.asset_type,
      interval: interval.value,
      account_equity: accountEquity.value,
      max_risk_percent: maxRiskPercent.value / 100,
      leverage: leverage.value,
    });
    predictionStats.value = await request<any>("/api/ai/statistics").catch(
      () => null,
    );
    portfolioRisk.value = await request<any>("/api/ai/portfolio-risk").catch(
      () => null,
    );
    const primary:any=aiResult.value?.predictions?.["1H"] || Object.values(aiResult.value?.predictions||{})[0];
    livePredictionHistory.value.unshift({
      prediction_id: aiResult.value?.history?.saved?.prediction_id || aiResult.value?.history?.saved || `LIVE-${Date.now()}`,
      time: new Date().toISOString(), mode:"LIVE", reasons:options?.reasons||["MANUAL"],
      action:aiResult.value?.decision_center?.v5_final_decision?.action || aiResult.value?.decision_center?.decision?.action,
      probabilities:primary?.probabilities,
    });
    livePredictionHistory.value=livePredictionHistory.value.slice(0,20);
    if(!options?.silent) ElMessage.success("V7 实时因果策略与交易决策完成");
  } catch (e) {
    aiError.value=e instanceof Error ? e.message : "AI预测失败";ElMessage.error(aiError.value);
  } finally {
    aiLoading.value = false;
  }
}

function selectedRealtimeKey(){
  return selected.value ? realtimeMarketStore.key(selected.value.asset_type,selected.value.symbol,interval.value) : "";
}
function handleRealtime(event:RealtimeEvent){
  if(event.type==="ticker"&&event.data?.quote){
    const incoming=event.data.quote;
    const index=items.value.findIndex((item)=>item.symbol===incoming.symbol&&item.asset_type===incoming.asset_type);
    if(index>=0)items.value[index]={...items.value[index],...incoming};
    const held=positions.value.find((p:any)=>p.symbol===incoming.symbol&&p.asset_type===incoming.asset_type);
    if(held){held.current_price=incoming.price;held.market_value=held.quantity*incoming.price;held.unrealized_pnl=held.market_value-held.quantity*held.average_cost;held.return_percent=(incoming.price/held.average_cost-1)*100}
  }
  if(!selected.value || event.key!==selectedRealtimeKey())return;
  const state=event.type==="candle"?event.data?.state:event.data;
  if((event.type==="ticker"||event.type==="snapshot")&&state?.quote)quote.value=state.quote;
  if(event.type==="candle"&&state){
    if(state.quote)quote.value=state.quote;
    if(state.candles)candles.value=state.candles;
    if(state.indicators)indicators.value=state.indicators;
    if(state.strategy&&aiResult.value?.decision_center)aiResult.value.decision_center.technical_strategy=state.strategy;
  }
  if(event.type==="analysis"){
    indicators.value=event.data.indicators;
    if(aiResult.value?.decision_center)aiResult.value.decision_center.technical_strategy=event.data.strategy;
  }
  if(event.type==="prediction"&&event.data?.result?.data){
    aiResult.value=event.data.result.data;
    const primary:any=aiResult.value?.predictions?.["1H"] || Object.values(aiResult.value?.predictions||{})[0];
    livePredictionHistory.value.unshift({prediction_id:aiResult.value?.history?.saved?.prediction_id||`LIVE-${Date.now()}`,
      time:event.data.generatedAt,mode:"LIVE",reasons:event.data.reasons,
      action:aiResult.value?.decision_center?.v5_final_decision?.action||aiResult.value?.decision_center?.decision?.action,
      probabilities:primary?.probabilities});
    livePredictionHistory.value=livePredictionHistory.value.slice(0,20);
  }
}
async function runBacktest() {
  if (!selected.value) return;
  backtestLoading.value = true;
  backtestResult.value = null;
  try {
    const endpoint=v5BacktestStrategies.includes(strategy.value)?"/api/strategy/backtest":"/api/backtest/run";
    backtestResult.value = await post<any>(endpoint, {
      symbol: selected.value.symbol,
      asset_type: selected.value.asset_type,
      interval: interval.value,
      strategy: strategy.value,
      initial_cash: initialCash.value,
      limit: 1000,
      slippage_rate: 0.0005,
      walk_forward: true,
    });
    strategyLeaderboard.value = (await request<any>("/api/strategy/leaderboard").catch(()=>({rows:[]}))).rows || [];
    ElMessage.success("历史回测完成");
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "回测失败");
  } finally {
    backtestLoading.value = false;
  }
}
async function loadWatchlist() {
  const data = await request<any[]>("/api/watchlist");
  watchlist.value = data;
}
async function toggleWatch() {
  if (!selected.value) return;
  try {
    if (inWatchlist.value)
      await request(`/api/watchlist/${selected.value.symbol}`, {
        method: "DELETE",
      });
    else
      await post("/api/watchlist", {
        symbol: selected.value.symbol,
        asset_type: selected.value.asset_type,
        name: selected.value.name,
      });
    await loadWatchlist();
    ElMessage.success(inWatchlist.value ? "已加入自选" : "已移出自选");
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "自选操作失败");
  }
}
async function placeOrder(side: "BUY" | "SELL", amount = orderAmount.value) {
  if (!selected.value) return;
  orderLoading.value = true;
  try {
    await post("/api/paper/order", {
      symbol: selected.value.symbol,
      asset_type: selected.value.asset_type,
      side,
      amount,
    });
    ElMessage.success(`模拟${side === "BUY" ? "买入" : "卖出"}已按实时价成交`);
    await loadPaper();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "模拟订单失败");
  } finally {
    orderLoading.value = false;
  }
}
async function loadPaper() {
  paperLoading.value = true;
  try {
    const snapshot=await request<any>("/api/paper/snapshot");
    paperAccounts.value=snapshot.accounts;positions.value=snapshot.positions;orders.value=snapshot.orders;
    positions.value.forEach((p:any)=>realtimeMarketStore.subscribe(p.asset_type,p.symbol,p.asset_type==='crypto'?'1m':'1m'));
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "账户数据获取失败");
  } finally {
    paperLoading.value = false;
  }
}
async function showPaper() {
  page.value = "paper";
  await loadPaper();
  if(paperTimer)window.clearInterval(paperTimer);paperTimer=window.setInterval(()=>{if(page.value==='paper')void loadPaper()},5000);
}
async function submitPaperOrder(side:"BUY"|"SELL"){
  if(!selected.value)return ElMessage.warning("请先搜索并选择交易标的");orderLoading.value=true
  try{const result=await post<any>("/api/paper/order",{symbol:selected.value.symbol,asset_type:selected.value.asset_type,side,quantity:orderQuantity.value,order_type:orderType.value,price:orderType.value==='LIMIT'?orderLimitPrice.value:null});ElMessage.success(result.status==='pending'?"限价单已挂单":"模拟订单已成交");await loadPaper()}catch(e){ElMessage.error(e instanceof Error?e.message:"下单失败")}finally{orderLoading.value=false}
}
async function cancelOrder(id:number){try{await post(`/api/paper/orders/${id}/cancel`,{});ElMessage.success("已撤单");await loadPaper()}catch(e){ElMessage.error(e instanceof Error?e.message:"撤单失败")}}
async function resetPaper(){if(!confirm("确定清空所有模拟持仓和订单，并恢复初始资金吗？"))return;await post('/api/paper/reset',{});selected.value=null;await loadPaper();ElMessage.success("模拟账户已重置")}
function openPosition(p:any){openAsset({symbol:p.symbol,name:p.name||p.symbol,asset_type:p.asset_type})}
async function prefillTrade(side:"BUY"|"SELL"="BUY"){if(!selected.value)return;orderType.value='MARKET';orderQuantity.value=Number(aiResult.value?.decision_center?.position_sizing?.quantity)||1;await showPaper();ElMessage.info(`已带入 ${selected.value.symbol} ${side==='BUY'?'买入':'卖出'}信息，请确认后再下单`)}
async function showWatchlist() {
  page.value = "watchlist";
  await loadWatchlist();
}
async function sellAll(position: any) {
  selected.value = {
    symbol: position.symbol,
    name: position.symbol,
    asset_type: position.asset_type,
  };
  orderLoading.value = true;
  try {
    await post("/api/paper/order", {
      symbol: position.symbol,
      asset_type: position.asset_type,
      side: "SELL",
      quantity: position.quantity,
    });
    ElMessage.success("已按实时价全部卖出");
    await loadPaper();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "卖出失败");
  } finally {
    orderLoading.value = false;
  }
}
async function checkUpdates() {
  if (!window.desktopUpdater) {
    ElMessage.info("请在 Windows 桌面客户端中检查更新");
    return;
  }
  updateChecking.value = true;
  updateStatus.value = "正在检查更新…";
  try {
    const result = await window.desktopUpdater.check();
    updateStatus.value =
      result.status === "current"
        ? "当前已经是最新版本。"
        : result.status === "not-configured"
          ? "尚未配置真实 GitHub 更新仓库。"
          : result.status === "network-error"
            ? "暂时无法检查更新，请稍后重试。"
            : result.status === "installing"
              ? "正在安装更新，软件将自动重启。"
              : result.status === "later"
                ? "已选择稍后提醒。"
                : result.status === "bad-release"
                  ? "已阻止曾启动失败的问题版本。"
                  : "更新检查已完成。";
  } catch {
    updateStatus.value = "暂时无法检查更新，请稍后重试。";
  } finally {
    updateChecking.value = false;
  }
}
function refreshPage(){
  if(page.value==='home')void loadHome();else if(page.value==='news')void loadNews();else if(page.value==='paper')void loadPaper();
  else if(page.value==='detail')void Promise.all([loadQuote(),loadKline()]);else if(page.value==='prediction'){void Promise.all([loadQuote(),loadKline()]);if(aiResult.value)void runAI()}
  else if(page.value==='strategy')void loadKline();else if(page.value==='watchlist')void loadWatchlist();
}
function nav(
  target:
    "home" | "market" | "ai" | "backtest" | "news" | "paper" | "watchlist" | "settings",
  updateUrl=true,
) {
  const paths:any={home:'/',market:'/market',ai:'/prediction',backtest:'/strategy',news:'/news',paper:'/paper',watchlist:'/watchlist',settings:'/settings'};if(updateUrl)history.pushState({},"",paths[target]||'/');
  if (target === "home") {
    page.value = "home";
    loadHome();
  } else if (target === "market") {
    page.value = "market";
    nextTick(() =>
      document.querySelector<HTMLInputElement>(".search input")?.focus(),
    );
  } else if (target === "paper") showPaper();
  else if (target === "news") showNews();
  else if (target === "watchlist") showWatchlist();
  else if (target === "settings") page.value = "settings";
  else if(target==='ai'){page.value='prediction';if(!selected.value)selected.value={symbol:'BTC',name:'比特币',asset_type:'crypto'};interval.value=selected.value.asset_type==='crypto'?'1h':'1d';void Promise.all([loadQuote(),loadKline()])}
  else if(target==='backtest'){page.value='strategy';if(!selected.value)selected.value={symbol:'BTC',name:'比特币',asset_type:'crypto'};interval.value=selected.value.asset_type==='crypto'?'1h':'1d';void loadKline()}
}
const removeRealtimeListener=realtimeMarketStore.onEvent(handleRealtime);
function restoreRoute(){const match=location.pathname.match(/^\/(stock|crypto)\/([^/]+)/);if(match){void openAsset({symbol:decodeURIComponent(match[2]),name:decodeURIComponent(match[2]),asset_type:match[1]==='crypto'?'crypto':'stock'},undefined,false);return}const route:Record<string,any>={'/':'home','/market':'market','/prediction':'ai','/strategy':'backtest','/news':'news','/paper':'paper','/watchlist':'watchlist','/settings':'settings'};nav(route[location.pathname]||'home',false)}
onMounted(()=>{realtimeMarketStore.connect();restoreRoute();window.addEventListener('popstate',restoreRoute)});
onBeforeUnmount(()=>{removeRealtimeListener();realtimeMarketStore.close();if(paperTimer)window.clearInterval(paperTimer);window.removeEventListener('popstate',restoreRoute)});
</script>

<template>
  <div class="shell">
    <aside>
      <div class="brand">
        <div class="logo">AI</div>
        <div>
          <b>AI行情助手</b><small>版本 v{{ appVersion }}</small>
        </div>
      </div>
      <nav>
        <button :class="{ active: page === 'home' }" @click="nav('home')">
          <el-icon><HomeFilled /></el-icon>首页
        </button>
        <button :class="{ active: page === 'market' }" @click="nav('market')">
          <el-icon><TrendCharts /></el-icon>行情搜索
        </button>
        <button :class="{ active: page === 'prediction' }" @click="nav('ai')">
          <el-icon><DataAnalysis /></el-icon>AI 预测
        </button>
        <button :class="{ active: page === 'news' }" @click="nav('news')">
          <el-icon><Bell /></el-icon>新闻情报
        </button>
        <button :class="{ active: page === 'strategy' }" @click="nav('backtest')">
          <el-icon><Wallet /></el-icon>回测
        </button>
        <button :class="{ active: page === 'paper' }" @click="nav('paper')">
          <el-icon><Wallet /></el-icon>模拟交易
        </button>
        <button
          :class="{ active: page === 'watchlist' }"
          @click="nav('watchlist')"
        >
          <el-icon><Star /></el-icon>自选
        </button>
        <button
          :class="{ active: page === 'settings' }"
          @click="nav('settings')"
        >
          <el-icon><Setting /></el-icon>设置与更新
        </button>
      </nav>
      <div class="risk">
        <b>研究与模拟模式</b>
        <p>概率预测和历史回测不构成投资建议，不连接真实交易账户。</p>
      </div>
    </aside>
    <main>
      <header>
        <div>
          <h1>
            {{
              page === "detail"
                ? selected
                  ? assetLabel(selected)
                  : "资产详情"
                : page === "paper"
                  ? "模拟交易账户"
                  : page === "market"
                    ? "行情搜索终端"
                  : page === "prediction"
                    ? "AI预测中心"
                  : page === "strategy"
                    ? "策略研究与回测"
                  : page === "news"
                    ? "AI Market Intelligence"
                  : page === "watchlist"
                    ? "我的自选"
                    : page === "settings"
                      ? "设置与更新"
                      : "市场概览"
            }}
          </h1>
          <p>
            {{
              page === "detail"
                ? "真实行情、指标、模型、回测与模拟交易"
                : page === "home"
                  ? "真实公开行情 · 数据源故障自动切换"
                  : page === "news"
                    ? "真实新闻 · 事件影响 · 交易决策辅助"
                  : page === "settings"
                    ? "版本、更新状态与用户数据位置"
                    : "数据持久化保存在本机"
            }}
          </p>
        </div>
        <button
          v-if="page !== 'settings'"
          class="refresh"
          @click="refreshPage"
        >
          <el-icon :class="{ spin: loading || detailLoading || paperLoading }"
            ><Refresh /></el-icon
          >刷新
        </button>
      </header>

      <div v-if="['market','detail','prediction','strategy','paper'].includes(page)" class="search">
        <el-icon><Search /></el-icon
        ><input
          v-model="query"
          @keyup.enter="searchAssets"
          @input="searchOpen = false"
          placeholder="输入贵州茅台、600519、BTC、ETH/USDT…"
        /><button @click="searchAssets" :disabled="searching">
          {{ searching ? "加载中…" : "搜索" }}
        </button>
        <div v-if="searchOpen" class="search-results">
          <div v-if="searching" class="search-state">正在查询真实数据源…</div>
          <template v-else
            ><button
              v-for="asset in searchResults"
              :key="asset.asset_type + asset.symbol"
              @click="selectSearchAsset(asset)"
            >
              <span>{{
                asset.asset_type === "crypto" ? asset.pair : asset.name
              }}</span
              ><small>{{ asset.symbol }} · {{ asset.source }}</small>
            </button>
            <div v-if="searchError" class="search-state error">
              {{ searchError }} <a @click="searchAssets">重试</a>
            </div></template
          >
        </div>
      </div>

      <template v-if="page === 'home'"
        ><el-alert
          v-if="error"
          :title="error"
          type="error"
          show-icon
          :closable="false"
          ><button @click="loadHome">重试</button></el-alert
        >
        <section class="hero">
          <div>
            <span class="eyebrow">REAL MARKET DATA</span>
            <h2>每一张卡片，都能打开真实分析。</h2>
            <p>
              点击资产进入
              K线、技术指标、AI预测、回测与模拟交易。模型概率不会预先写入页面。
            </p>
          </div>
          <div class="pulse">
            <i></i><span>可用行情</span
            ><b
              >{{ items.filter((x) => x.available).length }} /
              {{ items.length }}</b
            >
          </div>
        </section>
        <section v-if="marketContext" class="panel market-center">
          <div>
            <span class="eyebrow">LIVE MARKET CONTEXT</span>
            <h2>{{ marketContext.market_regime.risk_mode }}</h2>
            <p>
              市场状态 {{ marketContext.market_regime.primary }} · 波动
              {{ marketContext.market_regime.volatility }} · 流动性
              {{ marketContext.market_regime.liquidity }}
            </p>
          </div>
          <div>
            <span>资金方向</span
            ><b>{{ marketContext.capital_flow.direction }}</b
            ><small
              >真实 OHLCV 代理比率
              {{
                probability(marketContext.capital_flow.net_flow_ratio)
              }}</small
            >
          </div>
          <div>
            <span>资金轮动</span
            ><b>{{
              rotationSymbols(marketContext.capital_rotation)
            }}</b
            ><small>按真实收益与量价流排序</small>
          </div>
          <div
            :class="[
              'risk-badge',
              marketContext.risk_alerts.length ? 'warning' : '',
            ]"
          >
            <span>风险预警</span
            ><b>{{
              marketContext.risk_alerts.length
                ? "市场状态可能变化"
                : "暂无量价异常"
            }}</b
            ><small>事件日历 {{ marketContext.event_risk.status }}</small>
          </div>
        </section>
        <section v-if="newsIntelligence" class="panel home-intelligence">
          <div><span class="eyebrow">今日市场 AI 总结</span><h2>{{ newsIntelligence.decision.view }}</h2><p>新闻情绪 {{ newsIntelligence.radar.market_sentiment }} · 利好 {{ newsIntelligence.radar.positive }} · 利空 {{ newsIntelligence.radar.negative }} · 重大 {{ newsIntelligence.radar.major }}</p></div>
          <div><b>核心驱动</b><p v-for="item in newsIntelligence.top_news.slice(0,3)" :key="item.id">{{ item.event.event_type }}：{{ item.one_sentence_summary }}</p></div>
          <div><b>重点板块 / 风险</b><p>{{ Object.entries(newsIntelligence.sector_impact).sort((a:any,b:any)=>Math.abs(b[1].score)-Math.abs(a[1].score)).slice(0,4).map((x:any)=>`${x[0]} ${x[1].score>0?'+':''}${x[1].score}`).join(' · ') || '暂无明确板块信号' }}</p></div>
          <button @click="nav('news')">打开新闻情报中心 →</button>
        </section>
        <section>
          <div class="title-row">
            <div>
              <h3>数字资产</h3>
              <p>公开交易所 API · 点击查看详情</p>
            </div>
          </div>
          <div class="grid">
            <button
              v-for="x in cryptos"
              :key="x.symbol"
              class="card"
              @click="openAsset(x)"
            >
              <div class="asset">
                <div class="coin">{{ x.symbol[0] }}</div>
                <div>
                  <b>{{ x.symbol }} / USDT</b
                  ><small
                    >{{ x.name }} · {{ x.source || "数据源不可用" }}</small
                  >
                </div>
              </div>
              <div class="price">{{ price(x.price, "USDT") }}</div>
              <div :class="['change', trendClass(x.change_percent)]">
                {{ (x.change_percent || 0) >= 0 ? "+" : ""
                }}{{ x.change_percent?.toFixed(2) }}%
              </div>
              <div class="card-action">查看真实 K线与分析 →</div>
            </button>
          </div>
        </section>
        <section>
          <div class="title-row">
            <div>
              <h3>A 股市场</h3>
              <p>指数与自选股票 · 点击查看详情</p>
            </div>
          </div>
          <div class="grid">
            <button
              v-for="x in stocks"
              :key="x.symbol"
              class="card compact"
              @click="openAsset(x)"
            >
              <div class="asset">
                <div class="stock">{{ x.name[0] }}</div>
                <div>
                  <b>{{ x.name }}</b
                  ><small
                    >{{ x.symbol }} · {{ x.source || "数据源不可用" }}</small
                  >
                </div>
              </div>
              <div class="price">{{ price(x.price, "CNY") }}</div>
              <div :class="['change', trendClass(x.change_percent)]">
                {{ (x.change_percent || 0) >= 0 ? "+" : ""
                }}{{ x.change_percent?.toFixed(2) }}%
              </div>
              <div class="card-action">查看真实 K线与分析 →</div>
            </button>
          </div>
        </section></template
      >

      <template v-else-if="page === 'market'">
        <section class="market-workspace">
          <div class="panel market-guide"><span class="eyebrow">FIND & ANALYZE</span><h2>找股票 / 看股票</h2><p>在上方输入贵州茅台、600519、NVDA、TSLA、BTC。搜索结果来自东方财富、Yahoo Finance 或 OKX，选择后进入对应 symbol 的独立详情终端。</p></div>
          <section class="panel"><h3>可用市场入口</h3><div class="market-directory"><button @click="query='600519';searchAssets()">A股 · 600519</button><button @click="query='NVDA';searchAssets()">美股 · NVDA</button><button @click="query='TSLA';searchAssets()">美股 · TSLA</button><button @click="query='BTC';searchAssets()">Crypto · BTC</button></div></section>
          <section class="panel"><h3>行情终端包含</h3><div class="feature-strip"><div><b>实时价格</b><span>Ticker 与成交量</span></div><div><b>实时K线</b><span>当前蜡烛逐Tick更新</span></div><div><b>技术指标</b><span>MA/MACD/RSI/BOS/FVG</span></div><div><b>决策工具</b><span>新闻、AI预测、策略、模拟交易</span></div></div></section>
        </section>
      </template>

      <template v-else-if="page === 'prediction'">
        <section class="panel prediction-workspace">
          <div class="panel-top"><div><span class="eyebrow">PREDICTION CENTER</span><h2>{{ selected ? `${selected.name} ${selected.symbol}` : '请搜索标的' }}</h2><p>模型仅使用截至数据截止时间的真实K线、指标与外部上下文。</p></div><button class="primary" @click="runAI()" :disabled="aiLoading||!selected">{{ aiLoading?'正在训练与验证…':aiResult?'重新预测':'开始预测' }}</button></div>
          <el-alert v-if="aiError" :title="`AI预测暂时不可用：${aiError}`" type="warning" show-icon :closable="false"><button @click="runAI()">重新预测</button></el-alert>
          <div v-if="aiLoading" class="loading-box">正在获取最新行情、新闻、市场环境并执行严格时间验证…</div>
          <template v-else-if="aiResult"><div class="prediction-meta"><span>预测生成：{{ aiResult.predicted_at?.replace('T',' ').slice(0,19) || aiResult.realtime?.generated_at?.replace('T',' ').slice(0,19) }}</span><span>数据截止：{{ aiResult.data_time?.replace('T',' ').slice(0,19) }}</span><span>数据源：{{ aiResult.data_source }}</span></div>
            <div class="prediction-grid"><article v-for="p in predictionRows" :key="p.horizon" class="prediction-card"><h3>{{ p.horizon }}</h3><template v-if="p.prediction"><b>{{ p.prediction }}</b><p title="基于当前模型输入条件，对指定周期方向的统计概率估计，不保证收益。">上涨 {{ probability(p.probabilities.up) }} · 震荡 {{ probability(p.probabilities.flat) }} · 下跌 {{ probability(p.probabilities.down) }}</p><span title="表示模型在当前数据条件下对结果稳定程度的估计。">置信度 {{ p.confidence_score }}/100 · {{ p.confidence }}</span><small>Walk-forward {{ p.walk_forward_samples }} 个样本 · {{ p.status }}</small></template><template v-else><b>数据不足</b><p>{{ p.message }}</p></template></article></div>
            <section class="prediction-evidence"><h3 title="综合技术趋势、成交量、新闻、市场环境与历史统计。">预测依据 / AI评分</h3><p>策略一致性 {{ aiResult.decision_center?.technical_strategy?.confluence?.score ?? '—' }} · 数据质量 {{ aiResult.decision_center?.technical_strategy?.data_quality?.score ?? '—' }} · 市场环境 {{ aiResult.decision_center?.market_regime?.primary || '—' }}</p><p class="data-warning">预测概率是样本外统计估计，不是收益保证；样本不足的周期不会强行生成。</p></section>
          </template><div v-else class="empty">搜索并选择标的，然后点击“开始预测”。不会自动展示旧结果。</div>
        </section>
      </template>

      <template v-else-if="page === 'strategy'">
        <section class="panel strategy-workspace"><div class="panel-top"><div><span class="eyebrow">STRATEGY LAB</span><h2>{{ selected ? `${selected.symbol} 策略研究` : '请选择标的' }}</h2><p>配置策略并对真实历史K线执行含手续费、滑点的回测。</p></div><div><button class="primary" @click="runBacktest" :disabled="backtestLoading||!selected">{{ backtestLoading?'回测中…':'开始回测' }}</button> <button v-if="backtestResult" @click="prefillTrade('BUY')">模拟执行</button></div></div>
          <div class="strategy-controls"><select v-model="strategy"><option value="ma">MA 金叉/死叉</option><option value="macd">MACD</option><option value="rsi">RSI</option><option value="breakout">突破</option><option value="fibonacci">Fibonacci</option><option value="bos">BOS</option><option value="fvg">FVG</option><option value="fib_fvg_bos">Fib+FVG+BOS</option></select><select v-model="interval"><option value="1d">1D</option><option value="4h">4H</option><option value="1h">1H</option><option value="15m">15M</option></select><label>初始资金 <input v-model.number="initialCash" type="number" /></label></div>
          <div v-if="backtestResult" class="backtest-metrics"><div><span>最终资金</span><b>{{ backtestResult.final_cash }}</b></div><div><span>收益率</span><b>{{ backtestResult.return_percent }}%</b></div><div><span>最大回撤</span><b>{{ backtestResult.max_drawdown_percent }}%</b></div><div><span>胜率</span><b>{{ backtestResult.win_rate_percent }}%</b></div><div><span>交易次数</span><b>{{ backtestResult.trade_count }}</b></div></div><EquityChart v-if="backtestResult" :curve="backtestResult.equity_curve"/><div v-else class="empty">策略页面只负责策略选择、参数与历史回测，不再打开固定 BTC 详情页。</div>
        </section>
      </template>

      <template v-else-if="page === 'news'">
        <el-alert v-if="newsError" :title="newsError" type="error" show-icon :closable="false">
          <button @click="loadNews()">重试</button>
        </el-alert>
        <div v-if="newsLoading" class="loading-box">正在采集真实公开新闻并执行事件分析…</div>
        <template v-else-if="newsIntelligence">
          <section class="panel news-filters">
            <div><label>市场</label><select v-model="newsMarket"><option>全部</option><option>A股</option><option>美股</option><option>加密货币</option><option>全球</option></select></div>
            <div><label>类型</label><select v-model="newsCategory"><option>全部</option><option>公司</option><option>行业</option><option>政策</option><option>宏观</option><option>财报</option><option>公告</option><option>市场</option><option>地缘政治</option></select></div>
            <div><label>方向</label><select v-model="newsDirection"><option>全部</option><option>利好</option><option>利空</option><option>中性</option></select></div>
            <div><label>时间</label><select v-model.number="newsHours"><option :value="1">1小时</option><option :value="6">6小时</option><option :value="24">24小时</option><option :value="72">3天</option><option :value="168">7天</option><option :value="0">全部</option></select></div>
            <div class="news-search"><label>新闻 / 股票 / 板块</label><input v-model="newsKeyword" @keyup.enter="applyNewsFilters" placeholder="美联储、英伟达、半导体、BTC" /></div>
            <button class="primary" @click="applyNewsFilters">筛选</button>
          </section>
          <section class="panel intelligence-hero">
            <div><span class="eyebrow">TODAY'S MARKET RADAR</span><h2>{{ newsIntelligence.radar.market_sentiment }}</h2><p>市场新闻情绪分（-100 ~ +100）</p></div>
            <div class="news-radar">
              <article><b class="positive">{{ newsIntelligence.radar.positive }}</b><span>利好</span></article>
              <article><b class="negative">{{ newsIntelligence.radar.negative }}</b><span>利空</span></article>
              <article><b>{{ newsIntelligence.radar.neutral }}</b><span>中性</span></article>
              <article><b>{{ newsIntelligence.radar.major }}</b><span>重大事件</span></article>
            </div>
          </section>
          <section class="two-col">
            <div class="panel"><div class="panel-top"><h3>AI 综合观点</h3><span class="score">置信等级 {{ newsIntelligence.decision.confidence_grade }}</span></div>
              <h2>{{ newsIntelligence.decision.view }}</h2>
              <div class="decision-bars"><span>BUY {{ newsIntelligence.decision.scores.buy }}</span><span>HOLD {{ newsIntelligence.decision.scores.hold }}</span><span>AVOID {{ newsIntelligence.decision.scores.avoid }}</span></div>
              <p class="data-warning">{{ newsIntelligence.decision.notice }}</p>
            </div>
            <div class="panel"><h3>T+1 / T+3 / T+5 证据估计</h3><div class="level-list"><div v-for="(value,key) in newsIntelligence.predictions" :key="key"><b>{{ key }} · 上涨 {{ value.up }}% · 震荡 {{ value.flat }}% · 下跌 {{ value.down }}%</b><span>{{ value.type }} · 已验证样本 {{ value.validated_samples }}</span></div></div></div>
          </section>
          <section class="two-col">
            <div class="panel"><h3>利好板块</h3><div class="tag-list"><span v-for="(value,key) in newsIntelligence.sector_impact" :key="key" v-show="value.score > 0">{{ key }} +{{ value.score }}</span></div></div>
            <div class="panel"><h3>风险板块</h3><div class="tag-list risk-tags"><span v-for="(value,key) in newsIntelligence.sector_impact" :key="key" v-show="value.score < 0">{{ key }} {{ value.score }}</span></div></div>
          </section>
          <section class="two-col">
            <div class="panel"><h3>AI 关注名单</h3><div class="level-list"><div v-for="item in newsIntelligence.watch_list" :key="item.id"><b>{{ item.event.subject }} · {{ item.event.direction }} · 评分 {{ item.impact.score }}</b><span>{{ item.one_sentence_summary }}</span></div><p v-if="!newsIntelligence.watch_list.length" class="data-warning">暂无达到关注阈值的真实新闻。</p></div></div>
            <div class="panel"><h3>AI 风险名单</h3><div class="level-list"><div v-for="item in newsIntelligence.risk_list" :key="item.id"><b class="negative">{{ item.event.subject }} · {{ item.event.direction }} · 评分 {{ item.impact.score }}</b><span>{{ item.one_sentence_summary }}</span></div><p v-if="!newsIntelligence.risk_list.length" class="data-warning">暂无达到风险阈值的真实新闻。</p></div></div>
          </section>
          <section class="panel"><div class="panel-top"><div><h3>真实新闻列表</h3><p>共 {{ newsIntelligence.total }} 条 · 默认按影响程度与时间排序 · 每页 20 条</p></div><small>{{ newsIntelligence.method }}</small></div>
            <div v-if="!newsIntelligence.items?.length" class="empty">当前筛选条件下暂无可用真实新闻，请调整筛选或稍后重试。</div>
            <div class="news-list rich-news"><article v-for="item in newsIntelligence.items" :key="item.id" @click="openNews(item)">
              <div class="news-score" :class="newsClass(item)"><span>{{ item.event.direction }}</span><b>{{ item.impact.score }}</b></div>
              <div><h3 :class="newsClass(item)">{{ item.event.direction }} · {{ item.title }}</h3><p>{{ item.summary }}</p><small>{{ item.published_at?.replace('T',' ').slice(0,19) || '发布时间未知（禁止进入回测）' }} · {{ item.source }} · {{ item.market }} · {{ item.category }}</small>
                <div class="news-tags"><span v-for="symbol in item.symbols" :key="symbol">{{ symbol }}</span><span v-for="sector in item.sectors" :key="sector">{{ sector }}</span><em>{{ stars(item.impact.score) }} {{ item.impact.level }}</em><em>分析：{{ item.analysis_status }}</em><em v-if="item.related_source_count>1">相关新闻 {{ item.related_source_count }} 条</em></div>
                <p><b>为什么{{ item.event.direction }}：</b>{{ item.reason.join('；') }}</p>
              <button @click.stop="openNews(item)">AI深度分析</button> <a @click.stop :href="item.url" target="_blank">查看原文</a>
              </div>
            </article></div>
            <button v-if="newsIntelligence.has_more" class="load-more" @click="loadMoreNews">加载更多</button>
          </section>
          <section class="panel"><h3>数据源状态</h3><div class="provider-health"><span v-for="provider in newsIntelligence.provider_statuses" :key="provider.provider" :class="provider.status==='HEALTHY'?'positive':'negative'">{{ provider.status==='HEALTHY'?'●':'●' }} {{ provider.provider }} · {{ provider.count }} 条 · {{ provider.latency_ms }}ms</span></div><p class="data-warning">Point-in-Time：{{ newsIntelligence.point_in_time }} · 缓存降级 {{ newsIntelligence.cache_fallback?'已启用':'未启用' }}</p></section>
        </template>
      </template>

      <template v-else-if="page === 'detail'"
        ><el-alert
          v-if="detailError"
          :title="detailError"
          type="error"
          show-icon
          :closable="false"
          ><button @click="loadKline">重试</button></el-alert
        >
        <section v-if="selected" class="detail-head">
          <div>
            <span class="eyebrow">{{
              selected.asset_type === "crypto" ? "CRYPTO" : /^[A-Za-z]/.test(selected.symbol) ? "US EQUITY" : "A-SHARE"
            }}</span>
            <h2>
              {{ selected.name }}
              <small>{{
                selected.asset_type === "crypto"
                  ? selected.symbol + "/USDT"
                  : selected.symbol
              }}</small>
            </h2>
            <div class="big-price">
              {{ price(quote?.price, quote?.currency) }}
              <span :class="trendClass(quote?.change_percent)"
                >{{ (quote?.change_percent || 0) >= 0 ? "+" : ""
                }}{{ quote?.change_percent?.toFixed(2) }}%</span
              >
            </div>
            <p>
              {{ quote?.source || "正在连接数据源" }} ·
              {{ quote?.updated_at?.replace("T", " ").slice(0, 19) }}
            </p>
            <div :class="['realtime-status', liveStatus.toLowerCase()]">
              <i></i>{{ liveStatus === 'MARKET_CLOSED' ? '当前市场休市，实时行情暂停' : liveStatus }}
              <span>数据源 {{ selectedLiveState.source || quote?.source || '等待连接' }}</span>
              <span>最后更新 {{ selectedLiveState.processedTimestamp?.replace('T',' ').slice(11,19) || realtimeMarketStore.lastUpdateTime.value || '等待数据' }}</span>
              <span v-if="selectedLiveState.latencyMs!=null">延迟 {{ selectedLiveState.latencyMs }}ms</span>
            </div>
          </div>
          <div class="head-actions">
            <button @click="toggleWatch">
              {{ inWatchlist ? "★ 已收藏" : "☆ 加入自选" }}</button
            ><button class="primary" @click="runAI()" :disabled="aiLoading">
              {{ aiLoading ? "训练模型中…" : "AI预测" }}
            </button>
          </div>
        </section>
        <div v-if="quote" class="stats">
          <div>
            <span>开盘</span><b>{{ price(quote.open, quote.currency) }}</b>
          </div>
          <div>
            <span>昨收/24H开盘</span
            ><b>{{
              price(quote.previous_close ?? quote.open, quote.currency)
            }}</b>
          </div>
          <div>
            <span>最高</span><b>{{ price(quote.high, quote.currency) }}</b>
          </div>
          <div>
            <span>最低</span><b>{{ price(quote.low, quote.currency) }}</b>
          </div>
          <div>
            <span>成交量</span><b>{{ compact(quote.volume) }}</b>
          </div>
          <div>
            <span>成交额</span><b>{{ compact(quote.amount) }}</b>
          </div>
        </div>
        <section class="panel">
          <div class="panel-top">
            <h3>真实 K线与成交量</h3>
            <div class="periods">
              <button
                v-for="p in periods"
                :key="p"
                :class="{ active: interval === p }"
                @click="changeInterval(p)"
                :disabled="detailLoading"
              >
                {{ p.toUpperCase() }}
              </button>
              <button class="buy" @click="prefillTrade('BUY')">买入</button><button class="sell" @click="prefillTrade('SELL')">卖出</button>
            </div>
          </div>
          <div v-if="detailLoading" class="loading-box">
            正在获取 {{ interval.toUpperCase() }} 真实 K线…
          </div>
          <KlineChart v-else :candles="candles" :indicators="indicators" :structure="aiResult?.decision_center?.technical_strategy" :news="newsIntelligence?.top_news || []" @news-click="openNews" />
        </section>
        <section v-if="newsIntelligence" class="panel">
          <div class="panel-top"><div><h3>最新相关新闻</h3><p>仅显示明确提及 {{ selected?.name }} / {{ selected?.symbol }} 的新闻</p></div></div>
          <div class="decision-bars"><span>BUY {{ newsIntelligence.decision.scores.buy }}</span><span>HOLD {{ newsIntelligence.decision.scores.hold }}</span><span>AVOID {{ newsIntelligence.decision.scores.avoid }}</span></div>
          <h3>{{ newsIntelligence.decision.view }}</h3>
          <div class="news-list compact-news"><article v-for="item in newsIntelligence.items?.slice(0,5)" :key="item.id" @click="openNews(item)"><div class="news-score" :class="newsClass(item)">{{ item.impact.score }}</div><div><b>{{ item.title }}</b><p>{{ item.event.direction }} · {{ item.event.event_type }} · 影响 {{ stars(item.impact.score) }}</p></div></article></div>
          <div class="news-backtest-form"><select v-model="newsBacktestDirection"><option value="bullish">利好</option><option value="bearish">利空</option><option value="all">全部</option></select><label>最低影响 <input v-model.number="newsBacktestImpact" type="number" min="0" max="100" /></label><label>最低置信度% <input v-model.number="newsBacktestConfidence" type="number" min="0" max="100" /></label><select v-model.number="newsBacktestHorizon"><option :value="1">T+1</option><option :value="3">T+3</option><option :value="5">T+5</option><option :value="10">T+10</option><option :value="20">T+20</option></select><button class="primary" @click="runNewsBacktest">开始新闻策略回测</button></div>
          <div v-if="newsBacktest" class="backtest-metrics"><div><span>状态</span><b>{{ newsBacktest.status }}</b></div><div><span>样本</span><b>{{ newsBacktest.samples }}</b></div><div><span>方向胜率</span><b>{{ newsBacktest.win_rate==null?'—':probability(newsBacktest.win_rate) }}</b></div><div><span>平均收益</span><b>{{ newsBacktest.average_return==null?'—':probability(newsBacktest.average_return) }}</b></div><div><span>最大 / 最小</span><b>{{ newsBacktest.max_return==null?'—':`${probability(newsBacktest.max_return)} / ${probability(newsBacktest.min_return)}` }}</b></div><div><span>最大回撤</span><b>{{ probability(newsBacktest.max_drawdown) }}</b></div></div>
          <p v-if="newsBacktest?.notice" class="data-warning">{{ newsBacktest.notice }}</p>
        </section>
        <section v-if="indicators" class="panel">
          <div class="panel-top">
            <h3>实时计算技术指标</h3>
            <span class="score">综合 {{ indicators.score }} / 100</span>
          </div>
          <div class="indicator-grid">
            <div>
              <span>MA5 / MA20</span
              ><b
                >{{ indicators.latest.ma5?.toFixed(2) }} /
                {{ indicators.latest.ma20?.toFixed(2) }}</b
              >
            </div>
            <div>
              <span>EMA12 / EMA26</span
              ><b
                >{{ indicators.latest.ema12?.toFixed(2) }} /
                {{ indicators.latest.ema26?.toFixed(2) }}</b
              >
            </div>
            <div>
              <span title="MACD用于观察趋势方向、动能及其变化。">MACD ⓘ</span><b>{{ indicators.latest.macd?.toFixed(4) }}</b>
            </div>
            <div>
              <span title="RSI衡量近期上涨与下跌的相对强弱，通常用于识别超买或超卖。">RSI(14) ⓘ</span><b>{{ indicators.latest.rsi?.toFixed(2) }}</b>
            </div>
            <div>
              <span>K / D / J</span
              ><b
                >{{ indicators.latest.kdj_k?.toFixed(1) }} /
                {{ indicators.latest.kdj_d?.toFixed(1) }} /
                {{ indicators.latest.kdj_j?.toFixed(1) }}</b
              >
            </div>
            <div>
              <span>BOLL 上/中/下</span
              ><b
                >{{ indicators.latest.boll_upper?.toFixed(2) }} /
                {{ indicators.latest.boll_mid?.toFixed(2) }} /
                {{ indicators.latest.boll_lower?.toFixed(2) }}</b
              >
            </div>
            <div>
              <span>ATR</span><b>{{ indicators.latest.atr?.toFixed(3) }}</b>
            </div>
            <div>
              <span>OBV</span><b>{{ compact(indicators.latest.obv) }}</b>
            </div>
          </div>
        </section>
        <section v-if="livePredictionHistory.length" class="panel">
          <div class="panel-top"><h3>AI 预测变化</h3><small class="muted">LIVE 与历史回测数据严格分离</small></div>
          <div class="live-history">
            <article v-for="item in livePredictionHistory" :key="item.prediction_id">
              <b>{{ item.action || 'HOLD' }}</b><span>{{ item.time.replace('T',' ').slice(0,19) }}</span>
              <small>{{ item.mode }} · {{ item.reasons.join(' / ') }}</small>
            </article>
          </div>
        </section>
        <section class="two-col">
          <div class="panel ai-panel">
            <div class="panel-top">
              <div>
                <h3>AI V5 因果策略研究驾驶舱</h3>
                <small class="muted">30类技术策略 · ICT/SMC · Fib/FVG/BOS · 严格时间验证</small>
              </div>
              <button class="primary" @click="runAI()" :disabled="aiLoading">
                {{ aiLoading ? "全链路计算中…" : "生成动态方案" }}
              </button>
            </div>
            <div class="decision-inputs">
              <label>账户资金<input v-model.number="accountEquity" type="number" min="100" /></label>
              <label>单笔风险 %<input v-model.number="maxRiskPercent" type="number" min="0.1" max="10" step="0.1" /></label>
              <label>杠杆<input v-model.number="leverage" type="number" min="1" max="100" /></label>
            </div>
            <div v-if="!aiResult" class="empty">
              将比较 Logistic Regression、Random Forest、XGBoost、LightGBM
              与可用的 CatBoost；使用隔离验证集选择权重，最终测试集不参与选模。
            </div>
            <template v-else
              ><div class="prediction-grid v2">
                <div
                  v-for="(p, h) in aiResult.predictions"
                  :key="h"
                  class="prediction-card"
                >
                  <template v-if="p.prediction"
                    ><div class="prediction-title">
                      <span>未来 {{ h }}</span
                      ><i>{{ p.status }}</i>
                    </div>
                    <b
                      >{{ p.trend }} <small>{{ p.prediction }}</small></b
                    >
                    <div class="probability-bars">
                      <label
                        >涨 <span>{{ probability(p.probabilities.up) }}</span
                        ><i
                          :style="{ width: probability(p.probabilities.up) }"
                        ></i></label
                      ><label
                        >震 <span>{{ probability(p.probabilities.flat) }}</span
                        ><i
                          :style="{ width: probability(p.probabilities.flat) }"
                        ></i></label
                      ><label
                        >跌 <span>{{ probability(p.probabilities.down) }}</span
                        ><i
                          :style="{ width: probability(p.probabilities.down) }"
                        ></i
                      ></label>
                    </div>
                    <div class="confidence">
                      <strong>置信等级 {{ p.confidence }}</strong
                      ><span>{{ p.confidence_score }} / 100</span
                      ><span>模型共识 {{ p.consensus_label }}</span>
                    </div>
                    <small
                      >目标
                      {{
                        p.future_timestamp?.replace("T", " ").slice(0, 19)
                      }}
                      UTC</small
                    ><em
                      >Walk Forward {{ p.walk_forward_accuracy }}% ·
                      {{ p.walk_forward_samples }} 样本</em
                    >
                    <div class="advantage">{{ p.advantage_message }}</div>
                    <details>
                      <summary>模型细节与权重</summary>
                      <div
                        v-for="(m, name) in p.model_details"
                        :key="name"
                        class="model-row"
                      >
                        <b>{{ name }}</b
                        ><span>权重 {{ (m.weight * 100).toFixed(1) }}%</span
                        ><span>{{ m.direction }}</span
                        ><small
                          >Accuracy {{ probability(m.metrics.accuracy) }} · F1
                          {{ m.metrics.f1_macro }}</small
                        >
                      </div>
                    </details>
                    <details>
                      <summary>主要影响因子</summary>
                      <div
                        v-for="f in p.top_factors"
                        :key="f.feature"
                        class="factor-row"
                      >
                        <span>{{ f.label }}</span
                        ><b
                          :class="
                            f.direction === 'positive' ? 'positive' : 'negative'
                          "
                          >{{ f.direction === "positive" ? "正向" : "负向" }}</b
                        ><small>重要性 {{ probability(f.importance) }}</small>
                      </div>
                    </details></template
                  ><template v-else
                    ><b>数据不足</b><small>{{ p.message }}</small></template
                  >
                </div>
              </div>
              <div class="feature-strip">
                <div
                  v-for="(s, name) in aiResult.feature_availability
                    .feature_status"
                  :key="name"
                  :class="{ available: s.available }"
                >
                  <span>{{ name }}</span
                  ><b>{{ availabilityLabel(s) }}</b>
                </div>
              </div>
              <section v-if="aiResult.decision_center" class="decision-center">
                <div class="decision-hero">
                  <div><span>最终决策</span><b>{{ aiResult.decision_center.v5_final_decision?.action || aiResult.decision_center.decision.action }}</b><small>{{ aiResult.decision_center.v5_final_decision?.reason || aiResult.decision_center.decision.reason }}</small></div>
                  <div><span>策略共振</span><b>{{ aiResult.decision_center.v5_final_decision?.strategy_confluence ?? aiResult.decision_center.trade_opportunity.score }} / 100</b><small>{{ aiResult.decision_center.v5_final_decision?.direction || aiResult.decision_center.decision.direction }}</small></div>
                  <div><span>风险等级</span><b>{{ aiResult.decision_center.risk_level.level }}</b><small>{{ probability(aiResult.decision_center.risk_level.score) }}</small></div>
                </div>
                <section v-if="aiResult.decision_center.technical_strategy" class="strategy-radar">
                  <div class="panel-top"><div><h3>技术策略雷达</h3><small class="muted">同源指标先按信息家族去重，再计算共振；不可用数据不计分</small></div><b>{{ aiResult.decision_center.technical_strategy.confluence.score }} / 100 · {{ aiResult.decision_center.technical_strategy.confluence.signal }}</b></div>
                  <div class="strategy-grid">
                    <details v-for="item in aiResult.decision_center.technical_strategy.signals" :key="item.strategy" class="strategy-card">
                      <summary><span class="signal-dot" :class="signalClass(item.signal)"></span><b>{{ strategyLabel(item.strategy) }}</b><em :class="signalClass(item.signal)">{{ item.status === 'AVAILABLE' ? item.signal : item.status }}</em><small>{{ item.confidence.toFixed(0) }}%</small></summary>
                      <p>{{ item.reason }}</p>
                      <div class="strategy-meta"><span>强度 {{ item.strength }}</span><span>周期 {{ item.timeframe }}</span><span>质量 {{ item.data_quality }}</span><span>{{ item.timestamp?.replace('T',' ').slice(0,19) }} UTC</span></div>
                      <div class="level-list"><div v-for="(e,index) in item.evidence" :key="`${item.strategy}-${index}`"><b>{{ e.name }}</b><span>{{ e.value }} · 贡献 {{ e.contribution }}</span></div></div>
                    </details>
                  </div>
                  <div class="structure-summary">
                    <article title="BOS是价格突破已有结构；CHoCH表示市场结构可能转向。"><span>市场结构 ⓘ</span><b>{{ aiResult.decision_center.technical_strategy.structure.trend }}</b><small>BOS {{ aiResult.decision_center.technical_strategy.structure.latest_bos?.direction || 'NONE' }} · CHoCH {{ aiResult.decision_center.technical_strategy.structure.latest_choch?.direction || 'NONE' }}</small></article>
                    <article><span>Fibonacci</span><b>{{ aiResult.decision_center.technical_strategy.fibonacci.status }}</b><small>{{ aiResult.decision_center.technical_strategy.fibonacci.direction || '—' }} · available_at {{ aiResult.decision_center.technical_strategy.fibonacci.available_at?.replace('T',' ').slice(0,19) || '—' }}</small></article>
                    <article title="FVG（Fair Value Gap）是价格快速移动形成的三K线非平衡区域。"><span>FVG ⓘ</span><b>{{ aiResult.decision_center.technical_strategy.fvgs.filter((x:any)=>x.status!=='FILLED').length }} Open</b><small>只绘制三K线真实缺口</small></article>
                    <article><span>动态风险</span><b>EV {{ aiResult.decision_center.technical_strategy.risk_plan.expected_value }}</b><small>样本 {{ aiResult.decision_center.technical_strategy.risk_plan.historical_samples }} · SL {{ aiResult.decision_center.technical_strategy.risk_plan.stop_loss }}</small></article>
                  </div>
                  <details><summary>多空与中性证据链</summary><div class="evidence-columns"><div><h4>看多</h4><p v-for="(e,i) in aiResult.decision_center.technical_strategy.evidence_chain.bullish" :key="`b${i}`">+ {{ e.name }} · {{ e.value }}</p></div><div><h4>看空</h4><p v-for="(e,i) in aiResult.decision_center.technical_strategy.evidence_chain.bearish" :key="`s${i}`">- {{ e.name }} · {{ e.value }}</p></div><div><h4>中性/缺数据</h4><p v-for="(e,i) in aiResult.decision_center.technical_strategy.evidence_chain.neutral" :key="`n${i}`">{{ strategyLabel(e.name) }} · {{ e.value }}</p></div></div></details>
                </section>
                <div class="decision-grid">
                  <article><h4>市场环境</h4><b>{{ aiResult.decision_center.market_regime.primary }}</b><p>{{ aiResult.decision_center.market_regime.risk_mode }} · {{ aiResult.decision_center.market_regime.volatility }}</p></article>
                  <article><h4>资金方向</h4><b>{{ aiResult.decision_center.capital_flow.direction }}</b><p>{{ aiResult.decision_center.capital_flow.price_flow_relation }} · 持续性 {{ probability(aiResult.decision_center.capital_flow.flow_persistence) }}</p></article>
                  <article><h4>市场结构</h4><b>{{ aiResult.decision_center.market_structure.structure }}</b><p>{{ aiResult.decision_center.market_structure.high_pattern }} / {{ aiResult.decision_center.market_structure.low_pattern }}</p></article>
                  <article><h4>期望值</h4><b :class="trendClass(aiResult.decision_center.expected_value.percent)">{{ probability(aiResult.decision_center.expected_value.percent) }}</b><p>TP2 R:R {{ aiResult.decision_center.risk_reward.tp2 }} · 盈亏平衡 {{ aiResult.decision_center.risk_reward.breakeven_rr }}</p></article>
                  <article><h4>当前宏观</h4><b>{{ aiResult.decision_center.external_context?.macro?.signal || aiResult.decision_center.external_context?.macro?.status || 'NO_DATA' }}</b><p>{{ aiResult.decision_center.external_context?.macro?.source || '未取得可验证来源' }}</p></article>
                  <article><h4>新闻情绪</h4><b>{{ aiResult.decision_center.external_context?.news?.status || 'NO_DATA' }}</b><p>标题关键词分数 {{ aiResult.decision_center.external_context?.news?.sentiment_score ?? '—' }} · 非 LLM 编造</p></article>
                  <article><h4>事件调整置信度</h4><b>{{ probability(aiResult.decision_center.confidence_adjustment.adjusted) }}</b><p>原始 {{ probability(aiResult.decision_center.confidence_adjustment.raw) }} · 事件系数 {{ aiResult.decision_center.confidence_adjustment.event_factor }}</p></article>
                  <article v-if="aiResult.decision_center.research"><h4>数据质量</h4><b>{{ aiResult.decision_center.research.data_quality.score }} / 100</b><p>{{ aiResult.decision_center.research.data_quality.grade }} · {{ aiResult.decision_center.research.data_quality.components.source_count }} 个来源</p></article>
                  <article v-if="aiResult.decision_center.research"><h4>预期收益 / 波动</h4><b>{{ probability(aiResult.decision_center.research.return_distribution.expected_return) }}</b><p>波动 {{ probability(aiResult.decision_center.research.return_distribution.expected_volatility) }} · {{ aiResult.decision_center.research.return_distribution.status }}</p></article>
                  <article v-if="aiResult.decision_center.research"><h4>市场异常</h4><b>{{ aiResult.decision_center.research.anomaly_detection.status }}</b><p>{{ aiResult.decision_center.research.anomaly_detection.signals.length }} 个已触发异常</p></article>
                  <article v-if="portfolioRisk"><h4>组合风险</h4><b>{{ portfolioRisk.status }}</b><p v-if="portfolioRisk.status === 'AVAILABLE'">VaR {{ probability(portfolioRisk.var_95_per_bar) }} · CVaR {{ probability(portfolioRisk.cvar_95_per_bar) }}</p><p v-else>{{ portfolioRisk.reason }}</p></article>
                </div>
                <div class="trade-plan"><div><span>参考入场</span><b>{{ aiResult.decision_center.decision.entry_zone.lower }} - {{ aiResult.decision_center.decision.entry_zone.upper }}</b></div><div><span>动态止损</span><b>{{ aiResult.decision_center.risk_plan.stop_loss }}</b></div><div v-for="tp in aiResult.decision_center.take_profits" :key="tp.name"><span>{{ tp.name }}</span><b>{{ tp.price }}</b><small>R:R {{ tp.risk_reward }}</small></div><div><span>建议仓位</span><b>{{ aiResult.decision_center.position_sizing.quantity }}</b><small>名义价值 {{ aiResult.decision_center.position_sizing.notional }}</small></div></div>
                <details><summary>为什么是这个止损？</summary><pre>{{ JSON.stringify(aiResult.decision_center.risk_plan, null, 2) }}</pre></details>
                <details><summary>支撑、压力与强度</summary><div class="level-list"><div v-for="s in aiResult.decision_center.support_resistance.supports" :key="s.center"><b>支撑 {{ s.lower }} - {{ s.upper }}</b><span>{{ s.strength }}/100</span></div><div v-for="r in aiResult.decision_center.support_resistance.resistances" :key="r.center"><b>压力 {{ r.lower }} - {{ r.upper }}</b><span>{{ r.strength }}/100</span></div></div></details>
                <details><summary>资金 × 时间周期</summary><div class="timeframe-matrix"><div v-for="(value,tf) in aiResult.decision_center.multi_timeframe.matrix" :key="tf"><b>{{ tf }}</b><span>{{ value.trend || value.status }}</span><span>{{ value.flow || '—' }}</span><span>{{ value.sentiment || '—' }}</span></div></div></details>
                <details><summary>乐观 / 基准 / 悲观情景</summary><div class="scenario-list"><div v-for="scenario in aiResult.decision_center.scenarios" :key="scenario.name"><b>{{ scenario.name }}</b><span>{{ probability(scenario.probability) }}</span><small>目标 {{ scenario.target || '区间' }}</small></div></div></details>
                <details v-if="aiResult.decision_center.research"><summary>跨资产滚动相关</summary><div class="level-list"><div v-for="pair in aiResult.decision_center.research.cross_asset.correlations" :key="pair.pair"><b>{{ pair.pair }}</b><span>{{ pair.correlation }} · {{ pair.samples }} 样本</span></div><p v-if="!aiResult.decision_center.research.cross_asset.correlations.length" class="data-warning">{{ aiResult.decision_center.research.cross_asset.reason }}</p></div></details>
                <details v-if="aiResult.decision_center.research"><summary>MAE / MFE 路径风险与触达概率</summary><div v-if="aiResult.decision_center.research.path_risk.status === 'AVAILABLE'" class="validation-grid"><div><span>样本</span><b>{{ aiResult.decision_center.research.path_risk.samples }}</b></div><div><span>MAE 中位数</span><b>{{ probability(aiResult.decision_center.research.path_risk.mae.median) }}</b></div><div><span>MFE 中位数</span><b>{{ probability(aiResult.decision_center.research.path_risk.mfe.median) }}</b></div><div><span>止损触发概率</span><b>{{ probability(aiResult.decision_center.research.path_risk.stop_hit_probability) }}</b></div><div v-for="tp in aiResult.decision_center.research.path_risk.take_profit_probabilities" :key="tp.name"><span>{{ tp.name }} 历史触达</span><b>{{ probability(tp.historical_hit_probability) }}</b></div></div><p v-else class="data-warning">路径历史样本不足，未生成概率。</p></details>
                <details v-if="aiResult.decision_center.research"><summary>结构化新闻与去重</summary><div class="level-list"><div v-for="event in aiResult.decision_center.research.news_events.events" :key="event.event_id"><b>{{ event.event_type }} · {{ event.direction }}</b><span>{{ event.title }} · {{ event.publication_time || '时间未知' }}</span></div><p class="data-warning">重复 {{ aiResult.decision_center.research.news_events.duplicate_count }} 条；历史训练状态 {{ aiResult.decision_center.research.news_events.historical_training_status }}</p></div></details>
                <details v-if="aiResult.decision_center.research"><summary>预测失效条件</summary><div class="level-list"><div v-for="condition in aiResult.decision_center.research.invalidation_conditions" :key="condition.condition"><b>{{ condition.condition }}</b><span>{{ condition.level ?? condition.current ?? '触发即重新计算' }}</span></div><p>本预测到 {{ aiResult.decision_center.research.prediction_lifecycle.expires_at }} 自动过期。</p></div></details>
                <details v-if="aiResult.decision_center.research"><summary>因子增量价值审计</summary><div class="level-list"><div v-for="(audit,name) in aiResult.decision_center.research.feature_ablation.experiments" :key="name"><b>{{ name }} · Sharpe {{ audit.sharpe }}</b><span>Accuracy {{ probability(audit.accuracy) }} · IC {{ audit.ic }} · Return {{ probability(audit.return) }}</span></div><div v-for="(reason,name) in aiResult.decision_center.research.feature_ablation.not_testable" :key="name"><b>{{ name }}</b><span>{{ reason }}</span></div></div></details>
                <details><summary>当前外部数据与来源</summary><div class="level-list"><div v-for="(context,name) in aiResult.decision_center.external_context" :key="name"><b>{{ name }} · {{ context.status }}</b><span>{{ context.source || '未配置/不适用' }}</span></div></div></details>
                <details><summary>历史预测与风险模型验证</summary><div v-if="predictionStats?.overall?.samples" class="validation-grid"><div><span>已到期样本</span><b>{{ predictionStats.overall.samples }}</b></div><div><span>Accuracy</span><b>{{ probability(predictionStats.overall.accuracy) }}</b></div><div><span>F1 Macro</span><b>{{ probability(predictionStats.overall.f1_macro) }}</b></div><div><span>Brier Score</span><b>{{ predictionStats.overall.brier_score }}</b></div><div><span>Stop Hit</span><b>{{ probability(predictionStats.overall.stop_hit_rate) }}</b></div><div><span>TP Hit</span><b>{{ probability(predictionStats.overall.tp_hit_rate) }}</b></div><div><span>Average R</span><b>{{ predictionStats.overall.average_r ?? '—' }}</b></div><div><span>Profit Factor</span><b>{{ predictionStats.overall.profit_factor ?? '—' }}</b></div></div><p v-else class="data-warning">暂无已到期预测样本。系统已保存本次预测，到达目标时间并取得真实行情后才会统计，绝不预填成绩。</p></details>
                <el-alert v-if="aiResult.decision_center.regime_change_risk.active" title="市场状态可能发生变化" type="warning" show-icon :closable="false" />
                <p class="data-warning">事件风险：{{ aiResult.decision_center.event_risk.status }}。未配置可验证事件日历时，系统不会编造宏观事件。</p>
              </section>
              <div class="model-info">
                引擎：{{ aiResult.model.name }} ·
                {{ aiResult.model.models.join(" + ") }}<br />{{
                  aiResult.model.split
                }}<br />数据时间：{{ aiResult.data_time }}<br />{{
                  aiResult.risk_notice
                }}
              </div></template
            >
          </div>
          <div class="panel">
            <div class="panel-top">
              <h3>历史回测</h3>
              <button
                class="primary"
                @click="runBacktest"
                :disabled="backtestLoading"
              >
                {{ backtestLoading ? "运行中…" : "开始回测" }}
              </button>
            </div>
            <div class="form-row">
              <select v-model="strategy">
                <option value="ma">MA 金叉/死叉</option>
                <option value="macd">MACD</option>
                <option value="rsi">RSI</option>
                <option value="ai">AI 趋势</option>
                <option value="ai_technical">AI + 技术指标</option>
                <option value="breakout">V5 突破</option>
                <option value="pullback">V5 回撤</option>
                <option value="moving_average">V5 四均线</option>
                <option value="bollinger">V5 布林带</option>
                <option value="rsi_reversal">V5 RSI反转</option>
                <option value="fibonacci">V5 Fibonacci</option>
                <option value="bos">V5 BOS</option>
                <option value="fvg">V5 FVG</option>
                <option value="fib_fvg_bos">V5 Fib+FVG+BOS</option></select
              ><input
                v-model.number="initialCash"
                type="number"
                min="100"
              /><span>初始资金</span>
            </div>
            <div v-if="backtestResult" class="backtest-metrics">
              <div>
                <span>最终资金</span><b>{{ backtestResult.final_cash }}</b>
              </div>
              <div>
                <span>收益率</span
                ><b :class="trendClass(backtestResult.return_percent)"
                  >{{ backtestResult.return_percent }}%</b
                >
              </div>
              <div>
                <span>最大回撤</span
                ><b>{{ backtestResult.max_drawdown_percent }}%</b>
              </div>
              <div>
                <span>胜率</span><b>{{ backtestResult.win_rate_percent }}%</b>
              </div>
              <div>
                <span>夏普比率</span><b>{{ backtestResult.sharpe_ratio }}</b>
              </div>
              <div>
                <span>索提诺比率</span><b>{{ backtestResult.sortino_ratio }}</b>
              </div>
              <div>
                <span>交易次数</span><b>{{ backtestResult.trade_count }}</b>
              </div>
              <div>
                <span>盈利因子</span
                ><b>{{ backtestResult.profit_factor ?? "—" }}</b>
              </div>
              <div>
                <span>手续费 / 滑点</span
                ><b
                  >{{ probability(backtestResult.fee_rate) }} /
                  {{ probability(backtestResult.slippage_rate) }}</b
                >
              </div>
            </div>
            <EquityChart
              v-if="backtestResult"
              :curve="backtestResult.equity_curve"
            />
            <details v-if="backtestResult?.walk_forward"><summary>Walk-forward / Purged / Embargo</summary><p class="data-warning">{{ backtestResult.walk_forward.status }} · {{ backtestResult.walk_forward.method }} · 样本外交易 {{ backtestResult.walk_forward.out_of_sample_trades }}</p><div class="level-list"><div v-for="fold in backtestResult.walk_forward.folds" :key="fold.fold"><b>Fold {{ fold.fold }} · EV {{ fold.expectancy }} · Sharpe {{ fold.sharpe }}</b><span>{{ fold.test_start }} → {{ fold.test_end }} · embargo {{ fold.embargo_bars }}</span></div></div></details>
            <details v-if="strategyLeaderboard.length" class="strategy-leaderboard"><summary>策略排行榜（真实已保存回测）</summary><div class="table-row order"><b>策略</b><span>胜率</span><span>EV / PF</span><span>Sharpe</span><span>交易数</span></div><div v-for="row in strategyLeaderboard" :key="`${row.symbol}-${row.interval}-${row.strategy}`" class="table-row order"><b>{{ strategyLabel(row.strategy) }} · {{ row.symbol }} {{ row.interval }}</b><span>{{ probability(row.win_rate) }}</span><span>{{ row.expectancy ?? '—' }} / {{ row.profit_factor ?? '—' }}</span><span>{{ row.sharpe ?? '—' }}</span><span>{{ row.number_of_trades }}</span></div></details>
            <div v-else class="empty">
              真实历史行情回测，计入手续费和滑点；AI 策略只用样本外信号。
            </div>
          </div>
        </section>
        <section class="panel trade-panel">
          <div>
            <h3>模拟交易</h3>
            <p>成交价格由当前实时行情 API 决定，手续费自动记录。</p>
          </div>
          <input v-model.number="orderAmount" type="number" min="1" /><span
            >{{ selected?.asset_type === "crypto" ? "USDT" : "CNY" }} 金额</span
          ><button
            class="buy"
            @click="placeOrder('BUY')"
            :disabled="orderLoading"
          >
            模拟买入</button
          ><button
            class="sell"
            @click="placeOrder('SELL')"
            :disabled="orderLoading"
          >
            模拟卖出
          </button>
        </section></template
      >

      <template v-else-if="page === 'paper'">
        <el-alert title="模拟交易，不涉及真实资金；所有成交仅写入本机数据库。" type="info" show-icon :closable="false" />
        <div v-if="paperLoading" class="loading-box">正在按真实行情更新挂单、账户与持仓盈亏…</div>
        <div class="account-grid"><div v-for="a in paperAccounts" :key="a.currency" class="account-card"><span>{{ a.currency }} 模拟账户 · 总资产</span><b>{{ price(a.total_equity,a.currency) }}</b><small>可用 {{ price(a.available_cash,a.currency) }} · 冻结 {{ price(a.frozen_cash,a.currency) }} · 持仓 {{ price(a.position_market_value,a.currency) }}</small><small :class="trendClass(a.today_pnl)">今日盈亏 {{ price(a.today_pnl,a.currency) }}</small><small :class="trendClass(a.cumulative_pnl)">累计盈亏 {{ price(a.cumulative_pnl,a.currency) }} · 收益 {{ a.return_percent }}%</small></div></div>
        <section class="paper-layout">
          <div class="panel order-ticket"><div class="panel-top"><h3>下单面板</h3><span class="realtime-status"><i></i>{{ realtimeMarketStore.connectionStatus.value }}</span></div><p>在顶部搜索并选择股票或币种，新闻/AI/策略页也可带入标的。</p><div class="selected-order-asset"><b>{{ selected?.name || '尚未选择标的' }}</b><span>{{ selected?.symbol || '—' }} · {{ quote?.price || selectedLiveState.quote?.price || '等待实时价' }}</span></div><label>订单类型<select v-model="orderType"><option value="MARKET">市价</option><option value="LIMIT">限价</option></select></label><label>数量<input v-model.number="orderQuantity" type="number" min="0.000001" step="any" /></label><label v-if="orderType==='LIMIT'">限价<input v-model.number="orderLimitPrice" type="number" min="0.000001" step="any" /></label><div class="order-actions"><button class="buy" @click="submitPaperOrder('BUY')" :disabled="orderLoading||!selected">确认买入</button><button class="sell" @click="submitPaperOrder('SELL')" :disabled="orderLoading||!selected">确认卖出</button></div><p class="data-warning">市价单按当前真实报价成交；限价买 ≤ 限价、限价卖 ≥ 限价时成交。系统不会自动替你确认下单。</p></div>
          <div class="panel"><div class="panel-top"><h3>实时持仓</h3><button @click="resetPaper">重置模拟账户</button></div><div v-if="!positions.length" class="empty">暂无持仓。请搜索标的并在左侧下单。</div><div v-for="p in positions" :key="p.asset_type+p.symbol" class="position-row"><button class="link-button" @click="openPosition(p)">{{ p.symbol }}</button><span>持仓 {{ p.quantity.toFixed(6) }}</span><span>可卖 {{ (p.quantity-(p.frozen_quantity||0)).toFixed(6) }}</span><span>成本 {{ p.average_cost.toFixed(2) }}</span><span>现价 {{ p.current_price??'行情不可用' }}</span><b :class="trendClass(p.unrealized_pnl)">{{ p.unrealized_pnl??'—' }}（{{ p.return_percent??'—' }}%）</b><button @click="sellAll(p)">全部卖出</button></div></div>
        </section>
        <section class="panel"><h3>我的订单</h3><div class="paper-order-head"><span>时间</span><span>标的</span><span>方向/类型</span><span>数量 × 价格</span><span>状态</span><span>操作</span></div><div v-for="o in orders" :key="o.id" class="paper-order-row"><small>{{ o.created_at }}</small><b>{{ o.symbol }}</b><span>{{ o.side }} / {{ o.order_type }}</span><span>{{ o.quantity.toFixed(6) }} × {{ o.limit_price||o.price }}</span><strong :class="o.status==='filled'?'positive':o.status==='cancelled'?'negative':'neutral'">{{ o.status }}</strong><button v-if="o.status==='pending'" @click="cancelOrder(o.id)">撤单</button><span v-else>手续费 {{ o.fee.toFixed(4) }}</span></div><div v-if="!orders.length" class="empty">暂无订单记录。</div></section>
      </template>

      <template v-else-if="page === 'watchlist'"
        ><section class="panel">
          <h3>持久化自选</h3>
          <p class="muted">保存在本机 SQLite，关闭软件后仍然存在。</p>
          <div class="grid">
            <button
              v-for="w in watchlist"
              :key="w.symbol"
              class="card compact"
              @click="
                openAsset({
                  symbol: w.symbol,
                  name: w.name || w.symbol,
                  asset_type: w.asset_type,
                })
              "
            >
              <div class="asset">
                <div :class="w.asset_type === 'crypto' ? 'coin' : 'stock'">
                  {{ (w.name || w.symbol)[0] }}
                </div>
                <div>
                  <b>{{ w.name || w.symbol }}</b
                  ><small
                    >{{ w.symbol }} ·
                    {{ w.asset_type === "crypto" ? "数字资产" : "A股" }}</small
                  >
                </div>
              </div>
              <div class="card-action">打开完整分析 →</div>
            </button>
          </div>
        </section></template
      >
      <template v-else-if="page === 'settings'"
        ><section class="panel settings-card">
          <span class="eyebrow">APPLICATION UPDATE</span>
          <h2>AI行情助手 v{{ appVersion }}</h2>
          <p class="muted">
            正式更新通道：GitHub Releases<br />{{ updateStatus }}
          </p>
          <button
            class="primary"
            @click="checkUpdates"
            :disabled="updateChecking"
          >
            {{ updateChecking ? "正在检查…" : "检查更新" }}
          </button>
        </section>
        <section class="panel">
          <h3>用户数据</h3>
          <p class="muted">
            数据库、设置、自选、模拟交易和回测记录保存在
            %APPDATA%\AI行情助手，升级程序不会覆盖这些数据。
          </p>
        </section></template
      >
      <el-dialog v-model="newsDialogOpen" title="新闻事件详情" width="760px" append-to-body>
        <div v-if="newsSelected" class="news-detail-dialog">
          <span class="eyebrow">已发生 · 新闻事实</span><h2>{{ newsSelected.title }}</h2>
          <p>{{ newsSelected.summary }}</p><small>{{ newsSelected.published_at?.replace('T',' ').slice(0,19) }} · {{ newsSelected.source }} · {{ newsSelected.market }}</small>
          <h3 class="analysis-divider">AI判断 <span :class="newsClass(newsSelected)">{{ newsSelected.event.direction }}</span></h3>
          <div class="impact-banner"><b>Impact {{ newsSelected.impact.score }}/100</b><span>{{ stars(newsSelected.impact.score) }} · 可信度 {{ Math.round(newsSelected.event.confidence*100) }}%</span></div>
          <h3>为什么这样判断</h3><ol><li v-for="reason in newsSelected.reason" :key="reason">{{ reason }}</li></ol>
          <div class="two-col"><div><h3>直接影响</h3><p v-for="x in newsSelected.impact.primary" :key="x.target"><b>{{ x.target }} · {{ x.direction }}</b><br>{{ x.reason }}</p><p v-if="!newsSelected.impact.primary.length">未识别到可验证的直接标的，不强行关联。</p></div><div><h3>行业 / 间接影响</h3><p v-for="x in newsSelected.impact.secondary" :key="x.target"><b>{{ x.target }} · {{ x.direction }}</b><br>{{ x.reason }}</p></div></div>
          <h3>潜在反向影响 / 风险</h3><p v-for="x in newsSelected.impact.counter" :key="x.target"><b>{{ x.target }}</b>：{{ x.reason }}</p><p v-if="!newsSelected.impact.counter.length">规则引擎未识别到明确反向影响。</p>
          <template v-if="newsSelected.historical_outcome"><h3>新闻发布后真实市场表现</h3><div class="backtest-metrics"><div v-for="(value,key) in newsSelected.historical_outcome.returns" :key="key"><span>{{ key }}</span><b :class="trendClass(value as number)">{{ probability(value as number) }}</b></div></div><p>回测入场：{{ newsSelected.historical_outcome.entry_time }} · {{ newsSelected.historical_outcome.entry_price }}</p></template>
          <p v-else class="data-warning">该新闻尚未与足够的后续真实价格完成对齐，不展示虚构收益。</p>
          <h3 class="analysis-divider">市场预测</h3><div class="prediction-grid"><article v-for="(p,h) in newsSelected.market_prediction" :key="h"><b>{{ h }}</b><p title="未校准证据估计，不是保证收益。">上涨 {{ p.up }}% · 震荡 {{ p.flat }}% · 下跌 {{ p.down }}%</p><small>{{ p.validated_samples }} 个已验证样本 · {{ p.type }}</small></article></div><p class="data-warning">预测依据：新闻影响 {{ newsSelected.prediction_basis?.news_impact ?? '—' }} · 技术评分 {{ newsSelected.prediction_basis?.technical_score ?? '暂无' }} · 量能 {{ newsSelected.prediction_basis?.volume_ratio ?? '暂无' }} · 综合 {{ newsSelected.prediction_basis?.composite_evidence_score ?? '—' }}。{{ newsSelected.prediction_basis?.notice }}</p>
          <div class="dialog-actions"><button v-for="symbol in newsSelected.symbols" :key="symbol" @click="openNewsSymbol(symbol)">查看 {{ symbol }}</button><button v-if="newsSelected.symbols?.length" @click="tradeNewsSymbol(newsSelected.symbols[0])">模拟交易</button><a :href="newsSelected.url" target="_blank">查看原文</a></div>
        </div>
      </el-dialog>
      <footer>
        所有行情来自公开真实数据源；预测和回测不构成投资建议。<span
          >AI行情助手 v{{ appVersion }}</span
        >
      </footer>
    </main>
  </div>
</template>
