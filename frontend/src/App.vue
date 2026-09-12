<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
} from "vue";
import { ElMessage } from "element-plus";
import type { Asset, Candle, IndicatorSet, Quote } from "./api";
import { post, postLong, request } from "./api";
import { realtimeMarketStore, type RealtimeEvent } from "./realtime";
import TerminalSidebar from "./TerminalSidebar.vue";
import InfoTip from "./InfoTip.vue";
import MiniChart from "./MiniChart.vue";

const KlineChart = defineAsyncComponent(() => import("./KlineChart.vue"));
const PerformanceChart = defineAsyncComponent(
  () => import("./PerformanceChart.vue"),
);

type Page =
  | "home"
  | "market"
  | "detail"
  | "watchlist"
  | "screener"
  | "prediction"
  | "modelLab"
  | "news"
  | "strategy"
  | "backtest"
  | "paper"
  | "copilot"
  | "settings";
const page = ref<Page>("home"),
  appVersion = ref("1.11.0"),
  pageLoading = ref(false),
  pageError = ref("");
const dashboard = ref<any>(null),
  scanner = ref<any>({ rows: [], errors: [] }),
  modelLab = ref<any>(null),
  dataHealth = ref<any>(null);
const scannerFilters = ref({
  query: "",
  market: "全部",
  industry: "全部",
  change: "全部",
  min_ai_score: 0,
  min_volume_ratio: 0,
  max_risk: 100,
  news_direction: "全部",
});
const scannerLoading = ref(false),
  hoveredRow = ref<any>(null),
  watchlist = ref<any[]>([]),
  watchRows = ref<any[]>([]),
  watchSort = ref("score");
const query = ref(""),
  searching = ref(false),
  searchOpen = ref(false),
  searchResults = ref<Asset[]>([]),
  searchError = ref("");
const searchIndex = ref(0);
const selected = ref<Asset | null>(null),
  quote = ref<Quote | null>(null),
  candles = ref<Candle[]>([]),
  indicators = ref<IndicatorSet | null>(null),
  assetAnalysis = ref<any>(null);
const interval = ref("1d"),
  detailLoading = ref(false),
  detailError = ref(""),
  priceFlash = ref("");
const periods = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"];
const aiResult = ref<any>(null),
  aiQuick = ref<any>(null),
  aiLoading = ref(false),
  aiError = ref("");
const newsIntelligence = ref<any>(null),
  newsLoading = ref(false),
  newsError = ref(""),
  newsDirection = ref("全部"),
  newsSelected = ref<any>(null),
  newsDialogOpen = ref(false);
const newsReport = ref<any>(null),
  newsReportAsset = ref<Asset | null>(null),
  newsReportLoading = ref(false),
  newsReportError = ref("");
const marketIntel = ref<any>(null),
  marketIntelLoading = ref(false),
  marketIntelError = ref(""),
  marketIntelJob = ref<any>(null);
const strategyText = ref("帮我测试RSI低于30后买入，持有5天。"),
  parsedRule = ref<any>(null),
  strategy = ref("ma"),
  initialCash = ref(100000),
  backtestResult = ref<any>(null),
  backtestLoading = ref(false);
const paperAccounts = ref<any[]>([]),
  positions = ref<any[]>([]),
  orders = ref<any[]>([]),
  paperLoading = ref(false),
  paperTab = ref("orders");
const orderQuantity = ref(1),
  orderType = ref("MARKET"),
  orderLimitPrice = ref<number | null>(null),
  pendingSide = ref<"BUY" | "SELL">("BUY"),
  orderConfirmOpen = ref(false),
  orderLoading = ref(false);
const copilotOpen = ref(false),
  copilotInput = ref(""),
  copilotMessages = ref<any[]>([
    {
      role: "assistant",
      text: "我会调用行情、K线、指标、新闻或筛选器后回答。试试“分析NVDA”或“比较NVDA和AMD”。",
    },
  ]),
  copilotLoading = ref(false);
const updateChecking = ref(false),
  updateStatus = ref("启动时自动检查更新，也可手动检查。");
let paperTimer: number | null = null;
let scannerRequestId = 0;
let searchTimer: number | null = null;
let searchController: AbortController | null = null;
let intelligenceTimer: number | null = null;
const intelligenceRequested = new Set<string>();

const selectedKey = computed(() =>
  selected.value
    ? realtimeMarketStore.key(
        selected.value.asset_type,
        selected.value.symbol,
        interval.value,
      )
    : "",
);
const liveState = computed(
  () => realtimeMarketStore.states[selectedKey.value] || {},
);
const liveStatus = computed(() =>
  page.value === "detail"
    ? liveState.value.connectionStatus ||
      realtimeMarketStore.connectionStatus.value
    : realtimeMarketStore.connectionStatus.value,
);
const predictionRows = computed(() =>
  Object.entries(aiResult.value?.predictions || {})
    .map(([h, value]: any) => ({ horizon: h === "1D" ? "T+1" : h, ...value }))
    .filter((x: any) => ["T+1", "T+5", "T+20"].includes(x.horizon)),
);
const inWatchlist = computed(
  () =>
    !!selected.value &&
    watchlist.value.some(
      (x) =>
        x.symbol === selected.value?.symbol &&
        x.asset_type === selected.value?.asset_type,
    ),
);
const sortedWatchRows = computed(() =>
  [...watchRows.value].sort((a, b) =>
    watchSort.value === "change"
      ? (b.change_percent || 0) - (a.change_percent || 0)
      : watchSort.value === "risk"
        ? (a.components?.risk || 100) - (b.components?.risk || 100)
        : (b.ai_score || 0) - (a.ai_score || 0),
  ),
);
const paperTotals = computed(() => ({
  equity: paperAccounts.value.reduce(
    (s, x) => s + Number(x.total_equity || x.cash || 0),
    0,
  ),
  cash: paperAccounts.value.reduce(
    (s, x) => s + Number(x.available_cash || x.cash || 0),
    0,
  ),
  market: positions.value.reduce((s, x) => s + Number(x.market_value || 0), 0),
  pnl: positions.value.reduce((s, x) => s + Number(x.unrealized_pnl || 0), 0),
}));

function money(value: any, currency = "") {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return (
    (currency === "CNY" ? "¥" : "$") +
    Number(value).toLocaleString("zh-CN", {
      maximumFractionDigits: Number(value) < 10 ? 4 : 2,
    })
  );
}
function number(value: any, digits = 2) {
  return value == null || !Number.isFinite(Number(value))
    ? "—"
    : Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits });
}
function pct(value: any) {
  return value == null
    ? "—"
    : `${Number(value) >= 0 ? "+" : ""}${Number(value).toFixed(2)}%`;
}
function probability(value: any) {
  return value == null ? "—" : `${(Number(value) * 100).toFixed(1)}%`;
}
function tone(value: any) {
  return Number(value || 0) > 0
    ? "positive"
    : Number(value || 0) < 0
      ? "negative"
      : "neutral";
}
function statusTone(value: string) {
  return value === "Trading" || value === "CONNECTED" || value === "AVAILABLE"
    ? "ok"
    : value === "Pre-market" || value === "WARNING"
      ? "warn"
      : "off";
}
function timeLabel(value: any) {
  return value
    ? String(value).replace("T", " ").replace("Z", "").slice(0, 19)
    : "—";
}
function assetFrom(row: any): Asset {
  return {
    symbol: row.symbol,
    name: row.name || row.symbol,
    asset_type: row.asset_type,
    price: row.price,
    change_percent: row.change_percent,
    currency: row.currency,
  };
}

