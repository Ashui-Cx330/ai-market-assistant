"""Generate v1.14 research reports from the active user database."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from backend.audit_v114 import baseline_audit, markdown
from backend.database import connection

ROOT=Path(__file__).resolve().parents[1]


def write(name: str, title: str, body: list[str]):
    (ROOT/name).write_text("# "+title+"\n\n"+"\n\n".join(body)+"\n",encoding="utf-8")


report=baseline_audit();counts=report["table_counts"];stats=report["statistics"].get("overall",{})
(ROOT/"V1_14_BASELINE_AUDIT.md").write_text(markdown(report),encoding="utf-8")
with connection() as conn:
    null_news=conn.execute("SELECT COUNT(*) FROM news WHERE published_at IS NULL OR trim(published_at)='' ").fetchone()[0]
    future_news=conn.execute("SELECT COUNT(*) FROM news WHERE published_at IS NOT NULL AND collected_at IS NOT NULL AND datetime(published_at)>datetime(collected_at)").fetchone()[0]
    settled_by_market=[dict(r) for r in conn.execute("""SELECT COALESCE(market,CASE WHEN asset_type='crypto' THEN 'CRYPTO' WHEN symbol GLOB '[0-9]*' THEN 'CN' ELSE 'US' END) market,COUNT(*) samples FROM prediction_history WHERE actual IS NOT NULL GROUP BY 1""")]
    universes=[dict(r) for r in conn.execute("SELECT market,member_count,universe_version,survivorship_status FROM research_universes ORDER BY created_at DESC")]

common=f"生成自 `{report['database']}`；生成时间 `{report['generated_at']}`。不使用 Mock，不删除失败样本。"
write("DATASET_AUDIT_V4.md","Dataset Audit V4",[common,
  f"增量行情表当前 `{counts.get('market_candles',0)}` 行；历史特征观测 `{counts.get('feature_observations',0)}` 行。v1.14 启用 OHLC、负成交量、重复和乱序校验。",
  f"已结算分市场：`{json.dumps(settled_by_market,ensure_ascii=False)}`。当前多资产覆盖不足，结论：**INSUFFICIENT DATA**。"])
write("LABEL_AUDIT_V4.md","Label Audit V4",[common,
  "固定阈值标签保留为 Benchmark；波动率调整阈值仅可从每个训练窗口估计。收益定义为 `P(t+h)/P(t)-1`，股票按实际后续交易 Bar、Crypto 按 1H/4H/24H/7D UTC Bar。",
  "测试集不得调阈值。当前未产生足够的多资产新样本，标签比较状态：**INSUFFICIENT DATA**。"])
write("TEMPORAL_LEAKAGE_AUDIT_V4.md","Temporal Leakage Audit V4",[common,
  f"新闻 `{counts.get('news',0)}` 条；缺失 publishedAt `{null_news}`；publishedAt 晚于 collectedAt `{future_news}`。时间未知的新闻不得进入特征。",
  "当前新闻生产概率权重为 0；历史研究采用顺序 Walk-Forward、禁止 shuffle。已知生产泄漏：**未发现**；数据时间异常需隔离。"])
write("UNIVERSE_AUDIT_V4.md","Universe Audit V4",[common,
  f"持久化 Universe：`{json.dumps(universes,ensure_ascii=False)}`。最低门槛 CN=300、US=100、CRYPTO=50。",
  "仅当前成员列表无法解决退市/IPO 历史归属，因此 survivorship 状态必须保持 `UNRESOLVED`。未达到规模时不得声称横截面验收完成。"])
write("FACTOR_RESEARCH_V4.md","Factor Research V4",[common,
  f"特征观测 `{counts.get('feature_observations',0)}`；本版本未得到满足多资产 Universe 与五窗口要求的新研究运行。",
  "单次 SHAP/Importance 不构成因子有效证据。OOS IC、Rank IC、ICIR、分位收益、换手与 Regime 稳定因子：**NONE QUALIFIED**。"])
write("MODEL_TOURNAMENT_V4.md","Model Tournament V4",[common,
  f"模型注册表记录 `{counts.get('quant_model_registry',0)}`；研究运行 `{counts.get('quant_research_runs',0)}`。",
  "相同数据、特征、标签与窗口的正式 V4 Tournament 尚无合格样本；模型击败 Baseline：**NONE**。"])
write("WALK_FORWARD_V4.md","Walk-Forward V4",[common,
  "引擎要求至少 5 个 chronological rolling/expanding 窗口，训练、验证、测试分离并 purge 未完成标签。",
  "当前没有满足扩大 Universe 后的新五窗口结果；Best/Worst/Median/Std/Positive-window ratio：**UNAVAILABLE**。"])
write("CROSS_SECTIONAL_ALPHA_V4.md","Cross-sectional Alpha V4",[common,
  "Top/Bottom 10%/20%、Long/Short/Long-Short 和含成本指标只有在同一时点足量资产时才计算。",
  "当前持久化大 Universe 未完成且预测结算高度集中于 BTC；正 IC、正 Rank IC、稳定 ICIR、成本后正收益：**未证实**。"])
write("REGIME_ANALYSIS_V4.md","Regime Analysis V4",[common,
  "支持 Bull/Bear/Sideways/High Vol/Low Vol 分组；任何单 Regime 优势不得外推为全市场优势。",
  "当前跨窗口样本不足，结论：**INSUFFICIENT DATA / REGIME UNVERIFIED**。"])
write("NEWS_INCREMENTAL_VALUE_V4.md","News Incremental Value V4",[common,
  f"新闻 `{counts.get('news',0)}`，严格结算事件 `{report['news']['strict_settled_events']}`；最低初步门槛 30。",
  "由于严格事件不足，Price+Factor 与 Price+Factor+News 的同窗口增量 A/B 不具统计资格。News = **EXPLANATION ONLY**，production weight = 0。"])
write("EVENT_STUDY_V4.md","Event Study V4",[common,
  f"严格已结算事件 `{report['news']['strict_settled_events']}`；初步统计门槛 30，更高等级门槛 100。",
  "支持 [-1,+1/+3/+5/+10/+20] 与基准异常收益，但当前 Confidence Interval/分组统计不具资格：**INSUFFICIENT DATA**。"])
write("MODEL_DRIFT_V4.md","Model Drift V4",[common,
  f"状态：**{report['drift']['status']}**；时间覆盖 `{report['drift'].get('time_coverage_days')}` 天，最低要求 `{report['drift'].get('minimum_coverage_days')}` 天。",
  "未因漂移结果自动训练或晋升模型。"])
write("PRODUCTION_READINESS_V4.md","Production Readiness V4",[common,
  f"真实已结算 `{stats.get('samples',0)}`；Accuracy `{stats.get('accuracy')}`；Macro F1 `{stats.get('f1_macro')}`；IC `{stats.get('ic')}`；Rank IC `{stats.get('rank_ic')}`。",
  "多资产稳定性、基准优势、成本后收益、时间覆盖和新闻样本均未通过。Quant Status = **NO EDGE**；Production Model = **NONE**；Champion = **NONE**。"])
write("ALPHA_RESEARCH_REPORT_V4.md","Alpha Research Report V4",[common,
  "流程已具备 Dataset/Label/Leakage/Universe/Factor/Tournament/Walk-Forward/Regime/Cross-sectional/News/Event/Risk/Drift/Production Gate 的审计接口与后台队列。",
  "本次实际数据没有证明 Alpha。最值得补充的是：可复现的大型历史 Universe（含退市成员）、每标的足够长的点时行情、T+5/T+20 自然结算，以及不少于 30/100 的严格事件结果。",
  "最终：Quant Status = **NO EDGE**；Production Model = **NONE**；Champion = **NONE**。"])
print("generated 15 V4 reports")
