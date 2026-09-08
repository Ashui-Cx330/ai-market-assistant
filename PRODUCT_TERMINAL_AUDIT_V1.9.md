# AI行情助手 v1.9.0 产品终端审计

审计日期：2026-09-08  
审计范围：Vue 3 前端、FastAPI 后端、SQLite、实时行情、预测/新闻/回测/模拟交易、Electron、自动更新与 Windows 发布链路。

## 结论

v1.9.0 将 v1.8.0 的功能闭环重构为专业 AI 金融终端的信息架构。生产路径没有 `Math.random()`、随机行情、随机预测、随机新闻或随机收益。AI Score 被定义为当前信号综合评分，不是准确率或上涨保证。数据不足时显示 `INSUFFICIENT_DATA`，不会补造指标。

## 页面与独立路由

| 工作区 | 路由 | 目的 | 状态 |
| --- | --- | --- | --- |
| Market Intelligence | `/` | 5 秒了解市场状态、Pulse、Brief、异动、机会、风险、重要新闻 | PASS |
| Market Scanner | `/market` | 跨市场紧凑行情与组合筛选 | PASS |
| My Watchlist | `/watchlist` | 自选、AI Score/变化、趋势、新闻、风险和排序 | PASS |
| AI Screener | `/screener` | 自然语言条件与真实资产池筛选 | PASS |
| AI Outlook | `/prediction` | T+1/T+5/T+20 概率、证据、样本与模型状态 | PASS |
| Model Lab | `/model-lab` | 样本外表现、基线与历史结算记录 | PASS |
| AI Market Intelligence | `/news` | 全部/利好/利空、原因、对象和 Event Impact | PASS |
| Strategy Lab | `/strategy` | 自然语言规则转换与真实回测 | PASS |
| Backtest Research | `/backtest` | 策略与基准、净值和回撤研究 | PASS |
| Paper Trading Terminal | `/paper` | 持仓、K线、订单票据、确认、挂单与撤单 | PASS |
| AI Market Copilot | `/copilot` | 调用系统真实工具完成分析、比较和筛选 | PASS |
| Settings & Data Health | `/settings` | 数据源、模型、交易、更新、系统和健康状态 | PASS |
| 资产详情 | `/stock/{symbol}`、`/crypto/{symbol}` | 60% K线主工作区与 AI Analysis | PASS |

## 实时行情与数据源

| 市场 | 主链路 | 更新模式 | 说明 |
| --- | --- | --- | --- |
| A股 | 东方财富，腾讯/新浪备用 | 交易时段增量轮询 | 真实公开行情；休市状态可见 |
| 美股 | Yahoo Finance public chart API | 增量轮询 | 免费公开源可能延迟，不是交易所授权逐笔行情 |
| Crypto | OKX，Coinbase 备用 | WebSocket + REST fallback | Ticker/成交/K线持续更新 |

`RealtimeMarketStore` 保留心跳、指数退避重连、陈旧状态判断、服务器时间偏移、全局订阅和当前 K 线增量替换。详情价格含更新时间及轻量涨跌闪动。1m/5m/15m/30m/1h/4h/1D/1W 均有真实 K 线路径；周线当前柱使用最后一根真实日线时间，不标记未来周期结束日期。

## 新闻

- 数据源：东方财富公告、CoinDesk、Cointelegraph、CNBC、BBC Business、Yahoo Finance 等独立公开 Provider。
- 能力：采集、去重、持久化、来源健康、事件/情绪/影响规则分析、标的/板块关系、方向筛选、K线新闻标记。
- 展示：每条新闻说明“为什么”、影响对象与 Impact Score；详情名称统一为 Event Impact。
- 时间轴：仅在有发布后真实价格样本时显示收益，没有 5m/15m/1h/1D 样本时明确显示“样本不可用”。
- 新闻策略回测：Point-in-Time，对齐发布后的第一根可交易 K线；样本不足时返回 `DATA_INSUFFICIENT`。

## AI 预测与 Model Lab

- 模型：PerformanceWeightedEnsemble；Logistic Regression、Random Forest、XGBoost、LightGBM，以及环境可用且样本合理时的 CatBoost。
- 验证：Purged Train/Calibration/Validation/Test、horizon embargo、Walk-forward、概率校准和基线对照。
- 日线目标：T+1、T+5、T+20；每个周期独立显示模型版本、样本、训练时间、数据截止、可用状态和因素证据。
- 深度模型在当前单资产样本规模不足时明确禁用，不冒充 LSTM/Transformer 已投入生产。

NVDA 既有样本外审计结果按用户提供的数据如实展示：

| 周期 | Accuracy | Baseline | Edge | 结论 |
| --- | ---: | ---: | ---: | --- |
| T+1 | 39.47% | 原审计未披露数值 | 不可复算 | No statistical edge |
| T+5 | 50.26% | 48.15% | +2.11% | Weak edge |
| T+20 | 62.23% | 54.79% | +7.44% | Better historical edge |

