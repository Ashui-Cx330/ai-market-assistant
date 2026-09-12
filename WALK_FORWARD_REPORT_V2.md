# Walk Forward Report V2

Validation uses expanding chronological folds. Each fold contains:

1. Model-fit history.
2. A later calibration tail.
3. A purged/embargoed out-of-sample test window.

The label end time must precede the next prediction window. Random train/test split is prohibited. Probability calibration uses only the calibration tail. Model ranking uses out-of-sample metrics, and no one-off benchmark can directly become Production.

Leakage checks exercised by tests:

- Mutating the final 40 candles does not change any feature in the first 300 rows.
- Future return and target time never enter model inputs.
- News published after the information cutoff is excluded from snapshots.
- Multi-bar strategy returns use non-overlapping capital windows.

Limitations: the current provider history yields approximately 197–409 OOS classifications per asset, but only 20 non-overlapping NVDA T+20 strategy observations. More rolling windows and live shadow outcomes are required.
