# Model Ablation V2

Method: same chronological holdout, same Logistic model and dynamic target; only feature groups change.

| Asset | Technical only | +Volume | +Volume+Price | Full observed | Result |
|---|---|---|---|---|---|
| 600519 | Acc 41.35%, Brier .6517 | 41.35%, .6527 | 41.35%, .6548 | 41.35%, .6539 | No stable increment |
| NVDA | 27.96%, .7159 | 27.96%, .7116 | 28.91%, .7065 | 29.86%, .7053 | Small calibration improvement; still weak |
| BTC | 38.14%, .6658 | 40.00%, .6607 | 40.47%, .6611 | 42.33%, .6606 | Accuracy improves; IC remains negative |

News-only, Technical+News and News+Event variants are **not run** because point-in-time historical news vectors are insufficient. Reporting a result would introduce survivorship/time leakage. News incremental value remains unknown, not positive.

Regime is included only in Full observed. Its incremental result is inconsistent and therefore Experimental.
