# AI行情助手自动更新与发布

当前代码版本：**v1.6.1**。更新仓库：`Ashui-Cx330/ai-market-assistant`。只有在本地构建通过并向 GitHub Release 上传安装包、`.blockmap` 和 `latest.yml` 后，才会成为用户可检测的正式更新；未发布版本不会伪装成线上更新。

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
- 安装前将当前稳定程序完整备份至 `%APPDATA%\AI行情助手\update-backups`，并启动独立的隐藏回滚守护。
- 新版启动后验证 Electron、Renderer、本地后端、SQLite、核心健康 API 和首页。成功后确认新版并清理备份。
- 超时或启动失败会恢复旧程序、重新启动旧版、记录 `update.log`，并把失败版本加入阻止列表。
- 更新状态持久化在 `%APPDATA%\AI行情助手\update-state.json`。
- 用户数据库与程序分离，位于 `%APPDATA%\AI行情助手\database`。

## 一键发布

GitHub CLI 登录一次后，直接运行：

```powershell
.\release.bat
```

脚本会自动读取当前 GitHub 用户和 origin 仓库。不指定版本时自动增加 PATCH 版本，并依次统一版本号、构建、校验三个发布资产、提交代码、推送 GitHub、创建 Release、复核线上资产。任何检查失败都会停止并指出失败步骤。

`scripts\release-check.ps1` 验证版本、Tag、安装包、latest.yml 必需字段、SHA512、blockmap 内部块总大小、内置 updater 仓库、GitHub Release、桌面快捷方式和数据目录分离。

GitHub CLI 使用系统凭据库登录。Token 仅由 GitHub CLI/运行环境使用，不会进入源码、客户端或 Release。正式发布资产统一采用 ASCII 文件名，避免 GitHub 更新元数据与实际资产名称不一致。
