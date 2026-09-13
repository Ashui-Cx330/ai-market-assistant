# AI行情助手 v1.14.0 Implementation Plan

生成日期：2026-09-13  
原则：保留全部历史记录；不改变历史标签、回测、Prediction Snapshot；不自动晋级 Champion；没有真实 OOS 优势时保持 `NO EDGE / Production Model NONE`。

## 当前实现与现场问题

| 领域 | 当前实现 | 已确认问题 |
|---|---|---|
| Frontend | Vue 3 单页 Quant Research UI | 长研究为同步 HTTP；没有任务队列、取消、缓存命中状态与八维 Edge Diagnosis |
| Desktop | Electron、NSIS、electron-updater、回滚守护 | 工程链路已通过；本轮需完整回归，不重写更新器 |
| Backend | FastAPI + 本地 PyInstaller 服务 | Settlement 只在用户再次预测同一 symbol 时执行，没有全局到期扫描 |
| Database | 用户目录 SQLite、增量 `CREATE/ALTER` | 缺 Symbol Master、Universe Membership、Candle Store、Settlement Audit、Research Job/Cache、Provider Health 明细字段 |
| Symbol | 独立 symbol-registry.sqlite3 + seed/网络刷新 | 字段不足；A股仅5个 seed，美股仅5个 seed；A股列表刷新失败时 Universe 无法扩张 |
| Prediction | 旧预测表 + Quant Snapshot 表 | 1,678条中 BTC 占1,669；NVDA/SNDK 已到期1D仍未结算；无后台扫描；XSNDK 被误存为 crypto |
| Calendar | 股票统一按上海时区/工作日；训练按实际 bars | 美股错误复用上海时区；未来展示仅跳周末；Settlement 不应依赖预先估算 target timestamp |
| Research | Quant V3、57因子、5窗、模型竞赛、组合回测 | 每市场仅5资产；无持久 Candle Universe；Factor 单因子研究字段不完整；无行业/市值/Beta中性数据 |
| News/Event | 540新闻、11 settled events、结构相似度 | 新闻仍不足30；Provider 健康状态不做新鲜度判断；缺 News Leakage 独立审计与增量对照实验 |
| Market structure | 当前值 API + 缺失项显式标记 | 不能将当前 OI/Funding/VIX 等用于历史；Point-in-Time 历史缺失必须保持 UNAVAILABLE |
| Governance | Registry/Champion 字段和生产门禁 | 当前用户库 registry/research runs 均为0；必须由任务运行后持久化，仍禁止自动晋级 |

## 根因假设（先测试后修复）

1. `resolve_prediction_history(symbol, candles)` 只由 `/api/ai/predict` 调用，因此没有再次预测的股票永远不结算。
2. 结算 SQL 只按 symbol 查找，未把 asset_type/market/interval 作为完整身份，可能产生别名或周期错配。
3. 股票目标时间用上海交易时间统一计算，美股日历语义不正确；正确结算应基于预测后真实观测交易 bars。
4. 研究 Universe 小不是模型参数问题，而是 Symbol Master/历史 Candle Store/批量增量抓取尚未建立。

## 实施顺序与修改范围

### Phase 1 — Baseline Audit

- 新增 `backend/v114_audit.py` 与只读审计 API。
- 生成 `V1_14_BASELINE_AUDIT.md`，直接读取用户 SQLite 和真实行情结果。

### Phase 2 — Prediction Settlement

- 新增 `backend/settlement.py`：`TradingCalendar`、`PredictionSettlementEngine`。
- 以真实后续 bars 计算 CN T+1/T+5/T+20、US 1D/5D/20D、Crypto 1H/4H/24H/7D。
- 增加后台到期扫描、逐项审计状态和失败原因；历史预测只填充空的结算字段。
- 修改 `backend/database.py`、`backend/main.py`、`backend/realtime.py`。

### Phase 3 — Symbol Master