AAPL、TSLA、BTC 没有可复核 T+1/T+5/T+20 记录时显示 `INSUFFICIENT_DATA`；本机数据库另行展示已经到期结算的真实预测历史，不混为上述审计结果。

## 策略与回测

- 自然语言规则当前安全支持：RSI 阈值 + 固定持有期、MACD 交叉、MA5/MA20。无法解析的文本会被拒绝，不转换成模糊策略。
- 信号在收盘 T 生成，只能在 T+1 开盘执行；回测计入手续费与滑点。
- 输出：净收益、年化收益、胜率、盈亏比、最大回撤、Sharpe、交易次数、基准收益、超额收益、Strategy/Benchmark 净值曲线和 Drawdown Curve。
- 真实 NVDA 验收样例（2026-09-08 运行，结果随真实历史区间变化）：RSI<30、持有5日，5笔已闭合交易；三条曲线长度一致。该结果只验证引擎可执行，不代表策略有效。

## 模拟交易

- 支持：CNY/USD/USDT 模拟账户、市价、限价、资金/持仓冻结、真实当前报价成交、挂单条件成交、撤单、部分卖出、全部卖出、订单与持仓持久化。
- v1.9 布局：左持仓、中 K线、右订单票据；Open Orders/Positions/Trades/History 页签。
- 下单前必须经过二次确认弹窗，明确 Symbol、方向、数量、类型、估算价格与金额。
- 持仓订阅全局实时 Store；行情事件更新市场价值、浮盈亏和收益率。

## AI Copilot

Copilot 是确定性工具路由层，不是假装能访问数据的聊天框。

- “分析 NVDA/BTC”：依次调用 `market.quote`、`market.kline_indicators`、`news.lookup`。
- “比较 NVDA 和 AMD”：分别调用两个标的的真实工具后比较 AI Score 与 Risk Score。
- “找出值得关注的股票”：调用 `terminal.scanner`，返回当前真实筛选结果。
- 每条回答显示工具状态和数据截止时间；外部源失败会返回错误，不生成替代答案。

2026-09-08 本机真实验收：NVDA 来自 Yahoo Finance public chart API，三项工具调用全部 SUCCESS；首页跨市场聚合返回 5 个机会，本次 0 个 Provider 错误。

## UI 与错误处理

- 深色、高对比、少强调色、直角/小圆角、紧凑表格与工作区布局；没有大面积渐变。
- 首页、行情、详情、预测、新闻、策略、交易各自回答不同产品问题，不再重复同一套卡片。
- Skeleton、Empty State、Error + Retry 已覆盖关键异步页面。
- AI Score、Prediction、Confidence、RSI、MACD、BOS、CHoCH、FVG、Volume Ratio、Impact Score、Risk Score 使用统一 Tooltip 组件。
- 桌面 Playwright E2E：路由、Scanner、K线、1W、Tooltip、Model Lab、策略解析、订单确认、Copilot、新闻、Data Health 全部 PASS。

## Electron、更新与数据保留

- 安装：NSIS 当前用户固定目录 `%LOCALAPPDATA%\Programs\AI行情助手`。
- 快捷方式：始终指向固定的 `AI行情助手.exe`，更新后无需重建。
- 用户数据：`%APPDATA%\AI行情助手`，与安装目录分离。
- 发布：GitHub Releases `Ashui-Cx330/ai-market-assistant`；安装包、`latest.yml`、`.blockmap`。
- 更新：检查、提示、下载、SHA512/Blockmap 校验、静默安装、自动重启。
- 回滚：更新前备份、启动健康检查、失败恢复、坏版本阻止和次数记录。

## 自动化验收

- Python：61 tests PASS（含终端评分确定性和自然语言规则严格拒绝）。
- 前端：Vue TypeScript + Vite production build PASS。
- 真实数据：A股、美股、Crypto、News、AI 健康检查本机均 Connected；NVDA Scanner/Copilot、跨市场 Dashboard、1W K线与自然语言真实回测 PASS。
- Electron development E2E：PASS。
- Windows NSIS 打包、`latest.yml`/`.blockmap`/SHA512 校验与 packaged Electron E2E：PASS。

## 外部依赖与风险

- 本版核心功能不要求用户提供 API Key。公开 Provider 可能限流、延迟或在部分网络环境不可达，产品会显示具体错误与降级来源。
- 没有稳定授权基本面数据时不显示伪基本面评分。
- 当前 Windows 安装包未配置 Authenticode 代码签名证书，可能显示“未知发布者”；可信发布者签名需要证书主体后续申请，不阻塞功能和更新。
- AI Score 资产池是明确披露的高流动性跨市场列表加本地自选，不宣称覆盖全市场。

## 最终状态

功能与产品验收：PASS。  
金融免责声明：所有评分、概率、新闻分析和回测仅用于研究与模拟，不构成投资建议或收益承诺。
