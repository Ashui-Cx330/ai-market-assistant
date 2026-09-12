# Temporal Leakage Audit V3

状态：`PASSED`

- 每行特征时间严格早于标签时间。
- 目标索引由真实交易 K 线时间计算，股票日线按观测交易日，Crypto 按自然时序。
- 横截面标准化只使用同一 session 当时可观察的资产。
- 每个窗口按 Train → Validation → Test 排序。
- Train/Validation 会清除跨入后一区间的未完成标签。
- 禁止随机切分；测试集不用于阈值、参数、校准或模型权重选择。
- 新闻未进入 V3 生产概率，避免发布时间、抓取时间和修订时间混用。

10 项真实研究的 `invalid_feature_label_order`、`future_feature_rows` 和重复资产时间键均为 0。该通过结论只覆盖当前 V3 管道；外部供应商数据若未来发生追溯修订，仍需版本化快照才能完全审计。
