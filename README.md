# AI行情助手

本地运行的 A 股与加密货币行情研究平台，提供真实行情、K 线、技术指标、机器学习概率预测、历史回测、自选和模拟交易。系统不生成 Mock 行情，不连接真实交易账户，也不构成投资建议。

## Windows 安装

双击 `outputs\desktop\AI-Market-Assistant-Setup-v1.0.0.exe` 完成安装。桌面会出现“AI行情助手”，以后直接双击即可；无需打开项目目录、Python、Node、Docker 或命令行。

- 程序目录：`%LOCALAPPDATA%\Programs\AI行情助手`
- 用户数据：`%APPDATA%\AI行情助手`
- 卸载入口：Windows“已安装的应用”或开始菜单卸载项
- 自动更新：启动自动检查，并可在“设置与更新”手动检查；真实 GitHub 发布方法和当前外部阻塞见 `UPDATE.md`

## 已实现功能

- 股票名称/代码和币种动态搜索，真实详情报价。
- 1 分钟到日线的多周期 K 线，支持缩放和拖动。
- MA、EMA、MACD、RSI、KDJ、BOLL、ATR、OBV 和量能指标。
- RandomForest 上涨/震荡/下跌概率，展示训练样本、数据时间与 Walk Forward 准确率。
- MA、MACD、RSI、AI、AI+技术五种历史策略回测。
- CNY/USDT 模拟账户、真实当前价模拟买卖、持仓、订单和回测历史。
- SQLite 自选与用户记录持久化。

## 数据源与失败处理

- A 股：东方财富，失败时切换腾讯证券。
- 加密货币：OKX，失败时切换 Coinbase；首页还支持 Binance 源。
- 请求使用短时缓存并标注数据源。全部数据源失败时返回明确错误，页面提供重试，不伪造价格。

## 开发与测试

后端开发启动：`python -m uvicorn backend.main:app --reload`  
前端开发启动：在 `frontend` 中运行 `npm run dev`  
API 文档：`http://127.0.0.1:8000/api/docs`

自动化测试包括真实网络后端测试、前端生产构建、桌面端安装校验及 Playwright Electron 端到端操作。桌面打包入口为 `scripts\build_desktop.ps1`。
