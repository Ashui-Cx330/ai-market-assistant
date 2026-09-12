# Factor Research V3

## 因子体系

当前使用 57 个真实 OHLCV 派生特征，分为价格、技术、成交量、结构和状态五组，再加同 session 的 5/20 周期相对收益。标准化为同一时点横截面 z-score，并裁剪到 ±5。缺少可靠 Point-in-Time 数据的 PE/PB/ROE、盈利增长、VIX、DXY、US10Y、Funding、OI、清算、Long/Short Ratio 和 BTC Dominance 均不模拟。

10 项研究的 LightGBM gain 平均靠前特征为 ATR 0.0614、历史波动率 0.0531、ADX 0.0490、20期相对收益 0.0384、EMA200 偏离 0.0371、布林宽度 0.0365。代码中的 `sentiment_score` 是价格/波动派生的市场状态代理，不是新闻情绪。

最低平均 gain 为 Williams %R 0、causal BOS 0.0006、log return 0.0011、FVG imbalance 0.0017。它们在当前树模型中贡献很低，但 gain 为零不等于因子在所有模型和市场中“完全没用”。

## 消融结论

单组 Rank IC 偶尔较高，例如 A股 T+20 的结构 0.19、成交量 0.18，A股 T+5 的价格 0.14；但全特征组合没有稳定继承这些结果，最差窗口仍显著为负。美股 T+20 全因子 Rank IC 中位数 0.06，是本轮相对较好的研究线索；Crypto 多数周期为负。

当前没有任何因子通过跨市场、跨周期、成本后稳定性与独立增量门禁。SHAP 仅解释单次 LightGBM 输出贡献，不是概率，也不是因果证明。
