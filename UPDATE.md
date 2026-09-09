# AI行情助手自动更新与发布

当前代码版本：**v1.9.7**。更新仓库：`Ashui-Cx330/ai-market-assistant`。只有在本地构建通过并向 GitHub Release 上传安装包、`.blockmap` 和 `latest.yml` 后，才会成为用户可检测的正式更新；未发布版本不会伪装成线上更新。

## v1.9.7 / 单实例锁交接修复

- 更新后的干净重启会等待旧 Electron 主进程完全退出，再启动新版，避免与单实例锁竞争。
- 保留 v1.9.6 的用户数据目录校正和更新健康检查逻辑。

## v1.9.6 / 安装器环境自动脱离

- 新版以 `--updated` 启动并通过健康检查后，自动脱离 NSIS 交接环境并且只做一次干净重启。
- 干净重启前停止后端，重启后继续使用固定桌面快捷方式和原用户数据目录。

## v1.9.5 / 更新交接验收版

- 用于实际验证 v1.9.4 更新器的安装前后端进程树停止与新版数据库健康启动。

## v1.9.4 / 更新进程交接修复

- 安装器接管前显式终止当前客户端拥有的后端进程树，避免新版窗口短暂复用旧版后端。
- 自动检查和手动检查两条更新入口共用同一安全交接，备份与回滚状态在停服务前已落盘。

## v1.9.3 / Windows 持久化路径强制修复

- 桌面启动器传入数据目录时始终优先使用该目录，禁止导入期 `DB_PATH` 或 PyInstaller `_MEI` 临时路径覆盖。
- 增加实际写入与重新读取回归，确保安装版真正读写 `%APPDATA%\AI行情助手\database\trading_ai.db`。

## v1.9.2 / Windows 用户数据路径修复

- 数据库路径改为每次连接时重新解析桌面启动器传入的 `%APPDATA%\AI行情助手` 目录。
- 防止 PyInstaller one-file 后端误用 `_MEI` 临时解压目录中的数据库，确保自选、订单、持仓、回测和预测历史可持久保留。
- 健康接口报告当前实际数据库路径，并新增打包运行时路径回归测试。

## v1.9.1 / 加载性能与连接稳定性修复

- 资产详情把报价、K线、指标和 AI Score 合并成一次后端请求，移除三组重复外部行情请求。
- AI 选股限制同时访问的数据源数量，设置 18 秒批次预算、单资产超时和 60 秒结果缓存；外部源异常时不再无限显示骨架屏。
- 美股分钟报价路由不可达但真实K线可用时，明确使用带时间戳的最新真实K线降级，不伪造实时价格。
- 实时行情改为打开资产后按需订阅，取消启动时无条件连接 BTC/OKX；区分本地 WebSocket 状态与单资产行情新鲜度。
- Element Plus 按组件加载，ECharts 仅在详情/回测页异步加载；首屏 JS 由约 2.20 MB 降至约 196 KB，CSS 由约 384 KB 降至约 39 KB。

## v1.9.0 / 专业 AI 金融终端

- 重构为市场、AI分析、策略、交易、AI、系统六组工作区，新增 Market Scanner、AI Screener、Model Lab 和工具型 AI Copilot。
- 详情页以实时K线为主，AI Score 拆解趋势、技术、新闻、动能和风险，并明确它不是准确率。
- 日线 AI Outlook 显示 T+1/T+5/T+20 概率、样本、模型状态、训练时间和可解释因素；Model Lab 如实披露 NVDA 样本外弱项与优势。
- 新闻统一为 Event Impact；自然语言策略转成可审计规则；回测新增基准、年化、Sharpe 和回撤曲线。
- 模拟交易改为三栏终端并强制订单确认；设置新增真实探测的数据健康中心与美股延迟声明。

## v1.8.0 / 可操作 AI 行情终端

- 首页、行情、新闻、预测、策略、模拟交易、自选使用独立路由与独立工作区。
- 美股搜索、报价与 K 线接入 Yahoo Finance 公开 Chart API；A股使用东方财富/腾讯备用源，Crypto 使用 OKX WebSocket。
- 新闻详情明确分开已发生事实、AI规则判断与未校准市场预测，不把汇总预测冒充单篇新闻结果。
- 模拟交易支持市价、限价、冻结资产、条件成交、撤单、持仓标记、今日/累计盈亏和账户重置。
- 修复 WebSocket 并发写入、关闭竞态与握手顺序，并提供 30 秒真实流验收脚本。

## v1.7.0 / 真实新闻情报与事件回测

- 新闻中心改为东方财富公告、CoinDesk、Cointelegraph、CNBC、BBC Business、Yahoo Finance 六个独立真实源。
- 增加 Provider 健康状态、SQLite 缓存降级、模糊转载去重、搜索筛选与 20 条分页。
- 修复宏观新闻被强行关联到查询股票的问题，只保存公告元数据或标题/摘要明确提及的实体关系。
- 增加结构化方向、Impact Score、判断原因、直接/间接/反向影响以及 K 线新闻点击详情。
- 重构 Point-in-Time 新闻事件回测，支持方向、最低影响、最低置信度、T+1/3/5/10/20，并持久化真实价格对齐结果。

