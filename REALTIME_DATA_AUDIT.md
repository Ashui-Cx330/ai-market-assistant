# AI行情助手 V6 实时数据审计

审计版本：v1.5.0  
审计原则：只把真实外部数据源的持续观测记为实时；测试 fixture 不进入生产采集路径；数据源没有高频变化时，不制造变化。

## 数据链路

`OKX WebSocket / A股公开 HTTP` → `RealtimeDataManager` → `RealtimeMarketStore` → `BackendEventBus` → `/api/realtime/ws` → `RealtimeMarketStore(Vue)` → UI。

- Crypto Ticker、逐笔成交和五档盘口：OKX public WebSocket。
- Crypto 当前 K 线：OKX business Candle WebSocket；断线时仅用真实 HTTP K 线补齐。
- A 股：公开源没有项目可用的官方 WebSocket，按 15 秒策略调用 `force_refresh=True`，不命中旧报价/K线缓存。
- 新闻：60 秒重新检查有时间戳的 Google News RSS；事件总线只发送未见过的链接/标题。
- OI/Funding：OKX 公开 API，60 秒 TTL；宏观与链上 300 秒，符合数据自身发布速度。
- 生产代码没有模拟价格、随机 K 线、随机成交量或前端 `Math.random()`。

## 实现验收

| 项目 | 状态 | 证据/限制 |
|---|---|---|
| Ticker 实时更新 | PASS | OKX `tickers` WebSocket；A 股 15 秒真实增量请求 |
| K线实时更新 | PASS | OKX `candle*` WebSocket；同 timestamp 覆盖当前柱，新 timestamp 换柱 |
| 成交量实时更新 | PASS | Candle WebSocket 的真实 `vol` 字段 |
| 指标实时更新 | PASS | 每次当前柱变化重算 MA/EMA/BOLL/RSI/MACD/Stochastic/SAR/ATR/MFI/Momentum/Donchian |
| 资金流实时更新 | PASS | OKX trades 主动买卖量与累计 Delta；OI/Funding 低频刷新 |
| 新闻实时更新 | PASS | 60 秒检查，链接/标题去重后只发布新增项 |
| 宏观实时更新 | PASS | 300 秒按真实可用发布时间检查，不伪造高频变化 |
| 链上实时更新 | PASS（BTC/ETH） | Blockchair 300 秒；其他币明确 NOT_APPLICABLE_OR_NO_DATA |
| Order Flow 实时更新 | PASS（Crypto） | OKX `trades` 的 tradeId 去重和 side/size 聚合；A 股未伪造逐笔方向 |
| AI预测实时更新 | PASS | 新柱/价格阈值/策略或结构状态变化触发真实 V5 模型与风险链；300 秒防抖；每次落新 prediction_id |
| BOS 实时更新 | PASS | 因果 Swing 的 `available_at` 确认，历史确认结果不可提前使用 |
| FVG 实时更新 | PASS | 三 K 线缺口随当前柱重算，保留 CONFIRMED/INVALIDATED |
| Fib 实时更新 | PASS | 已确认 Swing 后生成，未确认状态单独标识 |
| 策略实时更新 | PASS | 每次 Candle 事件重算 30 类策略和去重共振 |
| 断线重连 | PASS | 1/2/4 秒指数退避，最大 30 秒；重连后 HTTP 补齐再恢复 WS |
| 数据假死检测 | PASS | 按数据类型刷新周期的 2x/4x/8x 标为 WARNING/STALE/DISCONNECTED |
| 时间戳 | PASS | source/dataTimestamp/receivedTimestamp/processedTimestamp/serverTimestamp/latencyMs |
| Mock | 0 | 生产采集路径检索与运行审计 |
| Random Market Data | 0 | AI 模块固定随机基线只用于模型对照，不生成任何行情 |

## 自动化测试

- `45 passed in 740.61s`：完整后端回归。
- `5 passed`：实时事件去重、当前柱与换柱、指标/策略链、tradeId 订单流、健康阈值、预测防抖、事件总线。
- `npm --prefix frontend run build`：Vue TypeScript 与生产构建通过。
- `scripts/realtime_e2e_check.py`：运行中后端实际收到 snapshot/ticker/analysis/candle，整条后端 WebSocket 边界 PASS。
- v1.5.0 安装版后端（`127.0.0.1:18765`）再次通过相同端到端检查；健康接口确认 desktop=true、database=ok、frontend=ok。
- `scripts/realtime_live_test.py`：直接观察 OKX 真实 public/business WebSocket，并在 1/5/15 分钟记录唯一价格、时间戳、tradeId、Candle close 与 volume。结果写入被 Git 忽略的 `outputs/realtime-live-test.json`。

真实运行结果（2026-09-07 UTC 06:05:01 至 06:20:03，共 901 秒）：

| 检查点 | Ticker 事件 | 唯一价格 | 唯一成交 ID | Candle 事件 | 唯一 Close | 唯一 Volume |
|---|---:|---:|---:|---:|---:|---:|
| 1 分钟 | 354 | 15 | 91 | 40 | 14 | 39 |
| 5 分钟 | 1,831 | 64 | 485 | 183 | 59 | 175 |
| 15 分钟 | 5,589 | 170 | 1,223 | 583 | 148 | 552 |

三段检查都实际观察到价格时间戳、当前 K 线 close、volume 与逐笔成交变化，真实流检查 `pass: true`。

Windows 安装验收：安装器退出码 0；桌面快捷方式仍指向固定路径 `%LOCALAPPDATA%\Programs\AI行情助手\AI行情助手.exe`；用户数据库仍位于 `%APPDATA%\AI行情助手\database\trading_ai.db`，程序目录与数据目录分离。

## 明确边界

- A 股公开源在本项目中没有可稳定使用的官方逐笔 WebSocket，所以是 15 秒实时增量轮询，不宣称 tick-level。
- 链上数据只对 Blockchair 支持且能返回数据的 BTC/ETH 标记可用；其他币不会生成替代数据。
- 宏观、新闻、Funding、OI、链上数据本身不应秒级变化；“实时”表示后台按政策持续检查并在新观测出现时推送。
- 历史回测只使用当时可得的数据；LIVE 预测带独立 mode、触发原因和新数据库记录。

最终判定以 15 分钟真实运行报告、桌面构建和安装包验收全部成功为准；任一项失败时不得把本版本发布为 REALTIME=PASS。
