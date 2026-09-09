# AI行情助手

当前版本 v1.10.1 在专业 AI 金融终端基础上完成加载性能、连接稳定性、用户数据路径与更新进程交接修复。审计与实测结果见 [PRODUCT_TERMINAL_AUDIT_V1.9.md](PRODUCT_TERMINAL_AUDIT_V1.9.md)。

本地运行的 A 股与加密货币行情研究平台，提供真实行情、K 线、技术指标、机器学习概率预测、历史回测、自选和模拟交易。系统不生成 Mock 行情，不连接真实交易账户，也不构成投资建议。

## Windows 安装

双击 `outputs\desktop\AI-Market-Assistant-Setup-v1.10.1.exe` 完成安装。桌面会出现“AI行情助手”，以后直接双击即可；无需打开项目目录、Python、Node、Docker 或命令行。

- 程序目录：`%LOCALAPPDATA%\Programs\AI行情助手`
- 用户数据：`%APPDATA%\AI行情助手`
- 卸载入口：Windows“已安装的应用”或开始菜单卸载项
- 自动更新：启动自动检查，并可在“设置与更新”手动检查；真实 GitHub 发布方法见 `UPDATE.md`

## 已实现功能

- 股票名称/代码和币种动态搜索，真实详情报价。
- 1 分钟到日线的多周期 K 线，支持缩放和拖动。
- MA、EMA、MACD、RSI、KDJ、BOLL、ATR、OBV 和量能指标。
- Logistic Regression + RandomForest + XGBoost + LightGBM（CatBoost 可用时加入）验证集表现加权集成，独立预测真实 1H/4H/1D 目标。
- 动态三分类阈值、Platt 概率校准、Purged Walk-forward、按 horizon 设置 Embargo、隔离最终测试集、Baseline 对照与数据质量等级。
- 因子可用性与自动降级；外部数据不可用时明确显示 `NO_DATA`，不使用 Mock。
- V3 市场状态、量价资金流/背离、Crypto OI/Funding、资金轮动、市场结构及多周期矩阵。
- 数学支撑压力区、强度、突破概率、历史优化动态止损、三档止盈、仓位、R:R、期望值和 NO_TRADE 决策。
- 预测历史自动落库，到期后使用真实 K 线核验 Accuracy/F1/Brier/LogLoss、止损/止盈命中率、Average R 和 Profit Factor。
- V4 市场快照、跨资产滚动相关、结构化新闻去重、特征存储、因子消融、预期收益/波动、MAE/MFE、异常检测、失效条件与组合 VaR/CVaR。
- V5 统一 30 类技术策略，因果 Swing、BOS、CHoCH、三K线 FVG、Fibonacci 组合、去重共振和多周期冲突降权。
- V6 进程级实时行情管理器：OKX Ticker/Candle/逐笔成交/盘口 WebSocket、A 股 15 秒增量请求、断线指数退避、假死检测、全局前端 Store、实时指标/结构/策略/风险与条件触发预测。
- V7 真实逐笔成交同时聚合 7 个 K 线周期；当前蜡烛、实时价线、成交量、MA/EMA/VWAP/RSI/MACD/ADX 及 BOS/CHoCH/FVG/Fibonacci 随最新柱重算。
- AI 新闻情报中心：真实 RSS、多 Provider 抽象、事件/情绪/影响图谱、板块雷达、关注/风险名单、T+1/T+3/T+5 证据估计、个股情报和 Point-in-Time 新闻回测。规则引擎不会冒充 FinBERT 或伪造准确率。
- 技术策略雷达、K线结构覆盖层、策略排行榜、独立回测、Walk-forward、参数锁定优化和 ICT 特征 ML 消融。
- MA、MACD、RSI、AI、AI+技术五种历史策略回测，计入手续费和滑点。
- CNY/USDT 模拟账户、真实当前价模拟买卖、持仓、订单和回测历史。
- SQLite 自选与用户记录持久化。

V7 的真实数据边界、30 秒 Tick 验收和开源调研见 `NEWS_INTELLIGENCE_AUDIT.md`。

## 数据源与失败处理

- A 股：东方财富，日内失败时切换新浪财经，日线失败时切换腾讯证券。
- 加密货币：OKX，失败时切换 Coinbase；首页还支持 Binance 源。
- 请求使用 SQLite TTL 原始数据缓存并标注数据源，最终预测不缓存。全部数据源失败时返回明确错误，页面提供重试，不伪造价格。V5 的升级前后边界见 `TECHNICAL_STRATEGY_AUDIT.md` 和 `FINAL_TRADING_STRATEGY_AUDIT.md`。

## 开发与测试

后端开发启动：`python -m uvicorn backend.main:app --reload`  
前端开发启动：在 `frontend` 中运行 `npm run dev`  
API 文档：`http://127.0.0.1:8000/api/docs`

自动化测试包括真实网络后端测试、前端生产构建、桌面端安装校验及 Playwright Electron 端到端操作。桌面打包入口为 `scripts\build_desktop.ps1`。