- 升级 `backend/symbol_registry.py` 为统一 Symbol Master，补 canonical symbol、market、exchange、currency、timezone、session、provider symbol、active/delisted、sector/industry 与 alias。
- 保持现有搜索接口兼容，新增审计/解析 API。

### Phase 4 — Universe/Data Expansion

- 新增 Universe 与 membership 版本表，记录 effective_from/effective_to，不能把今日成分倒灌历史。
- A股优先真实公开证券列表；美股先建立至少100只可验证流动股票研究池；Crypto 从实时交易所列表筛选真实 USDT 现货并记录版本。
- 新增 Candle Store 和增量更新，只抓 last timestamp→now，执行 gap/duplicate/order/OHLC 审计。

### Phase 5–13 — Research V4

- 在 `backend/quant_v3.py` 上演进，不复制一套不兼容模型。
- 同时保留固定阈值 baseline 与 train-only volatility threshold。
- 加入完整 baseline、Factor Research 2.0、Z-score/Rank/Winsor、可用时中性化、5–10窗聚合、Regime 指标、News A/B、Event Study、Snapshot V4、Drift 与严格生产门禁。
- 新增 `backend/alpha_research_v4.py`、`backend/research_jobs.py`；缓存以 dataset/feature/model hash 失效。

### Phase 14 — Quant Research Cockpit

- 修改 `frontend/src/App.vue`、`TerminalSidebar.vue`、样式与 API client。
- 增加 QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED、取消按钮、缓存命中、Signal/Evidence/Risk/Model Health 和八维 Edge Diagnosis。

### Phase 15–16 — Regression/Packaging

- 执行 Backend、Frontend、Integration、Packaged E2E、Installer、Updater 测试。
- 版本统一为 v1.14.0，生成安装包、latest.yml、blockmap；先备份用户数据库，再安装验证数据计数不减少。

## 数据库 Migration（只增不删）

- `symbol_master`
- `research_universes`、`research_universe_members`
- `market_candles`
- `prediction_settlement_audit`
- `research_jobs`、`research_cache`
- `provider_health_events`
- Prediction 表新增 `market/exchange/settlement_status/settlement_attempted_at/settlement_source`（仅填空值）
- Quant Snapshot 新增 V4 payload 字段仍保存在不可变 JSON，不更新旧 payload。

迁移前复制数据库到用户目录 `backups/`，校验 SHA256；迁移必须幂等，禁止 DROP/TRUNCATE/DELETE。

## API 变化

- `GET /api/v1.14/baseline-audit`
- `POST /api/v1.14/settlements/run`、`GET /api/v1.14/settlements/status`
- `GET /api/v1.14/symbols/resolve`、`GET /api/v1.14/universe`
- `POST /api/v1.14/research/jobs`、`GET/DELETE /api/v1.14/research/jobs/{id}`
- `GET /api/v1.14/research/report`、`GET /api/v1.14/edge-diagnosis/{asset}`
- 旧 API 保持兼容。

## 测试计划

- 新增 SymbolMaster、CN/US/Crypto Calendar、Settlement、News Timestamp、Leakage、Factor、Walk-Forward、Cross-sectional、Event Study、Provider Health、Governance、Snapshot、Cache、Migration/Backup 测试。
- 结算重点覆盖：美股跨周末、A股 T+1、Crypto 连续时间、目标日无 candle、别名、错误 asset type、重复执行幂等。
- 用用户数据库副本运行修复演练；不得直接用真实数据库做破坏性测试。

## 风险与降级

- 免费公开源可能限流或阻断；Universe 达不到目标时报告真实数量，不用静态假数据补齐。
- 当前成分列表无法消除历史存活偏差；缺 effective membership 时标记 `SURVIVORSHIP_BIAS_UNRESOLVED`。
- 行业/市值/Beta、新闻、衍生品历史不足时相应中性化/实验返回 `UNAVAILABLE`。
- 大 Universe 的完整研究可能耗时数小时，必须后台执行、可取消、缓存和增量更新。
- 任何门禁失败：`Champion = NONE`、`Production Model = NONE`。
