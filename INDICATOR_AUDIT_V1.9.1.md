# 技术指标公式审计

| 指标 | 实现 | 输入/周期 | 因果性 | 结论 |
| --- | --- | --- | --- | --- |
| SMA | `rolling(n).mean()` | close；5/10/20/60 | 仅当前及历史 | PASS |
| EMA | `ewm(span=n, adjust=False)` | close；12/26 | 仅历史递推 | PASS |
| MACD | EMA12−EMA26，Signal=EMA9，Hist=2×差值 | close | 仅历史递推 | PASS |
| RSI | Wilder alpha=1/14 的涨跌平滑 | close；14 | 仅历史递推 | PASS |
| BOLL | MA20 ± 2×rolling std | close；20 | 仅滚动历史 | PASS |
| ATR | max(H−L, abs(H−prevC), abs(L−prevC)) rolling 14 | OHLC | prevC 使用 shift(1) | PASS |
| ADX | ±DM、Wilder ATR、DX 的 Wilder 平滑 | OHLC；14 | 仅历史递推 | PASS |
| Volume Ratio | volume / rolling mean(volume,20) | volume；20 | 含当前量，界面按当前时点解释 | PASS |
| Momentum/ROC | 历史差值/收益率 | close | 仅过去窗口 | PASS |
| BOS/CHoCH/FVG | 已完成结构引擎和时点测试 | OHLC | 信号只在结构可确认后出现 | PASS（研究特征） |

指标是特征，不是“RSI<30 必涨”的预测公式。回测信号在 T 收盘形成、最早在 T+1 开盘执行，并计手续费/滑点。周线当前柱时间使用最后一根真实日线时间，不把未来周末时间写入当前样本。

