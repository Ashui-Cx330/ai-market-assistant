# Prediction Track Record（V1.9.1 要求 / v1.11.0 实现）

数据源：本机 append-only `prediction_history`，统计时间 2026-09-12。失败预测没有删除或改写。

## 总体

| Samples | Accuracy | Precision macro | Recall macro | F1 macro | Brier | LogLoss | Baseline | Edge |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 58 | 20.69% | 15.21% | 18.86% | 16.21% | 1.1004 | 6.1758 | 53.45% | -32.76pp |

状态：**NO_EDGE / Experimental**。样本量达到最低展示门槛不等于模型有效；当前明显落后于多数类基线。

## 按周期

| 周期 | 样本 | Accuracy | Baseline | Edge | Brier | LogLoss | 状态 |
|---|---:|---:|---:|---:|---:|---:|---|
| 1H | 26 | 19.23% | 69.23% | -50.00pp | 0.7881 | 1.2881 | INSUFFICIENT / NO EDGE |
| 4H | 25 | 16.00% | 40.00% | -24.00pp | 1.5845 | 12.7561 | INSUFFICIENT / NO EDGE |
| 1D / 24H | 5 | 40.00% | 100.00% | -60.00pp | 0.5323 | 0.8293 | INSUFFICIENT |
| T+5 | 1 | 100.00% | 100.00% | 0.00pp | 0.5018 | 0.8045 | INSUFFICIENT |
| T+20 | 1 | 0.00% | 100.00% | -100.00pp | 0.5546 | 0.8486 | INSUFFICIENT |

周期样本会重叠计数，因为一个预测时点可同时保存多个目标周期；总体为数据库中的已结算预测行数。

## 按市场 / 资产

- Crypto：55 个已结算样本，Accuracy 20.00%，Baseline 50.91%，Edge -30.91pp，NO_EDGE。
- 股票：3 个已结算样本，全部来自 NVDA，样本严重不足。
- A 股、AAPL、TSLA、ETH、SOL：已有预测记录但尚无足够到期结果，不能计算可信准确率。
- 按事件类型：旧预测没有持久化事件标签；系统不会事后补写或猜测，状态为 `NOT_AVAILABLE`。

## 展示政策

- 概率可以用于研究界面，但显示 `Experimental`、样本量、基线、数据截止和风险声明。
- 当前不得用“高概率机会”“Validated”“强烈买入/卖出”等字样描述这些结果。
- 等新增预测自然到期后由解析器追加真实结果，再重新评估；不允许回填、删除错误样本或调历史标签。

