# AI 预测引擎 V2

V2 使用真实 OHLCV 行情生成独立的 1H、4H 和 1D 三分类目标，输出 UP / FLAT / DOWN。目标按 UTC 时间戳对齐；A 股的日内目标跳过午休、夜间和周末，1D 表示下一个真实交易日的对应时点。节假日不靠推测，而是使用历史 K 线中实际存在的下一个时间点。

当前集成模型为 Random Forest、XGBoost 和 LightGBM。每个 horizon 独立训练，按时间顺序分为训练、校准和测试集，再进行 walk-forward 验证。权重由样本外 Accuracy、F1、LogLoss 和 Brier Score 综合确定，不是手写常数。概率使用 Platt 校准，界面明确标识为“校准后模型概率”，不代表现实世界保证。

当前真正可用的因子是 K 线、技术指标、量价资金压力代理和基于真实价格/波动率的市场情绪。新闻、宏观、A 股财务和 Crypto 链上数据尚未配置可验证的数据源，因此必须返回 `NO_DATA` 或 `NOT_APPLICABLE`，不会生成替代数据。LSTM 和 Transformer 在当前单资产样本量下不具备充分依据，故未启用。

模型保存在用户数据目录的 `models/<symbol>/<interval>/<horizon>/`，行情缓存保存在 `cache/market-cache.sqlite3`。新模型原子替换并保留上一版本，可由 ModelManager 回滚。同一训练时间窗内重复点击会直接加载已保存模型，1m/5m 每小时更新，其他日内周期每 4 小时更新，日线每日更新。

顶层影响因子使用经验证表现加权的树模型 Feature Importance，不是写死文案。当前环境未安装 SHAP，API 会如实返回 `shap_status: NOT_AVAILABLE`。
