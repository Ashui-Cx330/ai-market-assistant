# Production Model Decision V2

## Decision

**Production model: NONE. Final status: NO EDGE.**

No candidate simultaneously beats the majority baseline, shows positive stable IC, acceptable calibration, cost-adjusted performance and multiple-window stability. The historical live track record is materially worse than baseline.

## Candidate disposition

- Logistic Regression: retain as transparent baseline and research candidate.
- LightGBM, XGBoost, CatBoost: retain in Model Lab; none is Production.
- Random Forest: retain for comparison; no consistent advantage.
- Validation-weighted calibrated ensemble: Experimental; aggregation does not rescue weak inputs.
- LSTM, GRU, TFT, Transformer: not trained. Current per-asset samples and multivariate history are insufficient for a fair same-window contest.
- News-only and News+Price dual stream: not trained because point-in-time news vectors are insufficient.

## Promotion gate

A model can become Production Candidate only after at least three purged walk-forward folds, N≥100 OOS classifications, ≥3 percentage-point directional improvement over majority, IC>0.02, better Brier, stability checks and no leakage. Production additionally requires forward shadow performance and downgrade monitoring. One successful asset/window is insufficient.

## Direct answers

1. Best model: none globally; lowest-Brier winners vary by asset.
2. Why: performance is inconsistent and IC is mostly negative.
3. News value: unknown; insufficient point-in-time data.
4. Technical value: sometimes present, not stable.
5. Regime value: occasionally improves a window, not validated.
6. Best market: none. Crypto daily accuracy sometimes exceeds majority but IC remains negative.
7. A shares: NO EDGE.
8. US equities: NO EDGE.
9. Crypto: NO EDGE.
10. T+1/24H: all nine assets NO EDGE.
11. T+5: NVDA 52.63% vs 50.88%; negative IC, NO EDGE.
12. T+20: NVDA 57.22% equals baseline; only 20 non-overlap trades, NO EDGE.
13. Crypto: BTC 1H 40.00% vs 50.00%; 4H 30.32% vs 32.76%; 24H 33.99% vs 36.92%; all NO EDGE. 7D also NO EDGE.
14. IC: asset/window-specific; representative range -0.0811 to 0.2291. Live history -0.4850.
15. ICIR: reported when multiple fold ICs exist; not treated as proof with few folds.
16. Brier: nine-asset best range 0.6575–0.6898; live history 1.1004.
17. Sharpe: unstable; live history -3.2958.
18. Maximum drawdown: horizon checks range -1.80% to -32.25%; depends on non-overlap sample.
19. Buy & Hold: models do not consistently outperform; NVDA T+20 strategy 53.62% vs buy-and-hold 70.99%.
20. Future leakage: automated causality checks pass; no guarantee against unknown provider revisions.
21. Eliminate from production: all current candidates; deep/news variants remain unqualified.
22. Production: none.
23. Experimental: every current predictive model, ensemble, feature ablation and event similarity statistic.
