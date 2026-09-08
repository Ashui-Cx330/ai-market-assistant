# AI行情助手 v1.8.0 产品终端审计

## 数据与路由

- `/` 市场驾驶舱，`/market` 行情搜索，`/news` 新闻情报，`/prediction` AI 预测，`/strategy` 策略回测，`/paper` 模拟交易，`/watchlist` 自选。
- `/stock/{symbol}` 和 `/crypto/{symbol}` 动态加载标的；前进/后退不再重复压入历史。
- A股：东方财富，失败时腾讯证券；美股：Yahoo Finance 公开 Chart API；Crypto：OKX REST + WebSocket。休市时不伪造 Tick。
- SymbolResolver 将 `NASDAQ:NVDA` 统一为 `NVDA`，`SH600519` / `600519.SH` 统一为 `600519.SH`，`BTC-USDT` / `BTC/USDT` 内部统一为 `BTC`，界面展示为 `BTC/USDT`。

## 预测审计

2026-09-08 对 NVDA 真实日线运行 PerformanceWeightedEnsemble（Logistic Regression、Random Forest、XGBoost、LightGBM）：

| 周期 | 方向 | 上/震荡/下 | Walk-forward 样本 | 当前样本外结论 |
|---|---|---|---:|---|
| T+1 | UP | 38.15% / 26.00% / 35.85% | 533 | Accuracy 39.47%，没有超过多数类基线 |
| T+5 | DOWN | 42.39% / 12.88% / 44.73% | 531 | Accuracy 50.26%，较多数类基线约 +2.11pp，优势不明显 |
| T+20 | UP | 46.47% / 10.73% / 42.80% | 527 | Accuracy 62.23%，较多数类基线约 +7.44pp |

这些是当前数据切分上的历史样本外指标，不是未来精准率承诺。T+1 目前不具备可用优势，页面必须继续显示这一事实。

## 实测

- 纯逻辑回归：58 项通过，1 项真实全链路独立执行并通过。
- Electron 开发包端到端：独立页面、代码解析、K线、Tooltip、新闻、市价买入、限价挂单、撤单、卖出通过。
- WebSocket：实际收到 `snapshot` / `ticker` / `analysis` / `candle`，无并发写入异常。

## 明确限制

- 美股免费源是增量轮询，不是交易所逐笔授权行情；节假日仅能依据数据时间戳判断陈旧。
- 新闻分析为可解释规则引擎，不是 LLM 事实核查；历史相似事件样本不足时会明示 0，不伪造胜率。
- 模拟限价单使用最新观测报价触发，不模拟交易所排队和部分成交流动性。
- 尚未接入付费美股逐笔、期权链、链上全量资金流、结构化宏观事件日历；相关模块显示 `NO_DATA` / `NOT_AVAILABLE`。
