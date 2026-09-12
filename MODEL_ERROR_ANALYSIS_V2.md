# Model Error Analysis V2

The immutable live record has 58 resolved predictions:

- Accuracy 20.69%; Macro F1 16.21%.
- Brier 1.1004; LogLoss 6.1758; ECE 0.4337.
- IC -0.4850; Rank IC -0.3407; Sharpe -3.2958.
- Average realised R -0.7152; profit factor 0.4064.

Error attribution is now persisted without inventing causes:

- `VOLATILITY_UNDERESTIMATED`: predicted SIDE but realised outside the dynamic band.
- `STOP_HIT_BEFORE_TARGET`: risk boundary was crossed before target settlement.
- `DIRECTIONAL_MISS_UNATTRIBUTED`: wrong direction with no auditable causal evidence.

The system will not label an error “unexpected news” unless a post-cutoff event can be linked by timestamp. Existing failures remain immutable.
