# 模型真实性与统计有效性审计

## 当前生产模型

`PerformanceWeightedEnsemble` 使用 Logistic Regression、Random Forest、XGBoost、LightGBM；CatBoost 仅在依赖可用时启用。特征来自截至决策时点的量价、技术结构、波动率、资金/市场状态及可用外部数据。每个 horizon 使用 Purged Train/Calibration/Validation/Test、horizon embargo、Walk-forward、Platt 概率校准；选模只看 validation，最终 test 在权重确定后才打开。

代码计算 Accuracy、Precision、Recall、macro-F1、multi-class Brier、Log Loss、ECE/可靠性分箱，并和 majority/random/technical baseline 比较。`validation_scheme.leakage_check` 必须为 true。预测概率不是确定结果，也不是收益率。

## NVDA 既有结果的可复核边界

| 周期 | Accuracy | Majority baseline | Edge | 证据等级 | 结论 |
| --- | ---: | ---: | ---: | --- | --- |
| T+1 | 39.47% | 原材料未披露 | 不可计算 | D | No statistical edge，应停止把它展示为“有效预测” |
| T+5 | 50.26% | 48.15% | +2.11% | C | Weak historical evidence |
| T+20 | 62.23% | 54.79% | +7.44% | C | 点估计最好，但统计显著性未验证 |

原始逐样本预测、样本量和标签未随这组数字提供，因此 Precision、Recall、F1、Brier、Log Loss、Bootstrap 95% CI 和 Calibration Curve无法诚实复算，界面现在明确显示“不可复算”，没有补造数字。T+20 是当前三者中最有希望的历史点估计，但在补齐原始 OOS 样本和置信区间前不能称为稳定优势。

本机后续真实预测会写入 `prediction_history`，到期后按真实价格结算；样本不足时状态为 `INSUFFICIENT_DATA`。深度模型、新闻胜率和“80%准确率”等无证据宣传均未启用。

## 核心回答

- 模型“有没有用”：当前只能说研究价值存在；没有足够证据承诺稳定可交易 alpha。
- 应停用什么：T+1 的“有效方向预测”宣传；模型仍可保留为实验记录。
- 哪些只是看起来像 AI：AI Score 是确定性综合信号分，不是准确率；Copilot 解释不是独立预测模型；没有原始 OOS 记录的漂亮百分比没有统计意义。
- 数据泄露：特征阈值 shift(1)，标签只用于训练目标，时间序列不随机打乱，分割处 purge/embargo；自动测试覆盖边界。但这不等于未来永远不会出现实现缺陷，新增特征仍必须继续审计。

