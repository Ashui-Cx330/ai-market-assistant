# Event Study Report V2

The event engine now aligns each publication to the first strictly later trading bar and calculates T+1/T+3/T+5/T+10/T+20 returns. When a benchmark is available it also stores abnormal return and CAR:

`Abnormal Return = Asset Return - Aligned Benchmark Return`

Benchmarks are CSI 300 for A shares, SPY for US equities and BTC for non-BTC crypto. BTC is left without a benchmark rather than using an unjustified substitute.

The local audit database currently contains 281 normalized news records and only 11 historical event outcomes. Required evidence is N≥30. Therefore:

- Similar-event win rates: **INSUFFICIENT EVIDENCE**
- CAR significance: **INSUFFICIENT EVIDENCE**
- News/Event probability contribution: **disabled**
- Event information remains available for explanation, risk warning and future dataset accumulation.

No event label, direction or impact score is presented as a calibrated market probability.
