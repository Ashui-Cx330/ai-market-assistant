# Quant Research V3

生成时间：2026-09-12（Asia/Shanghai）  
结论：`NO EDGE`  
Production Model：`NONE`

## 研究问题

V3 不再把单资产三分类准确率当作可交易优势。它在相同的 Point-in-Time 数据上同时研究未来相对收益回归、ATR 动态方向分类和未来路径下行风险，并使用五个滚动窗口、独立验证集、横截面排序及含成本组合回测进行判定。

Legacy Logistic、Random Forest、LightGBM、XGBoost、CatBoost、LSTM、GRU、Transformer、TFT、News Model 和旧 Ensemble 均被冻结为 `Legacy Experimental Benchmark`。任何研究结果都不能自动晋级或自动重训。

## 实际执行

- A股：1D、T+5、T+20
- 美股：1D、T+5、T+20
- Crypto：1H、4H、24H、7D
- 每项均完成 5 个滚动窗口，共 10 项真实行情研究，全部返回 `NO_EDGE`。
- 数据质量与时间泄露审计通过；Production Model 始终为 `NONE`。

## 核心判断

当前主要瓶颈不是缺少更复杂模型，而是方向标签可分性差、分类器普遍塌缩到主类、横截面只有 5 个标的、部分结构数据缺失，以及样本外 Rank IC 在窗口间不稳定。美股 T+5 的 Lasso 组合出现正收益，但分类门禁失败、横截面太窄，不能视为已验证 Edge。

可复现实验入口：`python scripts/quant_v3_acceptance.py`。原始机器可读结果位于被 Git 忽略的 `work/quant-v3-acceptance.json`。