## v1.6.1 / V7 UI 完整性补丁

- 首页新增基于真实新闻的市场总结、核心驱动和重点板块/风险。
- 新闻中心补齐 AI 关注名单、AI 风险名单和历史相似事件展示。
- v1.6.0 保留为更新失败时的稳定回滚版本。

## v1.6.0 / V7

- OKX 真实逐笔成交驱动当前蜡烛，一个资产流同步聚合 1m/5m/15m/30m/1h/4h/1D。
- 指标/结构后台单航班重算，不阻塞 WebSocket；新增实时价线、VWAP、ADX、量比和新闻 K 线标记。
- 新增 AI Market Intelligence：多 Provider、事件提取、利好利空、影响图谱、板块雷达、关注/风险名单和证据型交易观点。
- 新增标准化新闻数据库与严格 Point-in-Time 新闻回测；样本不足不展示伪造准确率。
- A 股休市显示 `MARKET_CLOSED`，数据源不可用时明确报错。

## v1.5.1 / 模型保存热修复

- 修复 Windows Roaming Profile / reparse path 环境下保存模型出现 `[WinError 17]` 的问题。
- 模型保存增加同目标线程锁和唯一临时文件，避免自动实时预测与手动预测并发写入冲突。
- 跨卷替换自动降级为可恢复复制；写入前继续保留 `.previous.joblib` 备份。

## v1.5.0 / V6

- 新增后端常驻 RealtimeDataManager、事件总线和统一 RealtimeMarketStore。
- Crypto 使用 OKX 公开 WebSocket 持续接收 Ticker、当前 K 线、逐笔成交与五档盘口；A 股按公开源限制每 15 秒强制重新请求。
- 当前 K 线实时更新 OHLCV，换周期自动追加；同步重算技术指标、30 类策略、BOS/CHoCH/FVG/Fibonacci 与动态风险。
- 新增预测条件触发和 5 分钟防抖，预测以新的数据库记录保留，不覆盖历史预测。
- 新增断线指数退避、重复消息过滤、数据假死检测、服务器时间校准、连接状态/延迟/最后更新时间显示。
- 首页、详情和策略使用同一全局 Store，页面切换不停止后端同步。

## v1.4.0 / V5

- 统一 30 类因果技术策略与信息家族去重共振。
- 新增因果 Swing、BOS、CHoCH、三K线 FVG、Fibonacci 及组合策略。
- 新增技术策略雷达、真实结构图覆盖层、策略排行榜和实验 API。
- 新增策略 Walk-forward、参数锁定优化、ICT 特征 ML 消融、ECE/reliability。
- Order Flow、期权和历史新闻缺数据时明确禁用，绝不生成替代数据。

## 当前实现

- Electron 使用 `electron-updater`，启动后异步检查更新；设置页也提供“检查更新”。
- GitHub Publisher 从构建环境变量 `GH_OWNER`、`GH_REPO` 读取，不在源码、前端或安装包中保存 Token。
- 配置真实仓库后，electron-builder 同一次构建生成安装包、`.blockmap`、`latest.yml` 和客户端内置的 `app-update.yml`。
- 下载由 electron-updater 校验；下载失败不会修改旧程序。
- 安装前将当前稳定程序完整备份至 `%LOCALAPPDATA%\Temp\AI行情助手-update-backups`，并启动独立的隐藏回滚守护。
- 新版启动后验证 Electron、Renderer、本地后端、SQLite、核心健康 API 和首页。成功后确认新版并清理备份。
- 超时或启动失败会恢复旧程序、重新启动旧版、记录 `update.log`，并把失败版本加入阻止列表。
- 更新状态持久化在 `%LOCALAPPDATA%\Programs\AI行情助手 Update State\update-state.json`。
- 用户数据库与程序分离，位于 `%APPDATA%\AI行情助手\database`。

## 一键发布

GitHub CLI 登录一次后，直接运行：

```powershell
.\release.bat
```

脚本会自动读取当前 GitHub 用户和 origin 仓库。不指定版本时自动增加 PATCH 版本，并依次统一版本号、构建、校验三个发布资产、提交代码、推送 GitHub、创建 Release、复核线上资产。任何检查失败都会停止并指出失败步骤。

`scripts\release-check.ps1` 验证版本、Tag、安装包、latest.yml 必需字段、SHA512、blockmap 内部块总大小、内置 updater 仓库、GitHub Release、桌面快捷方式和数据目录分离。

GitHub CLI 使用系统凭据库登录。Token 仅由 GitHub CLI/运行环境使用，不会进入源码、客户端或 Release。正式发布资产统一采用 ASCII 文件名，避免 GitHub 更新元数据与实际资产名称不一致。
