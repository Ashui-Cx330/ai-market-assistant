# AI行情助手 V5 最终交易策略审计

审计日期：2026-09-07；引擎版本：StrategyEngine 5.0。

| 验收项 | 状态 | 说明 |
|---|---|---|
| 30类策略 | PARTIAL | 30 个统一 ID 均可调用；27 个使用 OHLCV 真值，Gann/Order Flow/Options 受证据或数据限制 |
| Fib | PASS | 已确认因果 Swing；0/.236/.382/.5/.618/.786/1/1.272/1.618/2.0 |
| FVG | PASS | 三根 K 线识别，记录区域、大小、年龄、回补与时间 |
| BOS / CHoCH | PASS | 突破已确认 Swing，保存 swing_id、价格、时间、成交量和确认 |
| Fib+FVG+BOS | PASS（实现）/ FAIL（收益） | 组合真实运行，但样本外为负 EV |
| Walk-forward | PASS（机制）/ FAIL（表现） | expanding train → lock → embargo → next test；真实结果为负 |
| 未来数据泄漏 | PASS（V5路径） | formation/available 分离；T 信号、T+1 开盘执行 |
| 实时数据 | PASS | 公开交易所/证券数据，失败不替代 |
| 历史数据 | PARTIAL | K线可用；历史新闻、链上、期权和逐笔流不足 |
| 概率校准 | PASS | Platt + Brier + Log Loss + ECE + reliability |
| 风险管理 | PASS | 结构/FVG/ATR/经验 MFE-MAE、TP1/2/3、成本后 EV |
| Mock / Random Signal / Fixed Prediction | 0 / 0 / 0 | 生产策略没有这些路径 |

## 30类策略

PASS：Trend、Breakout、Pullback、Reversal、Range、Moving Average、Bollinger、RSI Breakout、RSI Reversal、MACD、Fibonacci、Stochastic、PSAR、Momentum、MFI、Donchian、ATR、ICT/SMC、FVG、BOS、CHoCH、Fib+FVG+BOS。

PARTIAL：Double Top/Bottom、Head & Shoulders、Triangle、Wedge、Flag（已有因果识别和突破确认，尚缺足量逐资产增量证据）；Gann（`INSUFFICIENT_EVIDENCE`）；Order Flow（默认 `ORDER_FLOW_DATA_UNAVAILABLE`）；Options（`OPTIONS_DATA_UNAVAILABLE`）。Wedge 和 ATR 不允许未经确认单独发出交易指令。

## 真实 BTC 1H 策略实验

数据源：OKX；520 根；2026-08-16 12:00 UTC 至 2026-09-07 03:00 UTC。手续费和滑点已扣除，T 收盘信号、T+1 开盘执行，持仓不重叠。

| 策略 | Trades | Win Rate | EV/Trade | Sharpe | MDD |
|---|---:|---:|---:|---:|---:|
| Trend baseline | 42 | 33.33% | -0.1343% | -0.6074 | 16.18% |
| Fibonacci | 49 | 44.90% | -0.1477% | -0.8820 | 15.15% |
| FVG | 12 | 16.67% | -0.3512% | -2.1058 | 4.15% |
| BOS | 0 | 0% | 0 | 0 | 0 |
| Fib+FVG+BOS | 41 | 36.59% | -0.1091% | -0.4991 | 15.18% |

组合相对趋势基线：胜率 +3.26 pct、EV +0.0252 pct、Sharpe +0.1083、MDD -1.00 pct。绝对 EV/Sharpe 仍为负：**NOT PROFITABLE / NOT READY FOR LIVE TRADING**。

Walk-forward：4 folds、30 笔、每折 8 bar embargo；各折 EV 为 -0.2273%、-0.4045%、-0.4533%、-0.0877%。

## ML ICT 特征消融（BTC 1H → 4H）

固定 Logistic Regression；训练/校准/最终测试按时间分割，4 bar embargo；最终测试 76 条。

| 指标 | 加入前 | 加入后 | 增量 |
|---|---:|---:|---:|
| Accuracy | 0.2368 | 0.2500 | +0.0132 |
| F1 Macro | 0.1277 | 0.1481 | +0.0204 |
| AUC OVR | 0.4797 | 0.5107 | +0.0310 |
| Brier | 0.6838 | 0.6815 | -0.0023 |
| ECE | 0.1688 | 0.1546 | -0.0142 |
| EV | -0.2404% | -0.2197% | +0.0207 pct |
| Sharpe | -3.4582 | -3.1737 | +0.2845 |
| MDD | 16.83% | 15.51% | -1.32 pct |

结论：有轻微相对增量，但绝对表现很差，状态为 `INCREMENTAL_VALUE_NOT_TRADEABLE`。

## 缺失数据与评级

- `ORDER_FLOW_DATA_UNAVAILABLE`：没有逐笔 aggressor side/盘口字段。
- `OPTIONS_DATA_UNAVAILABLE`：没有完整期权链。
- `HISTORICAL_NEWS_ALIGNMENT_FAILED`：历史新闻不足以构建无偏训练集。
- BTC Dominance、稳定币流、交易所净流、鲸鱼标签和 A股历史北向覆盖不足，均不伪造。

工程与审计能力：B-；预测/交易能力：D；上线真实资金：FAIL。当前适合可追溯研究、样本外回放和模拟交易，不支持稳定盈利声明。
