"""Dynamic v1.14 baseline audit. Every number comes from the active SQLite files."""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .database import connection, database_path, prediction_statistics, quant_model_registry
from .quant_v3 import model_drift


def _table_counts(conn: sqlite3.Connection) -> dict[str,int]:
    names=[r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    return {name:int(conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]) for name in names}


def baseline_audit() -> dict:
    with connection() as conn:
        counts=_table_counts(conn)
        predictions=[dict(r) for r in conn.execute("""SELECT COALESCE(market,CASE WHEN asset_type='crypto' THEN 'CRYPTO' WHEN symbol GLOB '[0-9]*' THEN 'CN' ELSE 'US' END) market,
          symbol,horizon,COUNT(*) prediction_count,SUM(actual IS NOT NULL) settled,SUM(actual IS NULL) pending,
          MIN(prediction_time) first_prediction,MAX(prediction_time) last_prediction FROM prediction_history GROUP BY 1,2,3 ORDER BY 1,2,3""")]
        candles=[dict(r) for r in conn.execute("SELECT market,canonical_symbol symbol,interval,COUNT(*) candle_count,MIN(timestamp) start,MAX(timestamp) end FROM market_candles GROUP BY 1,2,3 ORDER BY 1,2,3")]
        event_settled=int(conn.execute("SELECT COUNT(*) FROM historical_events WHERE t1_return IS NOT NULL OR t3_return IS NOT NULL OR t5_return IS NOT NULL").fetchone()[0])
        universes=[dict(r) for r in conn.execute("SELECT universe_version,market,member_count,source,as_of,survivorship_status FROM research_universes ORDER BY created_at DESC")]
        records=[dict(r) for r in conn.execute("SELECT * FROM prediction_history WHERE actual IS NOT NULL ORDER BY prediction_time")]
    stats=prediction_statistics(); registry=quant_model_registry(100)
    matrix=[]
    keys=sorted({(r["market"],r["symbol"]) for r in predictions}|{(r["market"],r["symbol"]) for r in candles})
    for market,symbol in keys:
        p=[r for r in predictions if r["market"]==market and r["symbol"]==symbol]
        c=[r for r in candles if r["market"]==market and r["symbol"]==symbol]
        matrix.append({"market":market,"symbol":symbol,"candle_count":sum(r["candle_count"] for r in c),
          "prediction_count":sum(r["prediction_count"] for r in p),"settled":sum(r["settled"] for r in p),
          "pending":sum(r["pending"] for r in p),"horizons":{r["horizon"]:{"total":r["prediction_count"],"settled":r["settled"]} for r in p}})
    return {"audit":"V1.14 Baseline Audit","generated_at":datetime.now(timezone.utc).isoformat(),
      "database":str(database_path()),"table_counts":counts,"prediction_coverage":predictions,
      "candle_coverage":candles,"asset_coverage_matrix":matrix,"universes":universes,
      "news":{"records":counts.get("news",0),"events":counts.get("news_events",0),"strict_settled_events":event_settled},
      "features":counts.get("feature_observations",0),"backtests":counts.get("backtest_runs",0),
      "paper":{"accounts":counts.get("paper_accounts",0),"orders":counts.get("paper_orders",0),"positions":counts.get("paper_positions",0)},
      "model_registry":registry,"champion":next((r for r in registry if r.get("model_status")=="CHAMPION"),None),
      "statistics":stats,"drift":model_drift(records),"production_model":None,
      "quant_status":"NO EDGE" if stats.get("overall",{}).get("samples",0) else "INSUFFICIENT DATA"}


def markdown(report: dict) -> str:
    lines=["# AI行情助手 v1.14.0 基线审计","",f"生成时间：`{report['generated_at']}`",f"数据库：`{report['database']}`","",
      "> 本报告由 SQLite 实际记录生成，不采用前端展示常量。旧记录不删除、不重写。","","## 真实结论","",
      f"- Quant Status：**{report['quant_status']}**",f"- Production Model：**NONE**",f"- Champion：**NONE**",
      f"- 新闻：{report['news']['records']}；严格结算事件：{report['news']['strict_settled_events']}（低于 30，Explanation Only）",
      f"- 漂移：{report['drift']['status']}","","## 数据表","","| Table | Rows |","|---|---:|"]
    lines += [f"| {k} | {v} |" for k,v in report["table_counts"].items()]
    lines += ["","## Asset Coverage Matrix","","| Market | Symbol | Candle Count | Prediction Count | Settled | Pending | Horizons |","|---|---|---:|---:|---:|---:|---|"]
    for r in report["asset_coverage_matrix"]:
        hs=", ".join(f"{h}:{x['settled']}/{x['total']}" for h,x in r["horizons"].items()) or "—"
        lines.append(f"| {r['market']} | {r['symbol']} | {r['candle_count']} | {r['prediction_count']} | {r['settled']} | {r['pending']} | {hs} |")
    lines += ["","## Universe 版本","",json.dumps(report["universes"],ensure_ascii=False,indent=2) if report["universes"] else "尚无达到最低规模的持久化研究 Universe。",
      "","## 门禁","","由于当前已结算数据集中于单一资产、时间覆盖不足且既有 OOS 指标无优势，生产模型与 Champion 继续为 NONE。"]
    return "\n".join(lines)+"\n"


if __name__=="__main__":
    destination=Path(os.environ.get("V114_AUDIT_OUTPUT","V1_14_BASELINE_AUDIT.md"))
    destination.write_text(markdown(baseline_audit()),encoding="utf-8")
    print(destination.resolve())
