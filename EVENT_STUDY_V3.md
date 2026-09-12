# Event Study V3

新闻仍为 `EXPERIMENTAL`，生产概率权重为 0。

本机已保存 540 条真实新闻，但只有 11 条完成严格新闻发布时间 → 首个更晚交易 bar → T+N 价格结算的历史事件，低于最小 30 条门槛。因此不公布“新闻胜率”，也不把新闻分数直接转换为涨跌概率。

事件研究现支持 T+1/3/5/10/20、`[-1,+N]` 事件窗口、资产收益、对齐基准后的异常收益/CAR、均值、中位数、标准差和 95% 置信区间。Event Reaction Graph 会保存日线反应；5m/15m/1h 没有 Point-in-Time 盘中历史时明确返回不可用。

Similar Event Retrieval 使用确定性的结构相似度：Event Type、Sentiment、Impact、Sector、Market Regime 和 Volatility。LLM 不负责判断相似度，也不得改写模型概率。

结论：当前无法判断新闻是否具有增量 Alpha。需要至少 30 个严格结算事件后才开始审计，达到约 100 个且通过显著性、消融和 Walk-Forward 后才可讨论弱证据。
