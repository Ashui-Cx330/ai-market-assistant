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

type Page = "home" | "detail" | "news" | "paper" | "watchlist" | "settings";
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
  newsBacktest = ref<any>(null);
const orderAmount = ref(1000),
  orderLoading = ref(false),
  watchlist = ref<any[]>([]),
  paperAccounts = ref<any[]>([]),
  positions = ref<any[]>([]),
  orders = ref<any[]>([]),
  paperLoading = ref(false);
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
async function openAsset(asset: Asset, action?: "ai" | "backtest") {
  selected.value = asset;
  page.value = "detail";
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
    const params = target
      ? `?symbol=${encodeURIComponent(target.symbol)}&asset_type=${target.asset_type}&name=${encodeURIComponent(target.name)}`
      : "";
    newsIntelligence.value = await request<any>(`/api/news/intelligence${params}`);
  } catch (e) {
    newsError.value = e instanceof Error ? e.message : "新闻数据源暂不可用";
  } finally {
    newsLoading.value = false;
  }
}

async function showNews() {
  page.value = "news";
  await loadNews();
}

async function runNewsBacktest() {
  if (!selected.value) return;
  newsBacktest.value = await post<any>("/api/news/backtest", {
    symbol: selected.value.symbol,
    asset_type: selected.value.asset_type,
    interval: interval.value,
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
    ElMessage.error(e instanceof Error ? e.message : "AI预测失败");
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
    [paperAccounts.value, positions.value, orders.value] = await Promise.all([
      request<any[]>("/api/paper/account"),
      request<any[]>("/api/paper/positions"),
      request<any[]>("/api/paper/orders"),
    ]);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "账户数据获取失败");
  } finally {
    paperLoading.value = false;
  }
}
async function showPaper() {
  page.value = "paper";
  await loadPaper();
}
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
function nav(
  target:
    "home" | "market" | "ai" | "backtest" | "news" | "paper" | "watchlist" | "settings",
) {
  if (target === "home") {
    page.value = "home";
    loadHome();
  } else if (target === "market") {
    page.value = "home";
    nextTick(() =>
      document.querySelector<HTMLInputElement>(".search input")?.focus(),
    );
  } else if (target === "paper") showPaper();
  else if (target === "news") showNews();
  else if (target === "watchlist") showWatchlist();
  else if (target === "settings") page.value = "settings";
  else
    openAsset({ symbol: "BTC", name: "比特币", asset_type: "crypto" }, target);
}
const removeRealtimeListener=realtimeMarketStore.onEvent(handleRealtime);
onMounted(()=>{loadHome();realtimeMarketStore.connect()});
onBeforeUnmount(()=>{removeRealtimeListener();realtimeMarketStore.close()});
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
        <button @click="nav('market')">
          <el-icon><TrendCharts /></el-icon>行情搜索
        </button>
        <button @click="nav('ai')">
          <el-icon><DataAnalysis /></el-icon>AI 预测
        </button>
        <button :class="{ active: page === 'news' }" @click="nav('news')">
          <el-icon><Bell /></el-icon>新闻情报
        </button>
        <button @click="nav('backtest')">
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
          @click="
            page === 'home'
              ? loadHome()
              : page === 'news'
                ? loadNews()
              : page === 'paper'
                ? loadPaper()
                : page === 'detail'
                  ? (loadQuote(), loadKline())
                  : loadWatchlist()
          "
        >
          <el-icon :class="{ spin: loading || detailLoading || paperLoading }"
            ><Refresh /></el-icon
          >刷新
        </button>
      </header>

      <div class="search">
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
              @click="openAsset(asset)"
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

      <template v-else-if="page === 'news'">
        <el-alert v-if="newsError" :title="newsError" type="error" show-icon :closable="false">
          <button @click="loadNews()">重试</button>
        </el-alert>
        <div v-if="newsLoading" class="loading-box">正在采集真实公开新闻并执行事件分析…</div>
        <template v-else-if="newsIntelligence">
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
          <section class="panel"><div class="panel-top"><div><h3>今日最重要的 10 条新闻</h3><p>按事件影响分排序，不按发布时间冒充重要性</p></div><small>{{ newsIntelligence.method }}</small></div>
            <div class="news-list"><article v-for="item in newsIntelligence.top_news" :key="item.id">
              <div class="news-score" :class="item.sentiment.score >= 10 ? 'positive' : item.sentiment.score <= -10 ? 'negative' : ''">{{ item.sentiment.score > 0 ? '+' : '' }}{{ item.sentiment.score }}</div>
              <div><a :href="item.url" target="_blank">{{ item.title }}</a><p>{{ item.category }} · {{ item.event.event_type }} · 影响 {{ item.impact.score }} · {{ item.source }}</p><small>{{ item.published_at?.replace('T',' ').slice(0,19) || '发布时间未知（禁止进入回测）' }}</small>
                <details><summary>事件影响图谱</summary><p v-for="impact in [...item.impact.primary,...item.impact.secondary,...item.impact.counter]" :key="impact.target"><b>{{ impact.target }} · {{ impact.direction }}</b> — {{ impact.reason }}</p></details>
              </div>
            </article></div>
          </section>
          <p class="data-warning">Point-in-Time：{{ newsIntelligence.point_in_time }} · 数据源异常数 {{ newsIntelligence.provider_errors?.length || 0 }}</p>
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
              selected.asset_type === "crypto" ? "CRYPTO" : "A-SHARE"
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
            </div>
          </div>
          <div v-if="detailLoading" class="loading-box">
            正在获取 {{ interval.toUpperCase() }} 真实 K线…
          </div>
          <KlineChart v-else :candles="candles" :indicators="indicators" :structure="aiResult?.decision_center?.technical_strategy" :news="newsIntelligence?.top_news || []" />
        </section>
        <section v-if="newsIntelligence" class="panel">
          <div class="panel-top"><div><h3>个股 / 币种 AI 情报</h3><p>新闻 → 事件 → 影响 → 技术面融合</p></div><button @click="runNewsBacktest">新闻策略回测</button></div>
          <div class="decision-bars"><span>BUY {{ newsIntelligence.decision.scores.buy }}</span><span>HOLD {{ newsIntelligence.decision.scores.hold }}</span><span>AVOID {{ newsIntelligence.decision.scores.avoid }}</span></div>
          <h3>{{ newsIntelligence.decision.view }}</h3>
          <div class="news-list compact-news"><article v-for="item in newsIntelligence.top_news.slice(0,5)" :key="item.id"><div class="news-score" :class="item.sentiment.score >= 10 ? 'positive' : item.sentiment.score <= -10 ? 'negative' : ''">{{ item.sentiment.score }}</div><div><a :href="item.url" target="_blank">{{ item.title }}</a><p>{{ item.event.direction }} · {{ item.event.event_type }} · 影响 {{ item.impact.score }}</p></div></article></div>
          <p v-if="newsBacktest" class="data-warning">新闻回测：{{ newsBacktest.status }} · 样本 {{ newsBacktest.samples }} · {{ newsBacktest.notice || `T+5 胜率 ${probability(newsBacktest.win_rate_t5)}` }}</p>
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
              <span>MACD</span><b>{{ indicators.latest.macd?.toFixed(4) }}</b>
            </div>
            <div>
              <span>RSI(14)</span><b>{{ indicators.latest.rsi?.toFixed(2) }}</b>
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
                    <article><span>市场结构</span><b>{{ aiResult.decision_center.technical_strategy.structure.trend }}</b><small>BOS {{ aiResult.decision_center.technical_strategy.structure.latest_bos?.direction || 'NONE' }} · CHoCH {{ aiResult.decision_center.technical_strategy.structure.latest_choch?.direction || 'NONE' }}</small></article>
                    <article><span>Fibonacci</span><b>{{ aiResult.decision_center.technical_strategy.fibonacci.status }}</b><small>{{ aiResult.decision_center.technical_strategy.fibonacci.direction || '—' }} · available_at {{ aiResult.decision_center.technical_strategy.fibonacci.available_at?.replace('T',' ').slice(0,19) || '—' }}</small></article>
                    <article><span>FVG</span><b>{{ aiResult.decision_center.technical_strategy.fvgs.filter((x:any)=>x.status!=='FILLED').length }} Open</b><small>只绘制三K线真实缺口</small></article>
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

      <template v-else-if="page === 'paper'"
        ><div v-if="paperLoading" class="loading-box">
          正在按实时行情计算账户…
        </div>
        <div class="account-grid">
          <div
            v-for="a in paperAccounts"
            :key="a.currency"
            class="account-card"
          >
            <span>{{ a.currency }} 模拟账户</span
            ><b>{{ price(a.total_equity, a.currency) }}</b
            ><small
              >可用 {{ price(a.cash, a.currency) }} · 收益
              {{ a.return_percent }}%</small
            >
          </div>
        </div>
        <section class="panel">
          <h3>实时持仓</h3>
          <div v-if="!positions.length" class="empty">
            暂无持仓，可从任意资产详情页模拟买入。
          </div>
          <div
            v-for="p in positions"
            :key="p.asset_type + p.symbol"
            class="table-row"
          >
            <b>{{ p.symbol }}</b
            ><span>数量 {{ p.quantity.toFixed(6) }}</span
            ><span>成本 {{ p.average_cost.toFixed(2) }}</span
            ><span>现价 {{ p.current_price ?? "行情不可用" }}</span
            ><span :class="trendClass(p.return_percent)"
              >浮盈 {{ p.unrealized_pnl ?? "—" }}（{{
                p.return_percent ?? "—"
              }}%）</span
            ><button @click="sellAll(p)">全部卖出</button>
          </div>
        </section>
        <section class="panel">
          <h3>模拟订单记录</h3>
          <div v-for="o in orders" :key="o.id" class="table-row order">
            <span>#{{ o.id }}</span
            ><b>{{ o.symbol }} {{ o.side }}</b
            ><span>{{ o.quantity.toFixed(6) }} × {{ o.price }}</span
            ><span>手续费 {{ o.fee.toFixed(4) }}</span
            ><small>{{ o.created_at }}</small>
          </div>
        </section></template
      >

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
      <footer>
        所有行情来自公开真实数据源；预测和回测不构成投资建议。<span
          >AI行情助手 v{{ appVersion }}</span
        >
      </footer>
    </main>
  </div>
</template>
