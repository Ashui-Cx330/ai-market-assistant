# AI行情助手 V5 技术策略升级前审计

审计日期：2026-09-07；基线版本：v1.3.0 / V4。

## 扫描范围

已检查前端、FastAPI 后端、真实行情适配器、指标、ML 预测、回测、风险、新闻、宏观、资金代理、链上、SQLite、测试和 Electron 自动更新代码。

| 模块 | 升级前状态 | 事实 |
|---|---|---|
| 实时/历史行情 | PASS | A股与 Crypto 使用公开行情 API；失败时抛错，不生成替代价格 |
| ML 模型 | PASS | Logistic Regression、Random Forest、XGBoost、LightGBM；CatBoost 可选 |
| 概率校准 | PARTIAL | 已有 Platt、Brier、Log Loss，没有 ECE/reliability bins |
| Walk-forward | PARTIAL | ML 已滚动验证；独立技术策略只有少量简单规则 |
| Purged/Embargo | PASS（ML） | 训练/校准/验证/测试有预测期隔离 |
| 技术指标 | PARTIAL | MA5/10/20/60、MACD、RSI、KDJ、Bollinger、ATR、OBV |
| 统一策略接口 | FAIL | 不存在 StrategyEngine，策略散落在指标评分和回测条件中 |
| ICT/SMC、BOS、CHoCH、FVG | FAIL | 没有可独立审计的因果实现 |
| Fibonacci | PARTIAL | 仅用于支撑压力候选，没有独立策略与增量验证 |
| 形态策略 | FAIL | 双顶底、头肩、三角、楔形、旗形未接入 |
| Order Flow | FAIL/NO DATA | 只有 OHLCV 资金流代理，没有逐笔主动成交/订单簿 |
| 期权策略 | FAIL/NO DATA | 没有真实期权链适配器 |
| 风险系统 | PASS/PARTIAL | 已有结构+ATR+历史 MAE/MFE，但 V5 策略未统一使用 |
| 策略排行榜/实验室/结构图 | FAIL | 只有通用回测，K线没有结构覆盖层 |

## 泄漏与数据边界

V3 当前快照结构检测使用居中 rolling pivot，不能直接回填为历史信号，否则右侧 K 线会泄漏。V5 历史策略必须使用带 `available_at` 的因果 Swing。

- 原回测规则有固定阈值且没有参数锁定流程。
- 历史新闻不足：`HISTORICAL_NEWS_ALIGNMENT_FAILED`。
- Order Flow：`ORDER_FLOW_DATA_UNAVAILABLE`。
- 期权链：`OPTIONS_DATA_UNAVAILABLE`。
- 未发现生产预测使用 Mock、固定涨跌结果或随机交易信号。随机分类器只用于明确标注的研究基线，不参与最终预测。

保留 V4 的真实行情、模型校准、Purged/Embargo、风险与数据库层；新增因果 StrategyEngine、策略实验 API、结构图和审计测试，不更换技术栈。
