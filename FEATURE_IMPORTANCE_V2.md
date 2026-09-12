# Feature Importance V2

The V2 store publishes 57 timestamped features with `name`, `value`, `timestamp`, `source`, `lookback` and `version`.

| Group | Count | Examples | Current evidence |
|---|---:|---|---|
| Price | 15 | returns 1/3/5/10/20, log return, gap, ranges, volatility, price position | Experimental |
| Technical | 22 | RSI/MACD slopes, EMA distances, BOLL width, ADX, CCI, Stochastic, Williams %R, MFI | Experimental |
| Volume | 12 | ratio, z-score, relative volume, OBV change, money flow, price-volume correlation, VWAP deviation | Experimental |
| Structure | 3 | causal BOS, FVG, Fibonacci distance | Experimental |
| Regime | 5 | trend, high-volatility and risk-on proxies | Experimental |

Representative same-window Logistic ablation:

- 600519: Technical-only Brier 0.6517; Full observed 0.6539. Extra groups did not improve calibration, though Full reduced loss after costs.
- NVDA: Technical-only Brier 0.7159; Full observed 0.7053. Full improved Brier and net return, but directional accuracy remained only 29.86%.
- BTC: Technical-only accuracy 38.14% and Brier 0.6658; Full accuracy 42.33% and Brier 0.6606, but Full IC was -0.0491 and generated no actionable trades.

Conclusion: technical features contain some information in isolated windows, and volume/regime occasionally improve calibration, but incremental value is not stable across markets. No group is VALIDATED. News, events and fundamentals remain outside probability until a point-in-time historical feature matrix exists.
