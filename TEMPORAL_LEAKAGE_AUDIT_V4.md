# Temporal Leakage Audit V4

生成自 `C:\Users\汪文斌\AppData\Roaming\AI行情助手\database\trading_ai.db`；生成时间 `2026-09-13T11:19:01.253527+00:00`。不使用 Mock，不删除失败样本。

新闻 `540` 条；缺失 publishedAt `0`；publishedAt 晚于 collectedAt `12`。时间未知的新闻不得进入特征。

当前新闻生产概率权重为 0；历史研究采用顺序 Walk-Forward、禁止 shuffle。已知生产泄漏：**未发现**；数据时间异常需隔离。
