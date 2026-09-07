# AI 交易决策引擎 V3

V3 在 V2 的三模型概率层之后增加市场状态、资金、结构和风险决策层。它不会把方向概率直接翻译为买卖：负期望值、数据不足、模型分歧或止损不合理都会得到 `NO_TRADE` 或 `WAIT`。

## 数据与证据链

- 价格、K 线、成交量和成交额来自实时公开行情接口。A 股支持东方财富，并以新浪日内 K 线和腾讯日线作为独立备用源；Crypto 使用 OKX，并以 Coinbase 作为备用源。
- Crypto 的 Open Interest、OI 变化和 Funding Rate 来自 OKX 公共接口。Liquidation、ETF Flow、交易所链上流入流出没有可靠来源时返回 `NO_DATA`。
- “资金净流向”明确标识为真实 OHLCV 的量价代理，不冒充交易所报告的净流入。系统同时计算方向、动量、加速度、持续性以及价格/资金/OI 背离。
- 当前新闻标题来自 Google News RSS，宏观跨资产价格来自 Yahoo Finance 公共图表接口，重大事件来自 Fair Economy 周历，A 股估值来自腾讯证券公开行情字段，BTC/ETH 链上概况来自 Blockchair。每项都携带来源与状态；请求失败或资产不适用时保持 `NO_DATA` / `NOT_APPLICABLE`。
- 这些外部源目前只用于“当前市场上下文”和风险调整，尚无足够的时间对齐历史快照进入模型 Walk-forward，因此不会伪装成已经验证过的训练因子。

## 数学层

`MarketRegimeEngine` 综合趋势、历史波动率分位、真实成交量和资金代理，动态输出趋势状态、Risk-On/Risk-Off、流动性及状态切换预警。

`SupportResistanceEngine` 从真实 Swing、成交额加权 Volume Profile、VWAP、Anchored VWAP、MA、Bollinger、Fibonacci、缺口和前高前低聚合价格区间，并按触碰、停留、成交密集与多来源重合计算 0–100 强度。

`RiskEngine` 在较早 70% 时间序列上对 ATR multiplier 做网格回测，以平均 R 和回撤惩罚选参；较后 30% 作为独立时间留出验证。止损再与 Swing 和支撑/压力结构比较，保留所有候选、ATR、Buffer、样本数和选择依据。

仓位使用账户资金 × 最大风险百分比 ÷ 每单位总风险，并计入双边手续费、滑点、杠杆上限、合约乘数和最小交易单位。低流动性 Crypto 会降低有效风险额度并扩大滑点。

止盈输出 TP1/TP2/TP3，候选来自结构压力/支撑、ATR 和历史波动区间。期望值使用校准后的方向概率、目标收益、止损风险和交易成本计算；期望值不为正时禁止交易。

## 验证

- 模型：严格时间顺序训练/校准/测试和 Walk-forward，不做随机拆分。
- 风险：历史选参和后 30% 时间留出分别执行，OHLC 同一根 K 线同时触发止损和止盈时保守按止损优先。
- 在线预测：保存预测时间、数据时间、模型/特征版本、三类概率、状态、止损与 TP1。到达目标时间后只用真实后续 K 线解析结果。
- 统计：按 1H/4H/1D 和市场状态输出 Accuracy、Precision、Recall、F1、Brier、LogLoss、Calibration Gap、Stop Hit、TP Hit、Average R 与 Profit Factor。样本未到期时显示 `NO_DATA`，不会预填成绩。

## 2026-09-04 验收矩阵

BTC、ETH、贵州茅台（600519）、宁德时代（300750）和五粮液（000858）分别在 15m、1H、4H、1D 运行了真实数据验收，共 20 个组合。每个组合均完成模型预测、资金、市场状态、支撑压力、动态止损、三档止盈、仓位、R:R、Expected Value 和机会评分，20/20 返回 PASS。

这只是软件与数据链路验收，不代表未来预测准确，也不构成投资建议。
