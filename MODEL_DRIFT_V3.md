# Model Drift V3

当前状态：`INSUFFICIENT_TIME_COVERAGE`

本机共有 1,678 条不可变预测记录，其中 1,402 条已结算。整体 Accuracy 0.3238、Macro F1 0.2905、Brier 0.8952、LogLoss 5.5753、ECE 0.3255、IC -0.1755、Rank IC -0.1856、Average R -0.3338、Profit Factor 0.8326。

虽然记录数量较多，预测时间只覆盖约 1.84 天。旧实现可能把 30/90/180 日窗口误认为都有足够数据；V3 已修正为优先使用 `prediction_time`，并要求至少 170 天实际时间覆盖。当前不能得出“没有漂移”或“发生漂移”的统计结论。

漂移只会触发降级和重新研究候选：Backtest → Validation → Shadow → Manual Approval。自动重训永久关闭，连续失败版本不会自动反复晋级。
