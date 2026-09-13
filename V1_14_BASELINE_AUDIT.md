# AI行情助手 v1.14.0 基线审计

生成时间：`2026-09-13T11:19:01.253527+00:00`
数据库：`C:\Users\汪文斌\AppData\Roaming\AI行情助手\database\trading_ai.db`

> 本报告由 SQLite 实际记录生成，不采用前端展示常量。旧记录不删除、不重写。

## 真实结论

- Quant Status：**NO EDGE**
- Production Model：**NONE**
- Champion：**NONE**
- 新闻：540；严格结算事件：11（低于 30，Explanation Only）
- 漂移：INSUFFICIENT_TIME_COVERAGE

## 数据表

| Table | Rows |
|---|---:|
| ai_score_history | 63 |
| backtest_runs | 1 |
| feature_observations | 68680 |
| historical_events | 11 |
| market_candles | 4422 |
| market_intelligence_snapshots | 0 |
| news | 540 |
| news_events | 540 |
| news_impacts | 540 |
| news_prediction_signals | 0 |
| news_provider_health | 6 |
| news_sector_relations | 186 |
| news_sentiment | 540 |
| news_stock_relations | 348 |
| paper_accounts | 3 |
| paper_daily_equity | 6 |
| paper_orders | 1 |
| paper_positions | 1 |
| prediction_history | 1678 |
| prediction_settlement_audit | 434 |
| provider_health_events | 0 |
| quant_model_registry | 0 |
| quant_prediction_snapshots | 0 |
| quant_research_runs | 0 |
| research_cache | 0 |
| research_jobs | 0 |
| research_universe_members | 603 |
| research_universes | 3 |
| schema_migrations | 1 |
| symbol_master | 605 |
| trading_decisions | 0 |
| watchlist | 7 |

## Asset Coverage Matrix

| Market | Symbol | Candle Count | Prediction Count | Settled | Pending | Horizons |
|---|---|---:|---:|---:|---:|---|
| CRYPTO | BTC | 3000 | 1669 | 1598 | 71 | 1D:232/238, 1H:705/722, 4H:661/709 |
| CRYPTO | XSNDK | 1422 | 3 | 3 | 0 | 1D:1/1, 1H:1/1, 4H:1/1 |
| US | NVDA | 0 | 3 | 0 | 3 | 1D:0/1, T+20:0/1, T+5:0/1 |
| US | SNDK | 0 | 3 | 1 | 2 | 1D:1/1, T+20:0/1, T+5:0/1 |

## Universe 版本

[
  {
    "universe_version": "CRYPTO-2026-09-13-8f4529ce07234ee6",
    "market": "CRYPTO",
    "member_count": 100,
    "source": "OKX public spot tickers ranked by observed quote volume",
    "as_of": "2026-09-13",
    "survivorship_status": "CURRENT_CONSTITUENTS_ONLY; SURVIVORSHIP_BIAS_UNRESOLVED"
  },
  {
    "universe_version": "US-2026-09-13-0cbf0807fecd7bb5",
    "market": "US",
    "member_count": 500,
    "source": "persistent registry populated by Nasdaq screener",
    "as_of": "2026-09-13",
    "survivorship_status": "CURRENT_CONSTITUENTS_ONLY; SURVIVORSHIP_BIAS_UNRESOLVED"
  },
  {
    "universe_version": "CN-2026-09-13-d581b4a58f5a7fc6",
    "market": "CN",
    "member_count": 5,
    "source": "persistent registry populated by Eastmoney",
    "as_of": "2026-09-13",
    "survivorship_status": "CURRENT_CONSTITUENTS_ONLY; SURVIVORSHIP_BIAS_UNRESOLVED"
  }
]

## 门禁

由于当前已结算数据集中于单一资产、时间覆盖不足且既有 OOS 指标无优势，生产模型与 Champion 继续为 NONE。
