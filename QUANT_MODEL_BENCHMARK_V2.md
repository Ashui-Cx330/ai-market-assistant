# Quant Model Benchmark V2

Audit date: 2026-09-12. Engine: Quant Intelligence Engine V2. Status: **NO EDGE / EXPERIMENTAL**.

## Method

- Real public OHLCV, 57 causal features, dynamic volatility labels.
- Expanding three-fold walk-forward; horizon purge/embargo; calibration tail is separate from model fit.
- Logistic Regression, Random Forest, XGBoost, LightGBM and CatBoost use identical samples. Ensemble weights are performance-derived, not manually assigned.
- Metrics include direction accuracy, Brier, LogLoss, IC, Rank IC, ICIR, Sharpe, Sortino, maximum drawdown, Calmar, turnover, costs and profit factor.
- Multi-bar portfolio returns use non-overlapping holding windows. The earlier overlapping-return implementation was rejected during this audit.
- Qlib was studied as a workflow reference, not embedded. Qlib separates data, models, records and backtests and reports signal IC/ICIR plus portfolio metrics; its published benchmarks also show that complex models do not universally win: https://github.com/microsoft/qlib and https://github.com/microsoft/qlib/tree/main/examples/benchmarks

## Nine-asset T+1 / 24H benchmark

| Market | Asset | OOS N | Lowest-Brier model | Accuracy | Majority | IC | Rank IC | Brier | Net return after costs | Decision |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---|
| CN | 600519 | 197 | CatBoost | 38.07% | 35.53% | -0.0040 | 0.0193 | 0.6575 | -4.32% | NO EDGE |
| CN | 000001 | 197 | XGBoost | 35.03% | 33.50% | 0.0444 | 0.0700 | 0.6713 | -7.95% | NO EDGE |
| CN | 300750 | 198 | Logistic | 30.30% | 37.37% | -0.0811 | -0.0267 | 0.6808 | -3.15% | NO EDGE |
| US | NVDA | 401 | Logistic | 35.91% | 36.41% | -0.0170 | -0.0402 | 0.6759 | -8.29% | NO EDGE |
| US | AAPL | 402 | Logistic | 42.54% | 42.54% | -0.0321 | 0.0024 | 0.6734 | 0.00% | NO EDGE |
| US | TSLA | 408 | LightGBM | 33.09% | 33.82% | 0.0016 | -0.0002 | 0.6786 | 7.07% | NO EDGE |
| Crypto | BTC | 409 | LightGBM | 33.99% | 36.92% | -0.0422 | -0.0123 | 0.6898 | 0.00% | NO EDGE |
| Crypto | ETH | 407 | XGBoost | 35.87% | 40.05% | -0.0249 | -0.0075 | 0.6678 | 1.61% | NO EDGE |
| Crypto | SOL | 409 | CatBoost | 40.83% | 28.85% | -0.0524 | -0.0243 | 0.6635 | 0.00% | NO EDGE |

“Best” only means lowest Brier among candidates for that asset. It does not mean validated or profitable. No single model wins consistently.

## Representative horizon checks

| Asset/horizon | Best | OOS N | Non-overlap trades | Accuracy / baseline | IC / ICIR | Sharpe | Max DD | Net | Result |
|---|---|---:|---:|---|---|---:|---:|---:|---|
| BTC 1H | XGBoost | 410 | 410 | 40.00% / 50.00% | 0.0602 / 0.6382 | -0.5233 | -1.80% | -0.94% | NO EDGE |
| BTC 4H | Logistic | 409 | 103 | 30.32% / 32.76% | 0.0943 / 2.0803 | 0.5961 | -2.18% | 2.23% | NO EDGE |
| BTC 7D | XGBoost | 407 | 59 | 39.80% / 37.84% | -0.0417 / 0.5628 | -0.5016 | -32.25% | -26.81% | NO EDGE |
| NVDA T+5 | Logistic | 399 | 80 | 52.63% / 50.88% | -0.0256 / 0.0628 | 0.9767 | -29.68% | 64.36% | NO EDGE |
| NVDA T+20 | Logistic | 395 | 20 | 57.22% / 57.22% | 0.2291 / 0.2778 | 0.9847 | -16.04% | 53.62% | NO EDGE |

T+20 has only 20 non-overlapping trades and merely matches the majority accuracy, so its attractive return cannot justify promotion.

## Answer

There is no globally best validated model. Logistic is the most defensible baseline because it is competitive on several assets and easiest to audit; CatBoost/XGBoost/LightGBM remain candidates. No model enters Production.