async function loadHome(force = false) {
  pageLoading.value = true;
  pageError.value = "";
  try {
    dashboard.value = await request<any>(
      `/api/terminal/dashboard${force ? "?force=true" : ""}`,
    );
    appVersion.value =
      (await fetch("/api/health").then((x) => x.json())).version ||
      appVersion.value;
    for (const row of dashboard.value.opportunities || [])
      realtimeMarketStore.subscribe(row.asset_type, row.symbol, "1m");
  } catch (e) {
    pageError.value = e instanceof Error ? e.message : "市场智能数据暂不可用";
  } finally {
    pageLoading.value = false;
  }
}
async function runScanner() {
  const requestId = ++scannerRequestId;
  scannerLoading.value = true;
  pageError.value = "";
  try {
    const result = await post<any>(
      "/api/terminal/scanner",
      scannerFilters.value,
    );
    if (requestId !== scannerRequestId) return;
    scanner.value = result;
    if (!result.rows.length && result.errors.length)
      pageError.value = "部分公开数据源不可用，当前没有可展示结果。";
  } catch (e) {
    if (requestId === scannerRequestId)
      pageError.value = e instanceof Error ? e.message : "筛选器暂不可用";
  } finally {
    if (requestId === scannerRequestId) scannerLoading.value = false;
  }
}
async function loadModelLab() {
  pageLoading.value = true;
  try {
    modelLab.value = await request<any>("/api/terminal/model-lab");
  } catch (e) {
    pageError.value = e instanceof Error ? e.message : "模型记录读取失败";
  } finally {
    pageLoading.value = false;
  }
}
async function loadDataHealth() {
  try {
    dataHealth.value = await request<any>("/api/terminal/data-health");
  } catch (e) {
    pageError.value = e instanceof Error ? e.message : "健康状态读取失败";
  }
}
async function loadWatchlist() {
  watchlist.value = await request<any[]>("/api/watchlist");
  const all = await post<any>("/api/terminal/scanner", {
    ...scannerFilters.value,
    query: "",
  }).catch(() => ({ rows: [] }));
  watchRows.value = watchlist.value.map(
    (x) =>
      all.rows.find(
        (r: any) => r.symbol === x.symbol && r.asset_type === x.asset_type,
      ) || { ...x, unavailable: true },
  );
}
async function searchAssets() {
  const text = query.value.trim();
  if (!text) {
    searchOpen.value = false;
    return;
  }
  searchController?.abort();
  const controller = new AbortController();
  searchController = controller;
  searching.value = true;
  searchOpen.value = true;
  searchError.value = "";
  searchIndex.value = 0;
  try {
    const results = await Promise.allSettled([
      request<Asset[]>(
        `/api/market/stock/search?q=${encodeURIComponent(text)}`,
        { signal: controller.signal },
      ),
      request<Asset[]>(
        `/api/market/crypto/search?q=${encodeURIComponent(text)}`,
        { signal: controller.signal },
      ),
    ]);
    if (controller.signal.aborted) return;
    searchResults.value = results
      .flatMap((x) => (x.status === "fulfilled" ? x.value : []))
      .slice(0, 16);
    if (!searchResults.value.length)
      searchError.value = "没有找到匹配的真实资产";
  } finally {
    if (searchController === controller) {
      searching.value = false;
      searchController = null;
    }
  }
}
function scheduleSearch() {
  if (searchTimer) window.clearTimeout(searchTimer);
  if (!query.value.trim()) {
    searchOpen.value = false;
    return;
  }
  searchTimer = window.setTimeout(() => void searchAssets(), 120);
}
function searchKey(event: KeyboardEvent) {
  if (event.key === "Escape") {
    searchOpen.value = false;
    return;
  }
  if (event.key === "ArrowDown") {
    event.preventDefault();
    searchIndex.value = Math.min(
      searchResults.value.length - 1,
      searchIndex.value + 1,
    );
  }
  if (event.key === "ArrowUp") {
    event.preventDefault();
    searchIndex.value = Math.max(0, searchIndex.value - 1);
  }
  if (
    event.key === "Enter" &&
    searchOpen.value &&
    searchResults.value[searchIndex.value]
  ) {
    event.preventDefault();
    selectSearchAsset(searchResults.value[searchIndex.value]);
  }
}
async function loadAssetWorkspace() {
  if (!selected.value) return;
  detailLoading.value = true;
  detailError.value = "";
  try {
    const data = await post<any>("/api/terminal/asset-workspace", {
      symbol: selected.value.symbol,
      asset_type: selected.value.asset_type,
      name: selected.value.name,
      interval: interval.value,
      limit: 500,
    });
    quote.value = data.quote;
    candles.value = data.candles;
    indicators.value = data.indicators;
    assetAnalysis.value = data.analysis;
  } catch (e) {
    detailError.value = e instanceof Error ? e.message : "资产工作区暂不可用";
  } finally {
    detailLoading.value = false;
  }
}
async function loadMarketIntelligence(asset: Asset, auto = true) {
  const key = `${asset.asset_type}:${asset.symbol}`;
  marketIntelLoading.value = true;
  marketIntelError.value = "";
  try {
    const result = await request<any>(
      `/api/market-intelligence/${asset.asset_type}/${encodeURIComponent(asset.symbol)}`,
      { timeoutMs: 8000 },
    );
    if (`${selected.value?.asset_type}:${selected.value?.symbol}` !== key)
      return;
    marketIntel.value = result;
    if (
      auto &&
      result.status === "INSUFFICIENT_EVIDENCE" &&
      !intelligenceRequested.has(key)
    ) {
      intelligenceRequested.add(key);
      void recalculateMarketIntelligence(asset);
    }
  } catch (e) {
    if (`${selected.value?.asset_type}:${selected.value?.symbol}` === key)
      marketIntelError.value =
        e instanceof Error ? e.message : "情报缓存读取失败";
  } finally {
    if (`${selected.value?.asset_type}:${selected.value?.symbol}` === key)
      marketIntelLoading.value = false;
  }
}
async function recalculateMarketIntelligence(asset = selected.value) {
  if (!asset) return;
  marketIntelError.value = "";
  try {
    marketIntelJob.value = await post<any>(
      "/api/market-intelligence/recalculate",
      {
        symbol: asset.symbol,
        asset_type: asset.asset_type,
        interval: asset.asset_type === "crypto" ? "1h" : "1d",
      },
    );
    pollIntelligenceJob(marketIntelJob.value.job_id, asset);
  } catch (e) {
    marketIntelError.value =
      e instanceof Error ? e.message : "后台判断启动失败";
  }
}
function pollIntelligenceJob(jobId: string, asset: Asset) {
  if (intelligenceTimer) window.clearInterval(intelligenceTimer);
  let attempts = 0;
  intelligenceTimer = window.setInterval(async () => {
    attempts++;
    try {
      const job = await request<any>(`/api/intelligence-jobs/${jobId}`, {
        timeoutMs: 5000,
      });
      marketIntelJob.value = job;
      if (job.status === "COMPLETED") {
        if (intelligenceTimer) window.clearInterval(intelligenceTimer);
        intelligenceTimer = null;
        await loadMarketIntelligence(asset, false);
        ElMessage.success("AI市场情报已更新");
      } else if (job.status === "FAILED") {
        if (intelligenceTimer) window.clearInterval(intelligenceTimer);
        intelligenceTimer = null;
        marketIntelError.value = job.error || "真实模型计算失败";
      }
    } catch {}
    if (attempts >= 120 && intelligenceTimer) {
      window.clearInterval(intelligenceTimer);
      intelligenceTimer = null;
    }
  }, 2500);
}
async function openAsset(asset: Asset, route = true) {
  selected.value = asset;
  page.value = "detail";
  if (route)
    history.pushState(
      {},
      "",
      `/${asset.asset_type === "crypto" ? "crypto" : "stock"}/${encodeURIComponent(asset.symbol)}`,
    );
  searchOpen.value = false;
  quote.value = null;
  candles.value = [];
  indicators.value = null;
  assetAnalysis.value = null;
  aiResult.value = null;
  aiQuick.value = null;
  marketIntel.value = null;
  marketIntelJob.value = null;
  interval.value = asset.asset_type === "crypto" ? "1h" : "1d";
  void loadMarketIntelligence(asset);
  void loadNews(asset);
  await loadAssetWorkspace();
  realtimeMarketStore.subscribe(asset.asset_type, asset.symbol, interval.value);
}
async function changeInterval(value: string) {
  interval.value = value;
  aiResult.value = null;
  await loadAssetWorkspace();
  if (selected.value)
    realtimeMarketStore.subscribe(
      selected.value.asset_type,
      selected.value.symbol,
      value,
    );
}
function selectSearchAsset(asset: Asset) {
  if (page.value === "paper") {
    selected.value = asset;
    orderLimitPrice.value = asset.price || null;
    void loadAssetWorkspace();
    searchOpen.value = false;
    return;
  }
  if (
    page.value === "prediction" ||
    page.value === "strategy" ||
    page.value === "backtest"
  ) {
    selected.value = asset;
    interval.value = "1d";
    aiResult.value = null;
    backtestResult.value = null;
    void loadAssetWorkspace();
    searchOpen.value = false;
    return;
  }
  void openAsset(asset);
}
async function runAI() {
  if (!selected.value) return;
  aiQuick.value = assetAnalysis.value;
  aiLoading.value = true;
  aiError.value = "";
  aiResult.value = null;
  interval.value = "1d";
  try {
    aiResult.value = await postLong<any>(
      "/api/ai/decision",
      {
        symbol: selected.value.symbol,
        asset_type: selected.value.asset_type,
        interval: "1d",
        account_equity: 100000,
        max_risk_percent: 0.01,
        leverage: 1,
      },
      300000,
    );
    ElMessage.success("样本外预测与模型状态已更新");
  } catch (e) {
    aiError.value = e instanceof Error ? e.message : "预测服务暂不可用";
  } finally {
    aiLoading.value = false;
  }
}
async function loadWatchReport(asset: Asset) {
  newsReportAsset.value = asset;
  newsReport.value = null;
  newsReportError.value = "";
  newsReportLoading.value = true;
  const key = `${asset.asset_type}:${asset.symbol}`;
  try {
    const params = new URLSearchParams({
      symbol: asset.symbol,
      asset_type: asset.asset_type,
      name: asset.name || asset.symbol,
    });
    const result = await request<any>(
      `/api/terminal/watchlist-report?${params}`,
      { timeoutMs: 45000 },
    );
    if (
      `${newsReportAsset.value?.asset_type}:${newsReportAsset.value?.symbol}` ===
      key
    )
      newsReport.value = result;
  } catch (e) {
    if (
      `${newsReportAsset.value?.asset_type}:${newsReportAsset.value?.symbol}` ===
      key
    )
      newsReportError.value =
        e instanceof Error ? e.message : "评估报告暂不可用";
  } finally {
    if (
      `${newsReportAsset.value?.asset_type}:${newsReportAsset.value?.symbol}` ===
      key
    )
      newsReportLoading.value = false;
  }
}
async function loadNews(asset?: Asset, refresh = false) {
  newsLoading.value = true;
  newsError.value = "";
  try {
    const params = new URLSearchParams();
    if (asset) {
      params.set("symbol", asset.symbol);
      params.set("asset_type", asset.asset_type);
      params.set("name", asset.name);
      newsIntelligence.value = await request<any>(
        `/api/news/intelligence?${params}`,
      );
    } else {
      if (newsDirection.value !== "全部")
        params.set("direction", newsDirection.value);
      params.set("refresh", String(refresh));
      newsIntelligence.value = await request<any>(
        `/api/terminal/watchlist-news?${params}`,
      );
      const assets = (newsIntelligence.value.assets || []) as Asset[];
      const current =
        assets.find(
          (x) =>
            x.symbol === newsReportAsset.value?.symbol &&
            x.asset_type === newsReportAsset.value?.asset_type,
        ) || assets[0];
      if (current && !newsReportLoading.value && (refresh || !newsReport.value))
        void loadWatchReport(current);
    }
  } catch (e) {
    newsError.value = e instanceof Error ? e.message : "新闻数据源暂不可用";
  } finally {
    newsLoading.value = false;
  }
}
function openNews(item: any) {
  newsSelected.value = item;
  newsDialogOpen.value = true;
}
function eventImpact(item: any, period: string) {
  const value = period === "1D" ? item?.historical_outcome?.t1_return : null;
  return value == null ? "样本不可用" : pct(Number(value) * 100);
}
async function parseStrategy() {
  try {
    parsedRule.value = await post<any>("/api/terminal/strategy/parse", {
      text: strategyText.value,
    });
    if (parsedRule.value.status === "UNSUPPORTED")
      ElMessage.warning(parsedRule.value.message);
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "规则解析失败");
  }
}
async function runBacktest(natural = false) {
  if (!selected.value) return ElMessage.warning("请先搜索并选择标的");
  backtestLoading.value = true;
  backtestResult.value = null;
  try {
    if (natural) {
      if (!parsedRule.value) await parseStrategy();
      if (parsedRule.value?.status !== "PARSED")
        throw new Error("规则未能安全转换，已阻止回测");
      if (parsedRule.value.strategy === "rsi_hold")
        backtestResult.value = await post<any>(
          "/api/terminal/strategy/natural-backtest",
          {
            text: strategyText.value,
            symbol: selected.value.symbol,
            asset_type: selected.value.asset_type,
            initial_cash: initialCash.value,
          },
        );
      else
        backtestResult.value = await post<any>("/api/backtest/run", {
          symbol: selected.value.symbol,
          asset_type: selected.value.asset_type,
          interval: "1d",
          strategy: parsedRule.value.strategy,
          initial_cash: initialCash.value,
          limit: 1200,
        });
    } else
      backtestResult.value = await post<any>("/api/backtest/run", {
        symbol: selected.value.symbol,
        asset_type: selected.value.asset_type,
        interval: "1d",
        strategy: strategy.value,
        initial_cash: initialCash.value,
        limit: 1200,
      });
    ElMessage.success("真实历史回测完成");
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "回测失败");
  } finally {
    backtestLoading.value = false;
  }
}
async function loadPaper() {
  paperLoading.value = true;
  try {
    const data = await request<any>("/api/paper/snapshot");
    paperAccounts.value = data.accounts;
    positions.value = data.positions;
    orders.value = data.orders;
    for (const p of positions.value)
      realtimeMarketStore.subscribe(p.asset_type, p.symbol, "1m");
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "模拟账户读取失败");
  } finally {
    paperLoading.value = false;
  }
}
function confirmOrder(side: "BUY" | "SELL") {
  if (!selected.value) return ElMessage.warning("请先搜索交易标的");
  pendingSide.value = side;
  orderConfirmOpen.value = true;
}
async function submitOrder() {
  if (!selected.value) return;
  orderLoading.value = true;
  try {
    await post("/api/paper/order", {
      symbol: selected.value.symbol,
      asset_type: selected.value.asset_type,
      side: pendingSide.value,
      quantity: orderQuantity.value,
      order_type: orderType.value,
      price: orderType.value === "LIMIT" ? orderLimitPrice.value : null,
    });
    orderConfirmOpen.value = false;
    ElMessage.success(
      orderType.value === "LIMIT" ? "模拟限价单已提交" : "模拟市价单已成交",
    );
    await loadPaper();
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "下单失败");
  } finally {
    orderLoading.value = false;
  }
}
async function cancelOrder(id: number) {
  try {
    await post(`/api/paper/orders/${id}/cancel`, {});
    await loadPaper();
    ElMessage.success("已撤单并释放冻结资产");
  } catch (e) {
    ElMessage.error(e instanceof Error ? e.message : "撤单失败");
  }
}
async function sellAll(position: any) {
  selected.value = assetFrom(position);
  orderQuantity.value = position.quantity;
  await loadAssetWorkspace();
  confirmOrder("SELL");
}
function selectPosition(position: any) {
  selected.value = assetFrom(position);
  void loadAssetWorkspace();
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
async function askCopilot(example?: string) {
  const message = (example || copilotInput.value).trim();
  if (!message) return;
  copilotMessages.value.push({ role: "user", text: message });
  copilotInput.value = "";
  copilotLoading.value = true;
  try {
    const result = await post<any>("/api/terminal/copilot", { message });
    copilotMessages.value.push({
      role: "assistant",
      text: result.answer,
      tools: result.tool_calls,
      rows: result.rows,
      cutoff: result.data_cutoff,
    });
  } catch (e) {
    copilotMessages.value.push({
      role: "error",
      text: e instanceof Error ? e.message : "Copilot工具调用失败",
    });
  } finally {
    copilotLoading.value = false;
    await nextTick();
  }
}
async function checkUpdates() {
  if (!window.desktopUpdater)
    return ElMessage.info("请在 Windows 客户端中检查更新");
  updateChecking.value = true;
  try {
    const result = await window.desktopUpdater.check();
    updateStatus.value =
      result.status === "current"
        ? "当前已经是最新版本。"
        : result.status === "installing"
          ? "正在安装，完成后自动重启。"
          : result.status === "later"
            ? "已稍后提醒。"
            : `检查结果：${result.status}`;
  } catch {
    updateStatus.value = "更新服务暂时不可用，请稍后重试。";
  } finally {
    updateChecking.value = false;
  }
}
function handleRealtime(event: RealtimeEvent) {
  if (event.type === "ticker" && event.data?.quote) {
    const incoming = event.data.quote;
    if (selected.value && incoming.symbol === selected.value.symbol) {
      const prior = quote.value?.price || incoming.price;
      priceFlash.value =
        incoming.price > prior
          ? "flash-up"
          : incoming.price < prior
            ? "flash-down"
            : "";
      quote.value = incoming;
      setTimeout(() => (priceFlash.value = ""), 450);
    }
    const held = positions.value.find(
      (x) =>
        x.symbol === incoming.symbol && x.asset_type === incoming.asset_type,
    );
    if (held) {
      held.current_price = incoming.price;
      held.market_value = held.quantity * incoming.price;
      held.unrealized_pnl =
        held.market_value - held.quantity * held.average_cost;
      held.return_percent = (incoming.price / held.average_cost - 1) * 100;
    }
  }
  if (!selected.value || event.key !== selectedKey.value) return;
  const state = event.type === "candle" ? event.data?.state : event.data;
  if ((event.type === "snapshot" || event.type === "ticker") && state?.quote)
    quote.value = state.quote;
  if (event.type === "candle" && state) {
    if (state.quote) quote.value = state.quote;
    if (state.candles) candles.value = state.candles;
    if (state.indicators) indicators.value = state.indicators;
  }
}
const paths: Record<Page, string> = {
  home: "/",
  market: "/market",
  detail: "/",
  watchlist: "/watchlist",
  screener: "/screener",
  prediction: "/prediction",
  modelLab: "/model-lab",
  news: "/news",
  strategy: "/strategy",
  backtest: "/backtest",
  paper: "/paper",
  copilot: "/copilot",
  settings: "/settings",
};
async function nav(target: string, route = true) {
  const started = performance.now();
  page.value = target as Page;
  searchOpen.value = false;
  pageError.value = "";
  if (route) history.pushState({}, "", paths[page.value]);
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
  window.dispatchEvent(
    new CustomEvent("app:performance", {
      detail: {
        event: "navigation_skeleton",
        page: target,
        duration_ms: Number((performance.now() - started).toFixed(2)),
      },
    }),
  );
  if (target === "home") await loadHome();
  if (target === "market" || target === "screener") await runScanner();
  if (target === "watchlist") await loadWatchlist();
  if (target === "modelLab") await loadModelLab();
  if (target === "news") await loadNews();
  if (target === "settings") await loadDataHealth();
  if (target === "paper") {
    await loadPaper();
    if (paperTimer) clearInterval(paperTimer);
    paperTimer = window.setInterval(
      () => page.value === "paper" && void loadPaper(),
      5000,
    );
  }
  if (
    ["prediction", "strategy", "backtest", "paper"].includes(target) &&
    !selected.value
  ) {
    selected.value = { symbol: "NVDA", name: "NVIDIA", asset_type: "stock" };
    interval.value = "1d";
    await loadAssetWorkspace();
  }
  if (target === "copilot") copilotOpen.value = true;
  window.dispatchEvent(
    new CustomEvent("app:performance", {
      detail: {
        event: "navigation_end",
        page: target,
        duration_ms: Number((performance.now() - started).toFixed(2)),
      },
    }),
  );
}
function restoreRoute() {
  const detail = location.pathname.match(/^\/(stock|crypto)\/([^/]+)/);
  if (detail) {
    void openAsset(
      {
        symbol: decodeURIComponent(detail[2]),
        name: decodeURIComponent(detail[2]),
        asset_type: detail[1] === "crypto" ? "crypto" : "stock",
      },
      false,
    );
    return;
  }
  const map: Record<string, Page> = {
    "/": "home",
    "/market": "market",
    "/watchlist": "watchlist",
    "/screener": "screener",
    "/prediction": "prediction",
    "/model-lab": "modelLab",
    "/news": "news",
    "/strategy": "strategy",
    "/backtest": "backtest",
    "/paper": "paper",
    "/copilot": "copilot",
    "/settings": "settings",
  };
  void nav(map[location.pathname] || "home", false);
}
function refresh() {
  if (page.value === "home") void loadHome(true);
  else if (page.value === "market" || page.value === "screener")
    void runScanner();
  else if (page.value === "news") void loadNews(undefined, true);
  else if (page.value === "paper") void loadPaper();
  else if (page.value === "settings") void loadDataHealth();
  else if (page.value === "detail") {
    void loadAssetWorkspace();
    if (selected.value) {
      void loadNews(selected.value, true);
      void loadMarketIntelligence(selected.value, false);
    }
  }
}
const removeRealtime = realtimeMarketStore.onEvent(handleRealtime);
onMounted(() => {
  realtimeMarketStore.connect();
  restoreRoute();
  window.addEventListener("popstate", restoreRoute);
});
onBeforeUnmount(() => {
  removeRealtime();
  realtimeMarketStore.close();
  searchController?.abort();
  if (searchTimer) clearTimeout(searchTimer);
  if (paperTimer) clearInterval(paperTimer);
  if (intelligenceTimer) clearInterval(intelligenceTimer);
  window.removeEventListener("popstate", restoreRoute);
});
</script>

<template>
  <div class="terminal-shell">
    <TerminalSidebar :page="page" :version="appVersion" @navigate="nav" />
    <main class="terminal-main">
      <header class="topbar">
        <div>
          <h1>
            {{
              page === "home"
                ? "Market Intelligence"
                : page === "market"
                  ? "Market Scanner"
                  : page === "detail"
                    ? selected?.name || "资产详情"
                    : page === "watchlist"
                      ? "My Watchlist"
                      : page === "screener"
                        ? "AI Screener"
                        : page === "prediction"
                          ? "AI Outlook"
                          : page === "modelLab"
                            ? "Model Lab"
                            : page === "news"
                              ? "AI Market Intelligence"
                              : page === "strategy"
                                ? "Strategy Lab"
                                : page === "backtest"
                                  ? "Backtest Research"
                                  : page === "paper"
                                    ? "Paper Trading Terminal"
                                    : page === "copilot"
                                      ? "AI Market Copilot"
                                      : "Settings & Data Health"
            }}
          </h1>
          <span
            >{{ liveStatus }} ·
            {{
              realtimeMarketStore.lastUpdateTime.value || "等待实时数据"
            }}</span
          >
        </div>
        <div class="global-search">
          <input
            v-model="query"
            @input="scheduleSearch"
            @keydown="searchKey"
            placeholder="搜索股票、ETF、指数、Crypto"
          /><button @click="searchAssets">搜索</button>
          <div v-if="searchOpen" class="search-pop">
            <div v-if="searching" class="skeleton-line"></div>
            <button
              v-for="(x, i) in searchResults"
              :key="x.asset_type + x.symbol"
              :class="{ active: i === searchIndex }"
              @mouseenter="searchIndex = i"
              @click="selectSearchAsset(x)"
            >
              <b>{{ x.symbol }}</b
              ><span
                >{{ x.name }} · {{ (x as any).market || x.asset_type }}</span
              >
            </button>
            <p v-if="searchError">{{ searchError }}</p>
          </div>
        </div>
        <button class="icon-button" title="刷新当前真实数据" @click="refresh">
          ↻
        </button>
      </header>
      <div v-if="pageError" class="state-error">
        <b>数据暂不可用</b><span>{{ pageError }}</span
        ><button @click="refresh">重试</button>
      </div>
      <div v-if="pageLoading" class="page-skeleton">
        <i v-for="n in 8" :key="n"></i>
      </div>

      <section
        v-else-if="page === 'home' && dashboard"
        class="workspace home-workspace"
      >
        <div class="market-status strip">
          <div v-for="x in dashboard.market_status" :key="x.market">
            <i :class="statusTone(x.status)"></i><b>{{ x.market }}</b
            ><span>{{ x.status }}</span
            ><time>{{ x.time }}</time>
          </div>
          <small>数据截止 {{ timeLabel(dashboard.data_cutoff) }}</small>
        </div>
        <div class="pulse-layout">
          <article class="pulse-score">
            <span>AI MARKET PULSE</span
            ><strong>{{ dashboard.pulse.score }}</strong
            ><b>{{ dashboard.pulse.stance }}</b
            ><small><InfoTip term="AI Score" /></small>
          </article>
          <article class="pulse-breakdown">
            <div
              v-for="key in ['trend', 'sentiment', 'volume', 'news', 'risk']"
              :key="key"
            >
              <span>{{ key }}</span
              ><i><em :style="{ width: dashboard.pulse[key] + '%' }"></em></i
              ><b>{{ dashboard.pulse[key] }}</b>
            </div>
          </article>
          <article class="market-brief">
            <span>AI MARKET BRIEF</span>
            <p>{{ dashboard.brief }}</p>
            <small
              >生成 {{ timeLabel(dashboard.generated_at) }} · 数据
              {{ timeLabel(dashboard.data_cutoff) }} · 可审计规则聚合</small
            >
          </article>
        </div>
        <div class="terminal-grid two-one">
          <section class="terminal-panel">
            <header>
              <h2>Market Movers</h2>
              <small>公开行情实时/延迟状态见设置</small>
            </header>
            <table class="data-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Price</th>
                  <th>Change</th>
                  <th>AI Score</th>
                  <th>Trend</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="x in dashboard.movers.gainers"
                  :key="x.symbol"
                  @click="openAsset(assetFrom(x))"
                >
                  <td>
                    <b>{{ x.symbol }}</b
                    ><small>{{ x.name }}</small>
                  </td>
                  <td>{{ money(x.price, x.currency) }}</td>
                  <td :class="tone(x.change_percent)">
                    {{ pct(x.change_percent) }}
                  </td>
                  <td>{{ x.ai_score }}</td>
                  <td>{{ x.direction }}</td>
                </tr>
              </tbody>
            </table>
          </section>
          <section class="terminal-panel">
            <header>
              <h2>AI Opportunities</h2>
              <InfoTip term="AI Score" />
            </header>
            <div class="signal-list">
              <button
                v-for="x in dashboard.opportunities"
                :key="x.symbol"
                @click="openAsset(assetFrom(x))"
              >
                <b
                  >{{ x.symbol }} <em>{{ x.ai_score }}</em></b
                ><span>{{ x.direction }} · {{ x.factors[0]?.label }}</span>
              </button>
            </div>
          </section>
        </div>
        <div class="terminal-grid two-one">
          <section class="terminal-panel">
            <header>
              <h2>Breaking News</h2>
              <button @click="nav('news')">查看全部 →</button>
            </header>
            <div v-if="!dashboard.breaking_news.length" class="empty-state">
              尚未采集到可关联的重要新闻
            </div>
            <div class="headline-list">
              <button
                v-for="x in dashboard.breaking_news"
                :key="x.id"
                @click="openNews(x)"
              >
                <time>{{ timeLabel(x.published_at).slice(11) }}</time
                ><b>{{ x.title }}</b
                ><span :class="tone(x.sentiment?.score)"
                  >{{ x.event?.direction }} · {{ x.impact?.score }}</span
                >
              </button>
            </div>
          </section>
          <section class="terminal-panel risk-panel">
            <header>
              <h2>Risk Watch</h2>
              <InfoTip term="Risk Score" />
            </header>
            <button
              v-for="x in dashboard.risk_watch"
              :key="x.symbol"
              @click="openAsset(assetFrom(x))"
            >
              <b>{{ x.symbol }}</b
              ><strong>{{ x.components.risk }}</strong
              ><span>{{ x.risks[0] }}</span>
            </button>
          </section>
        </div>
      </section>

      <section
        v-else-if="page === 'market' || page === 'screener'"
        class="workspace scanner-workspace"
      >
        <div v-if="page === 'screener'" class="nl-screener">
          <span>AI SCREENER</span
          ><input
            v-model="scannerFilters.query"
            placeholder="例如：美股 AI板块 趋势向上 AI Score > 70"
          /><button
            @click="
              scannerFilters.min_ai_score = 70;
              runScanner();
            "
          >
            解析并筛选</button
          ><small
            >在当前可审计资产池和本地自选中执行真实行情筛选，不生成不存在的股票。</small
          >
        </div>
        <div class="filterbar">
          <label
            >市场<select v-model="scannerFilters.market">
              <option>全部</option>
              <option>A股</option>
              <option>美股</option>
              <option>Crypto</option>
            </select></label
          ><label
            >行业<select v-model="scannerFilters.industry">
              <option>全部</option>
              <option>AI</option>
              <option>科技</option>
              <option>消费</option>
              <option>新能源</option>
              <option>数字资产</option>
            </select></label
          ><label
            >涨跌<select v-model="scannerFilters.change">
              <option>全部</option>
              <option>上涨</option>
              <option>下跌</option>
            </select></label
          ><label
            >AI Score ≥<input
              v-model.number="scannerFilters.min_ai_score"
              type="number"
              min="0"
              max="100" /></label
          ><label
            >量比 ≥<input
              v-model.number="scannerFilters.min_volume_ratio"
              type="number"
              min="0"
              step="0.1" /></label
          ><label
            >风险 ≤<input
              v-model.number="scannerFilters.max_risk"
              type="number"
              min="0"
              max="100" /></label
          ><button @click="runScanner">运行筛选</button>
        </div>
        <div v-if="scannerLoading" class="page-skeleton">
          <i v-for="n in 6" :key="n"></i>
        </div>
        <section v-else class="terminal-panel scanner-table">
          <header>
            <h2>
              {{ page === "market" ? "跨市场行情" : "符合条件的真实结果" }}
            </h2>
            <small
              >{{ scanner.available }} 可用 ·
              {{ scanner.errors?.length || 0 }} 数据源错误</small
            >
          </header>
          <div v-if="!scanner.rows.length" class="empty-state">
            当前条件下没有可用结果。请调整条件，或检查数据源状态。
          </div>
          <table class="data-table">
            <thead>
              <tr>
                <th>Symbol / Name</th>
                <th>Market</th>
                <th>Price</th>
                <th>Change</th>
                <th>Volume</th>
                <th><InfoTip term="AI Score" /></th>
                <th>Trend</th>
                <th>News</th>
                <th><InfoTip term="Risk Score" /></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="x in scanner.rows"
                :key="x.symbol"
                @mouseenter="hoveredRow = x"
                @mouseleave="hoveredRow = null"
                @click="openAsset(assetFrom(x))"
              >
                <td>
                  <b>{{ x.symbol }}</b
                  ><small>{{ x.name }}</small>
                </td>
                <td>
                  {{ x.market }}<small>{{ x.industry }}</small>
                </td>
                <td>{{ money(x.price, x.currency) }}</td>
                <td :class="tone(x.change_percent)">
                  {{ pct(x.change_percent) }}
                </td>
                <td>
                  {{ number(x.volume, 0)
                  }}<small>量比 {{ number(x.volume_ratio) }}</small>
                </td>
                <td>
                  <strong class="score-pill">{{ x.ai_score }}</strong>
                </td>
                <td>{{ x.direction }}</td>
                <td>{{ x.news_direction }}</td>
                <td>{{ x.components.risk }}</td>
              </tr>
            </tbody>
          </table>
          <aside v-if="hoveredRow" class="mini-preview">
            <b
              >{{ hoveredRow.symbol }} ·
              {{ money(hoveredRow.price, hoveredRow.currency) }}</b
            ><MiniChart :candles="hoveredRow.preview" /><span
              >AI Score {{ hoveredRow.ai_score }} ·
              {{ hoveredRow.direction }}</span
            ><small>{{ hoveredRow.news[0]?.title || "暂无已关联新闻" }}</small>
          </aside>
        </section>
      </section>

      <section
        v-else-if="page === 'detail' && selected"
        class="workspace detail-workspace"
      >
        <div class="instrument-bar">
          <div>
            <span>{{
              selected.asset_type === "crypto"
                ? "CRYPTO"
                : /^[A-Z]/.test(selected.symbol)
                  ? "US EQUITY"
                  : "A-SHARE"
            }}</span>
            <h2>
              {{ selected.name }} <small>{{ selected.symbol }}</small>
            </h2>
          </div>
          <div :class="['live-price', priceFlash]">
            <strong>{{ money(quote?.price, quote?.currency) }}</strong
            ><b :class="tone(quote?.change_percent)">{{
              pct(quote?.change_percent)
            }}</b
            ><small
              >{{ timeLabel(quote?.updated_at) }} · {{ liveStatus }}</small
            >
          </div>
          <div>
            <button @click="toggleWatch">
              {{ inWatchlist ? "★ 已自选" : "☆ 加入自选" }}</button
            ><button class="primary" @click="nav('prediction')">
              AI Outlook
            </button>
          </div>
        </div>
        <div v-if="detailError" class="state-error">
          <span>{{ detailError }}</span
          ><button @click="loadAssetWorkspace">重试</button>
        </div>
        <div class="chart-analysis-layout">
          <section class="terminal-panel chart-panel">
            <header>
              <h2>实时 K线与成交量</h2>
              <div class="periods">
                <button
                  v-for="x in periods"
                  :key="x"
                  :class="{ active: interval === x }"
                  @click="changeInterval(x)"
                >
                  {{ x.toUpperCase() }}
                </button>
              </div>
            </header>
            <div v-if="detailLoading" class="chart-skeleton"></div>
            <KlineChart
              v-else
              :candles="candles"
              :indicators="indicators"
              :news="newsIntelligence?.all_news || newsIntelligence?.items || []"
              @news-click="openNews"
            />
          </section>
          <aside class="terminal-panel ai-analysis">
            <header>
              <h2>AI Analysis</h2>
              <InfoTip term="AI Score" />
            </header>
            <div v-if="assetAnalysis">
              <div class="ai-score">
                <strong>{{ assetAnalysis.ai_score }}</strong
                ><span>/ 100</span><b>{{ assetAnalysis.direction }}</b>
              </div>
              <p class="score-note">{{ assetAnalysis.score_definition }}</p>
              <div class="dimension-list">
                <div
                  v-for="key in [
                    'trend',
                    'technical',
                    'news',
                    'momentum',
                    'risk',
                  ]"
                  :key="key"
                >
                  <span>{{ key }}</span
                  ><i
                    ><em
                      :style="{ width: assetAnalysis.components[key] + '%' }"
                    ></em></i
                  ><b>{{ assetAnalysis.components[key] }}</b>
                </div>
              </div>
              <h3>为什么？</h3>
              <ul class="evidence-list">
                <li
                  v-for="x in assetAnalysis.factors"
                  :key="x.label"
                  :class="x.positive ? 'positive' : 'negative'"
                >
                  {{ x.positive ? "▲" : "▼" }} {{ x.label }}
                </li>
              </ul>
              <h3>风险</h3>
              <ul class="risk-list">
                <li v-for="x in assetAnalysis.risks" :key="x">⚠ {{ x }}</li>
              </ul>
              <small>数据截止 {{ timeLabel(assetAnalysis.data_cutoff) }}</small>
            </div>
            <div v-else class="empty-state">分析数据正在连接</div>
          </aside>
        </div>
        <section class="terminal-panel indicator-strip">
          <div>
            <InfoTip term="RSI" /><b>{{ number(indicators?.latest.rsi) }}</b>
          </div>
          <div>
            <InfoTip term="MACD" /><b>{{
              number(indicators?.latest.macd, 4)
            }}</b>
          </div>
          <div>
            <InfoTip term="Volume Ratio" /><b
              >{{ number(indicators?.latest.volume_ratio) }}x</b
            >
          </div>
          <div><InfoTip term="BOS" /><b>结构引擎</b></div>
          <div><InfoTip term="CHoCH" /><b>结构引擎</b></div>
          <div><InfoTip term="FVG" /><b>K线标记</b></div>
        </section>
        <section class="terminal-panel intelligence-panel">
          <header>
            <div><span>AI MARKET INTELLIGENCE</span><h2>模型概率、证据与事件时间线</h2></div>
            <button :disabled="marketIntelJob?.status==='RUNNING'||marketIntelJob?.status==='QUEUED'" @click="recalculateMarketIntelligence()">
              {{ ['RUNNING','QUEUED'].includes(marketIntelJob?.status) ? '后台计算中…' : '运行真实判断' }}
            </button>
          </header>
          <div v-if="marketIntelError" class="state-error"><span>{{marketIntelError}}</span><button @click="selected&&loadMarketIntelligence(selected,false)">重试</button></div>
          <div v-if="marketIntelLoading&&!marketIntel" class="intel-skeleton"><i v-for="n in 3" :key="n"></i></div>
          <template v-else-if="marketIntel">
            <div v-if="!marketIntel.periods?.length" class="empty-state large">证据不足：尚无该标的真实校准模型快照。系统已在后台准备，不会用新闻分数冒充概率。</div>
            <div v-else class="intel-grid">
              <article v-for="x in marketIntel.periods" :key="x.horizon" class="probability-card">
                <header><b>{{x.horizon}}</b><span>{{x.trend}} · Evidence {{x.evidence}}</span></header>
                <div><label>UP</label><i><em :style="{width:x.up+'%'}"></em></i><strong>{{x.up}}%</strong></div>
                <div><label>SIDEWAYS</label><i><em class="flat" :style="{width:x.sideways+'%'}"></em></i><strong>{{x.sideways}}%</strong></div>
                <div><label>DOWN</label><i><em class="down" :style="{width:x.down+'%'}"></em></i><strong>{{x.down}}%</strong></div>
                <small>{{x.model_level}} · {{x.probability_type}}</small>
              </article>
              <article class="intel-why">
                <h3>WHY?</h3>
                <div v-for="x in marketIntel.contributions" :key="x.factor"><span>{{x.factor}}</span><b :class="tone(x.contribution)">{{x.contribution>0?'+':''}}{{x.contribution}}</b></div>
                <p v-if="!marketIntel.contributions?.length">缓存记录没有完整特征贡献；重新运行后生成。</p>
                <small>Market Regime · {{marketIntel.market_regime?.primary||marketIntel.market_regime||'待识别'}}</small>
              </article>
            </div>
            <div v-if="marketIntel.why_changed?.length" class="intel-change"><b>⚡ 为什么改变？</b><span v-for="x in marketIntel.why_changed" :key="x.horizon">{{x.horizon}} {{x.from}} → {{x.to}} · UP {{x.up_delta>0?'+':''}}{{x.up_delta}}%</span></div>
            <div class="intel-meta"><span>更新 {{timeLabel(marketIntel.updated_at||marketIntel.generated_at)}}</span><span>数据截止 {{timeLabel(marketIntel.data_cutoff)}}</span><span>不可变快照 {{marketIntel.immutable_snapshot_count||0}}</span><span>已结算样本 {{marketIntel.track_record?.samples||0}}</span></div>
            <div class="intelligence-timeline">
              <header><h3>MARKET INTELLIGENCE TIMELINE</h3><span>新闻仅作情报与重算触发；未通过消融前不混入概率</span></header>
              <button v-for="x in marketIntel.news_context?.items||[]" :key="x.id" @click="openNews(x)"><time>{{timeLabel(x.published_at)}}</time><b>{{x.event?.event_type||x.category}}</b><span>{{x.title}}</span><em>Impact {{x.impact?.score}} · {{x.sentiment?.label}}</em></button>
              <p v-if="!marketIntel.news_context?.items?.length">News unavailable / 当前没有可明确关联的新闻，不会生成虚假新闻。</p>
            </div>
            <div class="intel-boundary"><b>模型边界：</b>{{marketIntel.probability_boundary||marketIntel.prediction_notice}} <button @click="nav('paper')">进入模拟交易 →</button></div>
          </template>
        </section>
      </section>

      <section v-else-if="page === 'watchlist'" class="workspace">
        <div class="filterbar">
          <h2>自选资产</h2>
          <label
            >排序<select v-model="watchSort">
              <option value="score">AI Score</option>
              <option value="change">涨跌幅</option>
              <option value="risk">风险</option>
            </select></label
          >
        </div>
        <section class="terminal-panel">
          <div v-if="!sortedWatchRows.length" class="empty-state">
            自选为空；请在资产详情点击“加入自选”。
          </div>
          <table class="data-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Price</th>
                <th>Change</th>
                <th>AI Score</th>
                <th>Score Δ</th>
                <th>Trend</th>
                <th>News</th>
                <th>Risk</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="x in sortedWatchRows"
                :key="x.symbol"
                @click="!x.unavailable && openAsset(assetFrom(x))"
              >
                <td>
                  <b>{{ x.symbol }}</b
                  ><small>{{ x.name }}</small>
                </td>
                <td>{{ money(x.price, x.currency) }}</td>
                <td :class="tone(x.change_percent)">
                  {{ pct(x.change_percent) }}
                </td>
                <td>{{ x.ai_score ?? "—" }}</td>
                <td :class="tone(x.score_change)">
                  {{
                    x.score_change == null
                      ? "—"
                      : (x.score_change > 0 ? "+" : "") + x.score_change
                  }}<small v-if="x.score_change == null">首次基线</small>
                </td>
                <td>{{ x.direction || "—" }}</td>
                <td>{{ x.news_direction || "—" }}</td>
                <td>{{ x.components?.risk ?? "—" }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </section>

      <section
        v-else-if="page === 'prediction'"
        class="workspace outlook-workspace"
      >
        <div class="action-header">
          <div>
            <span>AI OUTLOOK · {{ selected?.symbol }}</span>
            <h2>概率、证据与模型状态</h2>
            <p>日线目标严格按未来交易日/自然日对齐；样本不足时不生成。</p>
          </div>
          <button class="primary" @click="runAI" :disabled="aiLoading">
            {{ aiLoading ? "训练与验证中…" : "运行真实预测" }}
          </button>
        </div>
        <div v-if="aiError" class="state-error">
          <span>预测服务暂时不可用：{{ aiError }}</span
          ><button @click="runAI">重新预测</button>
        </div>
        <div v-if="aiLoading && aiQuick" class="method-banner">
          <b>即时结构信号</b
          ><span
            >{{ aiQuick.direction }} · AI Score {{ aiQuick.ai_score }}/100 ·
            风险 {{ aiQuick.components?.risk }}</span
          ><small
            >先显示当前真实量价与指标评分；概率模型仍在后台训练/验证，此评分不是上涨概率。</small
          >
        </div>
        <div v-if="aiLoading" class="page-skeleton">
          <i v-for="n in 6" :key="n"></i>
        </div>
        <template v-else-if="aiResult"
          ><div class="model-status strip">
            <span
              >模型
              <b
                >{{ aiResult.engine_version }} · {{ aiResult.model.name }}</b
              ></span
            ><span
              >数据截止 <b>{{ timeLabel(aiResult.data_time) }}</b></span
            ><span
              >训练状态 <b>{{ aiResult.model.training_status }}</b></span
            ><span>验证 <b>Purged + Walk-forward</b></span>
          </div>
          <div class="outlook-grid">
            <article
              v-for="x in predictionRows"
              :key="x.horizon"
              :class="{ 'unavailable-card': !x.prediction }"
            >
              <header>
                <h2>{{ x.horizon }}</h2>
                <span :class="statusTone(x.prediction ? 'AVAILABLE' : '')">{{
                  x.prediction ? "● Available" : "● Insufficient Data"
                }}</span>
              </header>
              <template v-if="x.prediction"
                ><strong>{{ x.prediction }}</strong>
                <div class="prob-bars">
                  <label
                    >UP
                    <i
                      ><em
                        :style="{ width: probability(x.probabilities.up) }"
                      ></em></i
                    ><b>{{ probability(x.probabilities.up) }}</b></label
                  ><label
                    >SIDEWAYS
                    <i
                      ><em
                        :style="{ width: probability(x.probabilities.flat) }"
                      ></em></i
                    ><b>{{ probability(x.probabilities.flat) }}</b></label
                  ><label
                    >DOWN
                    <i
                      ><em
                        :style="{ width: probability(x.probabilities.down) }"
                      ></em></i
                    ><b>{{ probability(x.probabilities.down) }}</b></label
                  >
                </div>
                <small
                  >样本 {{ x.sample_count }} · Walk-forward
                  {{ x.walk_forward_samples }} · 最近训练
                  {{ timeLabel(x.trained_at).slice(0, 10) }}</small
                >
                <p>{{ x.advantage_message }}</p></template
              >
              <p v-else>{{ x.message }}</p>
            </article>
          </div>
          <section class="terminal-panel evidence-panel">
            <header>
              <h2>Evidence</h2>
              <InfoTip term="Prediction" />
            </header>
            <div
              v-if="predictionRows[0]?.top_factors?.length"
              class="factor-table"
            >
              <div v-for="x in predictionRows[0].top_factors" :key="x.feature">
                <b>{{ x.label }}</b
                ><span
                  :class="x.direction === 'positive' ? 'positive' : 'negative'"
                  >{{ x.direction }} · importance {{ x.importance }}</span
                >
              </div>
            </div>
            <p class="risk-notice">{{ aiResult.risk_notice }}</p>
          </section></template
        >
        <div v-else class="empty-state large">
          选择标的后运行预测。页面不会自动复用旧结果，也不会预填概率。
        </div>
      </section>

      <section
        v-else-if="page === 'modelLab' && modelLab"
        class="workspace model-lab"
      >
        <div class="method-banner">
          <b>验证方法</b><span>{{ modelLab.validation }}</span
          ><small
            >Accuracy
            是历史样本外结果，不代表未来表现；空值不会用估算补齐。</small
          >
        </div>
        <section
          v-for="asset in modelLab.assets"
          :key="asset.symbol"
          class="terminal-panel"
        >
          <header>
            <div>
              <h2>{{ asset.symbol }}</h2>
              <span>{{ asset.model_version }}</span>
            </div>
            <b :class="statusTone(asset.status)">{{ asset.status }}</b>
          </header>
          <div v-if="asset.periods.length" class="performance-table">
            <article v-for="x in asset.periods" :key="x.horizon">
              <h3>{{ x.horizon }}</h3>
              <strong>{{ x.accuracy }}%</strong
              ><span
                >Baseline
                {{ x.baseline == null ? "未披露" : x.baseline + "%" }}</span
              ><span
                >Edge
                {{
                  x.edge == null
                    ? "不可计算"
                    : (x.edge > 0 ? "+" : "") + x.edge + "%"
                }}</span
              ><b
                :class="
                  x.assessment === 'NO_EDGE'
                    ? 'negative'
                    : x.assessment === 'WEAK_EDGE'
                      ? 'warning'
                      : 'positive'
                "
                >{{ x.evidence_level }}</b
              ><small
                >Precision
                {{ x.precision == null ? "不可复算" : x.precision }} · Brier
                {{ x.brier_score == null ? "不可复算" : x.brier_score }}</small
              ><small v-if="x.note">{{ x.note }}</small>
            </article>
          </div>
          <div v-else class="empty-state">
            该资产尚无 T+1/T+5/T+20
            可复核样本外结果。运行并积累预测后才会显示；Precision / Recall / F1
            / MAE 均不伪造。
          </div>
          <div v-if="asset.resolved_history.length" class="resolved-list">
            <b>本机已结算预测历史</b
            ><span v-for="x in asset.resolved_history" :key="x.horizon"
              >{{ x.horizon }} · {{ x.samples }} 样本 · Accuracy
              {{ x.accuracy }}% · MAE {{ x.mae }}%</span
            >
          </div>
        </section>
      </section>

      <section v-else-if="page === 'news'" class="workspace news-workspace">
        <div class="news-tabs">
          <button
            v-for="x in ['全部', '利好', '利空']"
            :key="x"
            :class="{ active: newsDirection === x }"
            @click="
              newsDirection = x;
              loadNews();
            "
          >
            {{ x }}
          </button>
          <div v-if="newsIntelligence">
            自选快讯情绪
            <strong>{{
              newsIntelligence.radar.market_sentiment ?? "—"
            }}</strong>
            · {{ newsIntelligence.total }} 条
          </div>
        </div>
        <div v-if="newsIntelligence?.assets?.length" class="watch-news-assets">
          <b>评估标的</b
          ><button
            v-for="x in newsIntelligence.assets"
            :key="x.asset_type + x.symbol"
            :class="{
              active:
                newsReportAsset?.symbol === x.symbol &&
                newsReportAsset?.asset_type === x.asset_type,
            }"
            @click="loadWatchReport(x)"
          >
            {{ x.name || x.symbol }} <small>{{ x.symbol }}</small></button
          ><span>只展示标题、摘要或公告元数据明确关联自选标的的快讯</span>
        </div>
        <section v-if="newsReportAsset" class="terminal-panel watch-report">
          <header>
            <div>
              <span>WATCHLIST INTELLIGENCE REPORT</span>
              <h2>
                {{ newsReportAsset.name || newsReportAsset.symbol }} ·
                近期新闻与数学模型评估
              </h2>
            </div>
            <button
              @click="loadWatchReport(newsReportAsset)"
              :disabled="newsReportLoading"
            >
              {{ newsReportLoading ? "计算中…" : "重新评估" }}
            </button>
          </header>
          <div v-if="newsReportLoading" class="report-loading">
            <b>正在计算 V5 技术共识与风险线…</b
            ><span>快讯已可浏览，报告在后台计算，不阻塞页面。</span>
          </div>
          <div v-else-if="newsReportError" class="state-error">
            <span>{{ newsReportError }}</span
            ><button @click="loadWatchReport(newsReportAsset)">重试</button>
          </div>
          <template v-else-if="newsReport"
            ><div class="report-verdict">
              <article>
                <span>结论</span
                ><strong :class="tone(newsReport.score)">{{
                  newsReport.action
                }}</strong
                ><small
                  >综合分 {{ number(newsReport.score) }} / [-100,100]</small
                >
              </article>
              <article>
                <span>V5技术共识</span
                ><strong>{{
                  number(newsReport.components.v5_technical)
                }}</strong
                ><small>{{ newsReport.market_regime.primary }}</small>
              </article>
              <article>
                <span>新闻影响</span
                ><strong :class="tone(newsReport.components.news)">{{
                  number(newsReport.components.news)
                }}</strong
                ><small>{{ newsReport.news.count }} 条明确关联</small>
              </article>
            </div>
            <p class="report-summary">{{ newsReport.summary }}</p>
            <div class="risk-levels">
              <article>
                <span>参考入场</span
                ><b>{{
                  money(newsReport.risk_plan.entry, newsReport.currency)
                }}</b>
              </article>
              <article class="danger">
                <span>止损 / 离场线</span
                ><b>{{
                  money(newsReport.risk_plan.exit_line, newsReport.currency)
                }}</b>
              </article>
              <article
                v-for="x in newsReport.risk_plan.take_profits"
                :key="x.name"
              >
                <span>{{ x.name }} 目标位</span
                ><b>{{ money(x.price, newsReport.currency) }}</b
                ><small>R:R {{ number(x.risk_reward) }}</small>
              </article>
            </div>
            <p><b>离场规则：</b>{{ newsReport.risk_plan.exit_rule }}</p>
            <div class="report-basis">
              <span v-for="x in newsReport.model_basis" :key="x">{{ x }}</span>
            </div>
            <small
              >数据截止 {{ timeLabel(newsReport.data_cutoff) }} ·
              {{ newsReport.notice }}</small
            ></template
          >
        </section>
        <div v-if="newsLoading && !newsIntelligence" class="page-skeleton">
          <i v-for="n in 8" :key="n"></i>
        </div>
        <div v-else-if="newsError" class="state-error">
          <span>{{ newsError }}</span
          ><button @click="loadNews()">重试</button>
        </div>
        <div v-else class="news-feed breaking-feed">
          <article
            v-for="x in newsIntelligence?.items || []"
            :key="x.id"
            @click="openNews(x)"
          >
            <header>
              <span class="breaking-label">快讯</span
              ><time>{{ timeLabel(x.published_at) }}</time
              ><span :class="tone(x.sentiment?.score)">{{
                x.event?.direction
              }}</span
              ><b><InfoTip term="Impact Score" /> {{ x.impact?.score }}</b>
            </header>
            <h2>{{ x.title }}</h2>
            <small>{{ x.source }} · {{ x.market }}</small>
            <p>{{ x.one_sentence_summary || x.summary }}</p>
            <div class="impact-tags">
              <span
                v-for="s in x.matched_watchlist_symbols || x.symbols"
                :key="s"
                >关联 {{ s }}</span
              ><span v-for="s in x.sectors" :key="s">{{ s }}</span>
            </div>
          </article>
          <div v-if="!newsIntelligence?.items?.length" class="empty-state">
            最近没有与自选股或自选币明确关联的真实新闻。
          </div>
        </div>
      </section>

      <section
        v-else-if="page === 'strategy' || page === 'backtest'"
        class="workspace strategy-workspace"
      >
        <div v-if="page === 'strategy'" class="strategy-builder">
          <span>NATURAL LANGUAGE STRATEGY</span
          ><textarea v-model="strategyText"></textarea
          ><button @click="parseStrategy">转换为可执行规则</button>
          <div
            v-if="parsedRule"
            :class="[
              'parsed-rule',
              parsedRule.status === 'PARSED' ? 'ok' : 'error',
            ]"
          >
            <template v-if="parsedRule.status === 'PARSED'"
              ><b
                >{{ parsedRule.entry.indicator }}
                {{ parsedRule.entry.operator }} {{ parsedRule.entry.value }}</b
              ><i>→</i><b>{{ parsedRule.action }}</b
              ><i>→</i
              ><b>{{ parsedRule.exit.type }} {{ parsedRule.exit.bars || "" }}</b
              ><small>{{ parsedRule.causality }}</small></template
            ><span v-else>{{ parsedRule.message }}</span>
          </div>
          <button
            class="primary"
            :disabled="backtestLoading || parsedRule?.status !== 'PARSED'"
            @click="runBacktest(true)"
          >
            开始真实回测
          </button>
        </div>
        <div v-else class="filterbar">
          <label
            >策略<select v-model="strategy">
              <option value="ma">MA5 / MA20</option>
              <option value="macd">MACD</option>
              <option value="rsi">RSI反转</option>
              <option value="ai">样本外AI</option>
            </select></label
          ><label
            >初始资金<input v-model.number="initialCash" type="number" /></label
          ><button @click="runBacktest(false)">
            {{ backtestLoading ? "回测中…" : "运行回测" }}
          </button>
        </div>
        <section v-if="backtestResult" class="terminal-panel backtest-report">
          <header>
            <div>
              <h2>
                {{ backtestResult.symbol }} · {{ backtestResult.strategy }}
              </h2>
              <span
                >{{ backtestResult.data_source }} ·
                {{ backtestResult.data_start }} →
                {{ backtestResult.data_end }}</span
              >
            </div>
            <button @click="nav('paper')">进入模拟交易 →</button>
          </header>
          <div class="metric-grid">
            <div>
              <span>净收益</span
              ><b :class="tone(backtestResult.net_return_percent)">{{
                pct(backtestResult.net_return_percent)
              }}</b>
            </div>
            <div>
              <span>年化收益</span
              ><b>{{ pct(backtestResult.annualized_return_percent) }}</b>
            </div>
            <div>
              <span>胜率</span
              ><b>{{ number(backtestResult.win_rate_percent) }}%</b>
            </div>
            <div>
              <span>盈亏比</span
              ><b>{{ number(backtestResult.profit_loss_ratio) }}</b>
            </div>
            <div>
              <span>最大回撤</span
              ><b class="negative"
                >-{{ number(backtestResult.max_drawdown_percent) }}%</b
              >
            </div>
            <div>
              <span>Sharpe</span
              ><b>{{ number(backtestResult.sharpe_ratio, 3) }}</b>
            </div>
            <div>
              <span>交易次数</span><b>{{ backtestResult.trade_count }}</b>
            </div>
            <div>
              <span>基准收益</span
              ><b>{{ pct(backtestResult.benchmark_return_percent) }}</b>
            </div>
          </div>
          <PerformanceChart
            :strategy="backtestResult.equity_curve"
            :benchmark="backtestResult.benchmark_curve"
            :drawdown="backtestResult.drawdown_curve"
          />
          <p class="risk-notice">{{ backtestResult.notice }}</p>
        </section>
        <div v-else class="empty-state large">
          {{
            page === "strategy"
              ? "输入可支持的自然语言规则，确认结构化结果后回测。"
              : "选择真实标的与策略后运行；结果不会预填。"
          }}
        </div>
      </section>

      <section v-else-if="page === 'paper'" class="workspace paper-workspace">
        <div class="account-strip">
          <div>
            <span>总资产</span><b>{{ money(paperTotals.equity) }}</b>
          </div>
          <div>
            <span>可用资金</span><b>{{ money(paperTotals.cash) }}</b>
          </div>
          <div>
            <span>持仓市值</span><b>{{ money(paperTotals.market) }}</b>
          </div>
          <div>
            <span>实时浮盈亏</span
            ><b :class="tone(paperTotals.pnl)">{{ money(paperTotals.pnl) }}</b>
          </div>
        </div>
        <div class="paper-terminal">
          <section class="terminal-panel positions-pane">
            <header>
              <h2>Positions</h2>
              <span>{{ positions.length }}</span>
            </header>
            <button
              v-for="x in positions"
              :key="x.symbol"
              @click="selectPosition(x)"
            >
              <b>{{ x.symbol }}</b
              ><span
                >{{ number(x.quantity) }} @ {{ number(x.average_cost) }}</span
              ><strong :class="tone(x.unrealized_pnl)"
                >{{ money(x.unrealized_pnl) }} ·
                {{ pct(x.return_percent) }}</strong
              ><i @click.stop="sellAll(x)">全部卖出</i>
            </button>
            <div v-if="!positions.length" class="empty-state">暂无持仓</div>
          </section>
          <section class="terminal-panel paper-chart">
            <header>
              <h2>{{ selected?.symbol || "请选择标的" }}</h2>
              <span
                >{{ money(quote?.price, quote?.currency) }} ·
                {{ timeLabel(quote?.updated_at) }}</span
              >
            </header>
            <KlineChart
              v-if="candles.length"
              :candles="candles"
              :indicators="indicators"
            />
            <div v-else class="empty-state">从搜索框选择交易标的</div>
          </section>
          <section class="terminal-panel order-ticket">
            <header>
              <h2>Order Ticket</h2>
              <span>模拟账户</span>
            </header>
            <div class="buy-sell">
              <button class="buy" @click="pendingSide = 'BUY'">Buy</button
              ><button class="sell" @click="pendingSide = 'SELL'">Sell</button>
            </div>
            <label
              >Order Type<select v-model="orderType">
                <option>MARKET</option>
                <option>LIMIT</option>
              </select></label
            ><label
              >Quantity<input
                v-model.number="orderQuantity"
                type="number"
                min="0.0001"
                step="0.0001" /></label
            ><label v-if="orderType === 'LIMIT'"
              >Limit Price<input v-model.number="orderLimitPrice" type="number"
            /></label>
            <div class="estimate">
              <span>Estimated price</span
              ><b>{{
                money(
                  orderType === "LIMIT" ? orderLimitPrice : quote?.price,
                  quote?.currency,
                )
              }}</b
              ><span>Estimated amount</span
              ><b>{{
                money(
                  Number(orderQuantity) *
                    (Number(
                      orderType === "LIMIT" ? orderLimitPrice : quote?.price,
                    ) || 0),
                  quote?.currency,
                )
              }}</b>
            </div>
            <p class="trade-risk">
              ⚠
              {{
                assetAnalysis?.direction === "偏多" &&
                assetAnalysis?.components?.risk > 55
                  ? "AI偏多，但当前存在追高或波动风险。"
                  : assetAnalysis?.risks?.[0] || "模拟交易也应设置风险上限。"
              }}
            </p>
            <button
              :class="pendingSide === 'BUY' ? 'buy' : 'sell'"
              @click="confirmOrder(pendingSide)"
            >
              Review {{ pendingSide }}
            </button>
          </section>
        </div>
        <section class="terminal-panel order-book">
          <div class="tabs">
            <button
              v-for="x in [
                ['orders', 'Open Orders'],
                ['positions', 'Positions'],
                ['trades', 'Trades'],
                ['history', 'History'],
              ]"
              :key="x[0]"
              :class="{ active: paperTab === x[0] }"
              @click="paperTab = x[0]"
            >
              {{ x[1] }}
            </button>
          </div>
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Type</th>
                <th>Qty</th>
                <th>Price</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="x in orders.filter((o: any) =>
                  paperTab === 'orders'
                    ? o.status === 'pending'
                    : paperTab === 'trades'
                      ? o.status === 'filled'
                      : paperTab === 'history'
                        ? true
                        : false,
                )"
                :key="x.id"
              >
                <td>{{ x.id }}</td>
                <td>{{ x.symbol }}</td>
                <td :class="x.side === 'BUY' ? 'positive' : 'negative'">
                  {{ x.side }}
                </td>
                <td>{{ x.order_type }}</td>
                <td>{{ number(x.quantity, 4) }}</td>
                <td>{{ number(x.price) }}</td>
                <td>{{ x.status }}</td>
                <td>
                  <button
                    v-if="x.status === 'pending'"
                    @click="cancelOrder(x.id)"
                  >
                    撤单
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <div v-if="paperTab === 'positions'" class="position-summary">
            <span v-for="x in positions" :key="x.symbol"
              >{{ x.symbol }} · {{ number(x.quantity) }} ·
              <b :class="tone(x.unrealized_pnl)">{{
                money(x.unrealized_pnl)
              }}</b></span
            >
          </div>
        </section>
      </section>

      <section v-else-if="page === 'copilot'" class="workspace copilot-page">
        <div class="copilot-intro">
          <span>TOOL-AUGMENTED MARKET ANALYSIS</span>
          <h2>不是独立聊天机器人</h2>
          <p>
            每次回答都会先调用本系统的真实行情、K线指标、新闻数据库或 AI
            Screener，并显示工具记录与数据截止时间。
          </p>
          <div>
            <button @click="askCopilot('分析NVDA')">分析 NVDA</button
            ><button @click="askCopilot('帮我分析BTC')">分析 BTC</button
            ><button @click="askCopilot('找出今天值得关注的股票')">
              寻找机会</button
            ><button @click="askCopilot('比较NVDA和AMD')">
              比较 NVDA / AMD
            </button>
          </div>
        </div>
        <div class="copilot-full">
          <div class="copilot-thread">
            <article v-for="(x, i) in copilotMessages" :key="i" :class="x.role">
              <b>{{
                x.role === "user"
                  ? "YOU"
                  : x.role === "error"
                    ? "ERROR"
                    : "COPILOT"
              }}</b>
              <p>{{ x.text }}</p>
              <div v-if="x.tools" class="tool-calls">
                <span v-for="(tool, j) in x.tools" :key="j"
                  >✓ {{ tool.tool }} · {{ tool.status }}</span
                >
              </div>
              <small v-if="x.cutoff">数据截止 {{ timeLabel(x.cutoff) }}</small>
            </article>
            <article v-if="copilotLoading" class="assistant">
              <div class="typing">正在调用真实工具…</div>
            </article>
          </div>
          <form @submit.prevent="askCopilot()">
            <input
              v-model="copilotInput"
              placeholder="问行情、原因、比较或筛选…"
            /><button>发送</button>
          </form>
        </div>
      </section>

      <section
        v-else-if="page === 'settings'"
        class="workspace settings-workspace"
      >
        <nav class="settings-tabs">
          <button>数据源</button><button>AI模型</button><button>交易</button
          ><button>更新</button><button>系统</button>
        </nav>
        <section class="terminal-panel">
          <header>
            <h2>Data Health</h2>
            <small>检查 {{ timeLabel(dataHealth?.checked_at) }}</small>
          </header>
          <div class="health-list">
            <article v-for="x in dataHealth?.items || []" :key="x.name">
              <i :class="statusTone(x.status)"></i>
              <div>
                <b>{{ x.name }}</b
                ><span>{{ x.source }}</span
                ><small>{{ x.mode }} · {{ x.realtime }}</small>
              </div>
              <strong>{{ x.status }}</strong
              ><time>{{ timeLabel(x.last_update) }}</time>
            </article>
          </div>
          <p class="source-disclosure">
            免费美股行情来自公开数据源，可能存在延迟，不属于交易所授权逐笔行情。连接状态表示服务链路可用，不表示零延迟。
          </p>
        </section>
        <div class="terminal-grid">
          <section class="terminal-panel settings-card">
            <h2>AI 模型</h2>
            <p>
              PerformanceWeightedEnsemble · 因果特征 · Purged split ·
              Walk-forward。
            </p>
            <span>深度模型在单资产样本不足时禁用，不冒充可用。</span
            ><button @click="nav('modelLab')">查看模型表现</button>
          </section>
          <section class="terminal-panel settings-card">
            <h2>更新</h2>
            <p>当前版本 v{{ appVersion }}</p>
            <span>{{ updateStatus }}</span
            ><button @click="checkUpdates" :disabled="updateChecking">
              {{ updateChecking ? "检查中…" : "检查最新版" }}
            </button>
          </section>
          <section class="terminal-panel settings-card">
            <h2>系统与数据</h2>
            <p>
              用户数据库、模型和设置保存在 Windows
              用户数据目录，与程序安装目录分离。
            </p>
            <span>卸载默认保留数据；更新不会覆盖数据库。</span>
          </section>
        </div>
      </section>
    </main>
    <button
      v-if="page !== 'copilot'"
      class="copilot-fab"
      @click="copilotOpen = !copilotOpen"
    >
      ✦<span>AI Copilot</span>
    </button>
    <aside v-if="copilotOpen && page !== 'copilot'" class="copilot-drawer">
      <header>
        <b>AI Market Copilot</b><button @click="copilotOpen = false">×</button>
      </header>
      <div class="copilot-thread">
        <article v-for="(x, i) in copilotMessages" :key="i" :class="x.role">
          <p>{{ x.text }}</p>
          <div v-if="x.tools" class="tool-calls">
            <span v-for="(tool, j) in x.tools" :key="j">✓ {{ tool.tool }}</span>
          </div>
        </article>
      </div>
      <form @submit.prevent="askCopilot()">
        <input v-model="copilotInput" placeholder="分析 NVDA…" /><button>
          发送
        </button>
      </form>
    </aside>
    <el-dialog
      v-model="orderConfirmOpen"
      title="确认模拟订单"
      width="440px"
      class="order-dialog"
      ><div class="confirm-order">
        <b>{{ selected?.symbol }} · {{ pendingSide }}</b
        ><span
          >{{ number(orderQuantity, 4) }}
          {{ selected?.asset_type === "crypto" ? "coins" : "shares" }}</span
        ><span
          >{{ orderType }} · Estimated
          {{
            money(
              orderType === "LIMIT" ? orderLimitPrice : quote?.price,
              quote?.currency,
            )
          }}</span
        ><strong
          >预计金额
          {{
            money(
              Number(orderQuantity) *
                (Number(
                  orderType === "LIMIT" ? orderLimitPrice : quote?.price,
                ) || 0),
              quote?.currency,
            )
          }}</strong
        >
        <p>这是模拟交易，不连接真实券商账户。请确认数量、方向和价格。</p>
      </div>
      <template #footer
        ><button @click="orderConfirmOpen = false">取消</button
        ><button
          :class="pendingSide === 'BUY' ? 'buy' : 'sell'"
          :disabled="orderLoading"
          @click="submitOrder"
        >
          确认{{ pendingSide === "BUY" ? "买入" : "卖出" }}
        </button></template
      ></el-dialog
    >
    <el-dialog v-model="newsDialogOpen" width="720px" class="news-dialog"
      ><template #header
        ><div>
          <span>EVENT IMPACT · 事件影响分析</span>
          <h2>{{ newsSelected?.title }}</h2>
        </div></template
      >
      <div v-if="newsSelected">
        <div class="event-impact">
          <article>
            <span>即时影响</span
            ><b :class="tone(newsSelected.sentiment?.score)"
              >{{ newsSelected.event?.direction }} ·
              {{ newsSelected.impact?.score }}</b
            >
          </article>
          <article>
            <span>短期影响</span
            ><b>{{
              newsSelected.predictions?.["T+1"]?.type || "样本待验证"
            }}</b>
          </article>
          <article>
            <span>中期影响</span
            ><b>{{
              newsSelected.predictions?.["T+5"]?.type || "样本待验证"
            }}</b>
          </article>
        </div>
        <h3>为什么？</h3>
        <p>
          {{ (newsSelected.reason || []).join("；") || newsSelected.summary }}
        </p>
        <h3>事件影响时间轴</h3>
        <div class="event-timeline">
          <div>
            <i></i><b>事件发布</b
            ><span>{{ timeLabel(newsSelected.published_at) }}</span>
          </div>
          <div v-for="x in ['5m', '15m', '1h', '1D']" :key="x">
            <i></i><b>{{ x }}</b
            ><span>{{ eventImpact(newsSelected, x) }}</span>
          </div>
        </div>
        <p class="risk-notice">
          仅在存在发布后真实可交易 K线时计算；没有样本的周期明确显示不可用。
        </p>
        <a :href="newsSelected.url" target="_blank">查看原始来源 ↗</a>
      </div></el-dialog
    >
  </div>
</template>
