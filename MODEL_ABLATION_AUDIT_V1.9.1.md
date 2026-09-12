# 模型消融审计（V1.9.1 要求 / v1.11.0 实现）

审计结论：**无法证明新闻提高预测效果。新闻暂不进入最终概率模型。**

## 可用数据边界

- 本地规范化新闻：281 条。
- 已具备发布后价格结果的历史事件：11 条，低于每个市场/事件/周期最低样本门槛。
- 已结算预测：58 条，其中 BTC 55 条、NVDA 3 条；A 股、AAPL、TSLA、ETH、SOL 没有足够已到期记录。
- 因此无法对 A 股 / 美股 / Crypto 分别运行具有统计意义的 `Full / -News / -Technical / -Regime` 比较。

## 当前可复核结果

| 方案 | 样本 | Accuracy | Baseline | Edge | Brier | LogLoss | 结论 |
|---|---:|---:|---:|---:|---:|---:|---|
| 当前价格/技术 Ensemble（全部已结算） | 58 | 20.69% | 53.45% | -32.76pp | 1.1004 | 6.1758 | NO_EDGE |
| BTC 当前模型 | 55 | 20.00% | 50.91% | -30.91pp | 1.1298 | 6.4639 | NO_EDGE |
| 纯新闻 | 0 个合格对齐样本集 | — | — | — | — | — | DATA_INSUFFICIENT |
| 技术 + 新闻 | 0 个合格对齐样本集 | — | — | — | — | — | DATA_INSUFFICIENT |
| Full / -News / -Technical / -Regime | 0 个跨市场合格实验 | — | — | — | — | — | NOT_RUN |

多分类 Brier 使用三类概率向量平方误差总和，理论范围 0–2。

## 为什么没有伪造完整表格

把当前 11 个事件重复切片、随机打散或事后按结果调权，会制造未来泄露和选择偏差。系统因此采取保守策略：新闻只作为事件时间线、风险解释和重大事件重算触发器；P(UP/SIDEWAYS/DOWN) 仍来自经过时间切分与校准的价格模型。

## 进入 Useful / Validated 的门槛

- 每个市场、周期至少 30 个独立已结算样本用于初步展示，生产判断建议至少 200–500 个。
- 采用 publication cutoff、首个可交易价格、Walk-Forward 和 horizon embargo。
- Full 相对 `-News` 的 Brier、LogLoss 和 Directional Accuracy 均改善，并报告 Bootstrap 95% CI。
- 相对多数类、随机和纯技术基线有稳定正 edge，且不是仅由单一资产贡献。
- 通过漂移、成本、最大回撤和校准审计后才可标为 Validated。

当前等级：**Experimental**。没有模型符合生产级 `Validated`。

