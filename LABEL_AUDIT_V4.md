# Label Audit V4

生成自 `C:\Users\汪文斌\AppData\Roaming\AI行情助手\database\trading_ai.db`；生成时间 `2026-09-13T11:19:01.253527+00:00`。不使用 Mock，不删除失败样本。

固定阈值标签保留为 Benchmark；波动率调整阈值仅可从每个训练窗口估计。收益定义为 `P(t+h)/P(t)-1`，股票按实际后续交易 Bar、Crypto 按 1H/4H/24H/7D UTC Bar。

测试集不得调阈值。当前未产生足够的多资产新样本，标签比较状态：**INSUFFICIENT DATA**。
