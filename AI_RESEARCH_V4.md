# AI行情助手 V4 量化研究审计

## 研究边界

V4 把价格模型与当前外部市场快照明确分开。只有具备逐时点历史的数据进入训练；当前新闻、宏观、财务与链上快照用于实时环境和风险解释，不会被伪装成历史特征。最终预测不缓存，每次请求重新取得最新原始数据；原始接口仅使用短 TTL 缓存。

## 已修复的验证问题

- 每个样本保存 feature time 与 target time；训练标签必须在下一验证区间开始前结束。
- Train、Calibration、Validation、Test 四段严格按时间排序，并按预测 horizon 增加 embargo。
- 概率校准只使用 Calibration；模型权重只来自 Validation；最终 Test 不参与选模。
- Walk-forward 每折执行相同的 purge；AI 回测在 T 收盘产生信号、T+1 开盘成交。
- 模型权重可按 BULL、BEAR、SIDEWAYS、HIGH_VOL 的验证样本动态选择；样本不足退回全局验证权重。

## V4 真实输出

- MarketSnapshot：风险偏好、趋势、波动、流动性、资金、宏观资产、BTC 与事件状态。
- CrossAssetEngine：从真实历史收盘价按时间配对计算滚动相关，缺少重叠样本时返回 DATA_INSUFFICIENT。
- NewsEventEngine：保存 publication/collection 时间、规则化事件类型、确定性去重与可计算时的 priced-in 分数；不由 LLM 编造事实。
- Feature Store：SQLite 使用 feature_timestamp、asset、feature_name、value、source、quality、collected_at 保存观测值。
- DataQualityScore：综合新鲜度、完整性、特征时间对齐、外部覆盖、来源数与冲突。
- ReturnDistribution 与 PathRisk：历史模型估计 expected return/volatility，并统计 MAE、MFE、止损和多档止盈触达率。
- 因子消融：在同一 purged holdout 上比较 Technical、Technical+Flow、Technical+Flow+Sentiment；报告 Accuracy/F1/AUC/LogLoss/Brier/IC/Return/Sharpe/Drawdown/Profit Factor。
- 预测生命周期：ACTIVE、到期时间、刷新触发器、RESOLVED、实际收益、MAE/MFE、SL/TP 命中。
- PortfolioRiskEngine：有两个以上真实持仓和足够重叠收益时计算相关、波动、VaR、CVaR、回撤和集中度。

## 仍然不足，绝不标记 PASS

- 新闻：没有覆盖足够长区间的历史新闻归档，扩展模型验证为 DATA_INSUFFICIENT。
- 宏观：已取得真实历史行情用于跨资产分析，但尚未形成完整的逐资产、逐预测时点扩展训练集。
- 财报：A 股公开财务历史保存 period_end 与 announcement_date；分析师一致预期及 surprise 历史不足，尚未进入模型。
- 链上：当前 Blockchair 快照真实，但缺少交易所净流、巨鲸、稳定币、MVRV 等完整历史时间序列。
- Liquidation、ETF flow、社交情绪、Put/Call 和 Options Skew 没有稳定公开源时保持 NO_DATA。
- 在线模型淘汰需要足够的已到期真实预测。在达到样本门槛前不会自动替换模型。
- 深度模型不会因“更高级”而默认启用；当前样本规模不支持对 LSTM/GRU/Transformer/TFT 做可信比较。

因此 V4 当前真实能力评级只能是 **B/C 边界**：核心价格/量价模型具备更严格的时间验证和研究能力，但只有在实际样本外表现持续超过基准时才可升为 B；多因子历史不足，不能评为 A，也不应直接用于自动实盘交易。
