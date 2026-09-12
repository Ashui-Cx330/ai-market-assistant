# Label Audit V3

## 三个独立目标

1. 回归：未来收益减去同一时点横截面平均收益。
2. 方向：未来收益超过训练窗口 ATR 动态阈值为 UP，低于负阈值为 DOWN，其余为 SIDE。
3. 风险：未来路径最大回撤是否低于训练窗口的 20% 分位阈值。

阈值仅使用对应训练窗口计算，验证集和测试集不能反向修改阈值。没有删除少数类样本；分类器使用 balanced class weight，并同时输出 Balanced Accuracy、Macro F1、MCC、Brier 和 LogLoss。

本轮训练阈值区间：A股约 1.04%–1.19%，美股约 1.65%–1.82%，Crypto 1H 约 0.23%–0.27%，Crypto 7D 约 2.29%–2.43%。首窗 1D SIDE 占比为 A股 61.93%、美股 54.66%、Crypto 1H 63.15%，类别不平衡明显。

结果显示最优分类器的 Balanced Accuracy 中位数大多为 0.3333、MCC 接近 0，说明高表面 Accuracy 主要来自主类，而不是可靠方向识别。此结论是 `NO EDGE` 的关键证据。
