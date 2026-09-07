# AI行情助手 V7：实时 K 线与新闻情报审计

核查日期：2026-09-07。生产模式不生成随机行情、随机新闻或虚构准确率。

## 实时 K 线改造

- 唯一事实源：OKX `trades` WebSocket 的真实逐笔成交。
- 一个币种只建立一条公共行情流，每笔成交同时更新 `1m/5m/15m/30m/1h/4h/1d` 当前柱。
- 同一时间桶保持 open，实时更新 high、low、close、volume、amount；跨桶确认旧柱并建立新柱。
- 蜡烛事件立即发送给前端；指标和结构分析采用“最多一个后台任务”的单航班节流，不阻塞后续成交。
- MA5/10/20/60、EMA12/26、VWAP、MACD、RSI、KDJ、BOLL、ATR、ADX、OBV、量能均线和量比使用最新当前柱重新计算。
- A 股数据源没有公开逐笔 WebSocket 时，保留真实 15 秒增量轮询；非交易时段显示 `MARKET_CLOSED`，不伪造 Tick。

### 2026-09-07 真实验收

命令：`.venv\Scripts\python.exe scripts\realtime_tick_acceptance.py`

- 来源：OKX trades WebSocket；测试时 BTC/USDT 连续交易。
- 30 秒处理 35 批真实成交；首个成交到 K 线更新 0.02 秒。
- 价格：79420.0 → 79426.8 → 79426.8 → 79437.2。
- 1m 当前柱成交量：0.19516874 → 0.21803989 → 0.26124448 → 0.63767448。
- RSI：49.19976595 → 51.26991705 → 54.12882781；MACD：-12.50657066 → -11.13449089。
- 七周期同一成交收盘价一致，时间桶分别正确对齐。结果来自当次公网观察，不代表未来每 5 秒价格一定变化；无成交时系统不会伪造变化。

## 新闻情报架构

`NewsProvider` 抽象下提供 `MarketNewsProvider`、`CompanyNewsProvider`、`MacroNewsProvider`、`AnnouncementProvider` 和通用 `RSSProvider`。第一阶段真实来源为 Google News RSS，保存原标题、来源、链接、发布时间、采集时间和 Provider。单个 Provider 失败不会生成替代新闻，而会进入 `provider_errors`。

数据落入独立表：`news`、`news_events`、`news_sentiment`、`news_impacts`、`news_stock_relations`、`news_sector_relations`、`historical_events`、`news_prediction_signals`、`trading_decisions`。

当前事件与情感方法是明确标注的 `auditable financial event lexicon v1`：输出事件类型、分类、-100~100 情绪、一级/二级/反向影响、行业映射、Impact Score、证据词和置信度。它不是 FinBERT，也不是 LLM。T+1/T+3/T+5 是未校准证据估计；真实结算样本不足时，历史准确率为 `null`。

新闻回测只允许 `published_at` 之后的第一根 K 线开盘成交；缺失发布时间的新闻禁止进入回测。少于 10 个已结算样本返回 `DATA_INSUFFICIENT`，不展示误导性胜率。

## 开源调研结论

- `ProsusAI/finBERT`：Apache-2.0，英文金融文本 BERT，原仓库依赖较旧的 `pytorch_pretrained_bert`。本版本只参考“正/负/中性分离和概率差分”的研究方向，未复制或打包模型。
- `zhaymn/StockIntel`：MIT，FastAPI/Next.js/PyTorch/LightGBM/LSTM；参考其 Purged Walk-forward、校准门、拒绝预测和“文本情绪与价格影响分离”的设计，未复制代码。
- `PandOvo/FinNews-Sentiment2Signal`：Python 词典/Transformer/IC/含成本回测思路，但 GitHub API 未识别到许可证，且示例数据明确为合成数据，因此未引入代码或数据。
- `overlandflight/PokieTicker_A-main`：能定位到同名仓库，但 GitHub API 未识别到许可证，因此未复制代码。另一个 A 股改造分支有 MIT 标识，但不是任务中可唯一确认的原项目。
- `valuesimplex/FinBERT`：中文金融模型方向可供后续离线模型 Provider 评估；本次未增加大模型下载和 PyTorch 打包体积。

## 当前限制

- Google News RSS 不是交易所公告直连，覆盖、延迟和实体相关性可能不完整；页面显示原始来源供人工核验。
- 规则情绪无法可靠处理反讽、否定嵌套和复杂中文金融语义。接入中文金融模型前不会标成“AI 模型准确率”。
- 刚开始积累事件数据，新闻历史回测当前可能返回样本不足；这是真实状态。
- 历史相似事件目前按事件类型、类别和行业映射检索，收益结果需要后续逐日积累并结算。
