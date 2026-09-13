import sqlite3
import os
import json
import math
import re
import numpy as np
import pandas as pd
import uuid
import hashlib
import shutil
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

data_root = os.environ.get("TRADING_AI_DATA_DIR")
if data_root:
    DB_PATH = Path(data_root) / "database" / "trading_ai.db"
else:
    DB_PATH = Path(__file__).resolve().parent.parent / "trading_ai.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_IMPORT_DB_PATH = DB_PATH
_INIT_LOCK = RLock()
SCHEMA_VERSION = "1.14.0"


def _backup_before_migration(path: Path) -> Path | None:
    """Create one recoverable database backup before the v1.14 additive migration."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    try:
        with sqlite3.connect(path) as probe:
            exists = probe.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
            if exists and probe.execute("SELECT 1 FROM schema_migrations WHERE version=?", (SCHEMA_VERSION,)).fetchone():
                return None
    except sqlite3.Error:
        pass
    backup_dir = path.parent.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"trading_ai-pre-v{SCHEMA_VERSION}.db"
    if not backup.exists():
        shutil.copy2(path, backup)
        digest = hashlib.sha256(backup.read_bytes()).hexdigest()
        backup.with_suffix(".db.sha256").write_text(digest, encoding="ascii")
    return backup


def database_path() -> Path:
    """Resolve the desktop data directory at call time.

    PyInstaller's one-file child process can import modules while its bootstrap
    environment is still being normalised.  Re-reading the launcher-provided
    path here prevents SQLite from ever falling back to the temporary _MEI
    extraction directory.  Tests can still override DB_PATH when no launcher
    data directory is present.
    """
    active_root = os.environ.get("TRADING_AI_DATA_DIR")
    return Path(active_root) / "database" / "trading_ai.db" if active_root else DB_PATH


@contextmanager
def connection():
    # Tests and the packaged launcher can switch the data root after import.
    # Always create the exact active parent before opening SQLite.
    active_path = database_path()
    active_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(active_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    # Desktop startup, API tests and worker threads may all enter the migration
    # path at nearly the same time.  SQLite has no `ALTER TABLE ... IF NOT
    # EXISTS`, so the schema inspection and ALTER must be one local critical
    # section.  This keeps repeated startup idempotent without deleting data.
    with _INIT_LOCK:
        _backup_before_migration(database_path())
    with _INIT_LOCK, connection() as conn:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS watchlist (
                symbol TEXT PRIMARY KEY,
                asset_type TEXT NOT NULL CHECK(asset_type IN ('stock', 'crypto')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )"""
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(watchlist)")}
        if "name" not in columns:
            conn.execute("ALTER TABLE watchlist ADD COLUMN name TEXT")
        conn.executescript(
            """CREATE TABLE IF NOT EXISTS paper_accounts (
                currency TEXT PRIMARY KEY, cash REAL NOT NULL, initial_cash REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_positions (
                symbol TEXT NOT NULL, asset_type TEXT NOT NULL, currency TEXT NOT NULL,
                quantity REAL NOT NULL, average_cost REAL NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(symbol, asset_type)
            );
            CREATE TABLE IF NOT EXISTS paper_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, name TEXT, asset_type TEXT NOT NULL,
                side TEXT NOT NULL, price REAL NOT NULL, quantity REAL NOT NULL, fee REAL NOT NULL,
                amount REAL NOT NULL, currency TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS paper_daily_equity (
                trading_date TEXT NOT NULL, currency TEXT NOT NULL, opening_equity REAL NOT NULL,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(trading_date, currency)
            );
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, asset_type TEXT NOT NULL,
                strategy TEXT NOT NULL, interval TEXT NOT NULL, result_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS prediction_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, asset_type TEXT NOT NULL,
                interval TEXT NOT NULL, horizon TEXT NOT NULL, prediction_time TEXT NOT NULL,
                target_time TEXT NOT NULL, entry_price REAL NOT NULL, prediction TEXT NOT NULL,
                prob_down REAL NOT NULL, prob_flat REAL NOT NULL, prob_up REAL NOT NULL,
                threshold REAL NOT NULL, regime TEXT, decision TEXT, stop_loss REAL, tp1 REAL,
                payload_json TEXT NOT NULL, actual TEXT, actual_return REAL, correct INTEGER,
                stop_hit INTEGER, tp_hit INTEGER, realized_r REAL, resolved_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, interval, horizon, prediction_time)
            );
            CREATE TABLE IF NOT EXISTS feature_observations (
                feature_timestamp TEXT NOT NULL, asset TEXT NOT NULL, feature_name TEXT NOT NULL,
                value REAL, source TEXT NOT NULL, quality TEXT NOT NULL, collected_at TEXT NOT NULL,
                PRIMARY KEY(feature_timestamp,asset,feature_name,source)
            );
            CREATE TABLE IF NOT EXISTS news (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT NOT NULL, source TEXT,
                provider TEXT, scope TEXT, published_at TEXT, collected_at TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS news_events (
                news_id TEXT PRIMARY KEY, subject TEXT, event_type TEXT, category TEXT, event_time TEXT,
                direction TEXT, magnitude INTEGER, confidence REAL, payload_json TEXT NOT NULL,
                FOREIGN KEY(news_id) REFERENCES news(id)
            );
            CREATE TABLE IF NOT EXISTS news_sentiment (
                news_id TEXT PRIMARY KEY, score REAL NOT NULL, direction TEXT NOT NULL, method TEXT NOT NULL,
                payload_json TEXT NOT NULL, FOREIGN KEY(news_id) REFERENCES news(id)
            );
            CREATE TABLE IF NOT EXISTS news_impacts (
                news_id TEXT PRIMARY KEY, impact_score REAL NOT NULL, payload_json TEXT NOT NULL,
                FOREIGN KEY(news_id) REFERENCES news(id)
            );
            CREATE TABLE IF NOT EXISTS news_stock_relations (
                news_id TEXT NOT NULL, symbol TEXT NOT NULL, relation TEXT NOT NULL,
                PRIMARY KEY(news_id,symbol), FOREIGN KEY(news_id) REFERENCES news(id)
            );
            CREATE TABLE IF NOT EXISTS news_sector_relations (
                news_id TEXT NOT NULL, sector TEXT NOT NULL, direction TEXT,
                PRIMARY KEY(news_id,sector), FOREIGN KEY(news_id) REFERENCES news(id)
            );
            CREATE TABLE IF NOT EXISTS historical_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, news_id TEXT NOT NULL, symbol TEXT,
                event_time TEXT NOT NULL, entry_time TEXT NOT NULL, t1_return REAL, t3_return REAL,
                t5_return REAL, t10_return REAL, t20_return REAL, payload_json TEXT, UNIQUE(news_id,symbol)
            );
            CREATE TABLE IF NOT EXISTS news_provider_health (
                provider TEXT PRIMARY KEY, status TEXT NOT NULL, item_count INTEGER NOT NULL,
                latency_ms INTEGER, error TEXT, markets TEXT, checked_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS news_prediction_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, decision_time TEXT NOT NULL,
                horizon TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS trading_decisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, decision_time TEXT NOT NULL,
                payload_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_score_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT NOT NULL, asset_type TEXT NOT NULL,
                score INTEGER NOT NULL, observed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS market_intelligence_snapshots (
                snapshot_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, asset_type TEXT NOT NULL,
                model_version TEXT, data_cutoff TEXT NOT NULL, generated_at TEXT NOT NULL,
                trigger_reason TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_market_intelligence_asset
                ON market_intelligence_snapshots(symbol,asset_type,generated_at DESC);
            CREATE TABLE IF NOT EXISTS quant_prediction_snapshots (
                prediction_id TEXT PRIMARY KEY, symbol TEXT NOT NULL, asset_type TEXT NOT NULL,
                interval TEXT NOT NULL, data_cutoff TEXT NOT NULL, generated_at TEXT NOT NULL,
                model_version TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_quant_snapshot_asset
                ON quant_prediction_snapshots(symbol,asset_type,generated_at DESC);
            CREATE TABLE IF NOT EXISTS quant_research_runs (
                run_id TEXT PRIMARY KEY, market TEXT NOT NULL, interval TEXT NOT NULL,
                horizon TEXT NOT NULL, dataset_version TEXT NOT NULL, status TEXT NOT NULL,
                champion TEXT, challenger TEXT, generated_at TEXT NOT NULL, payload_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_quant_research_market
                ON quant_research_runs(market,generated_at DESC);
            CREATE TABLE IF NOT EXISTS quant_model_registry (
                model_id TEXT PRIMARY KEY, market TEXT NOT NULL, horizon TEXT NOT NULL,
                model_name TEXT NOT NULL, model_status TEXT NOT NULL, feature_version TEXT NOT NULL,
                dataset_version TEXT NOT NULL, training_period TEXT NOT NULL,
                hyperparameters_json TEXT NOT NULL, validation_metrics_json TEXT NOT NULL,
                test_metrics_json TEXT NOT NULL, trained_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS symbol_master (
                canonical_symbol TEXT NOT NULL, market TEXT NOT NULL, exchange TEXT NOT NULL,
                asset_type TEXT NOT NULL, display_name TEXT NOT NULL, currency TEXT NOT NULL,
                timezone TEXT NOT NULL, session TEXT NOT NULL, provider_symbol TEXT NOT NULL,
                aliases TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1,
                delisted INTEGER NOT NULL DEFAULT 0, sector TEXT, industry TEXT,
                source TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(canonical_symbol,market)
            );
            CREATE TABLE IF NOT EXISTS research_universes (
                universe_version TEXT PRIMARY KEY, market TEXT NOT NULL, source TEXT NOT NULL,
                as_of TEXT NOT NULL, survivorship_status TEXT NOT NULL, member_count INTEGER NOT NULL,
                payload_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS research_universe_members (
                universe_version TEXT NOT NULL, canonical_symbol TEXT NOT NULL,
                effective_from TEXT, effective_to TEXT, active INTEGER NOT NULL DEFAULT 1,
                metadata_json TEXT NOT NULL, PRIMARY KEY(universe_version,canonical_symbol)
            );
            CREATE TABLE IF NOT EXISTS market_candles (
                market TEXT NOT NULL, canonical_symbol TEXT NOT NULL, interval TEXT NOT NULL,
                timestamp TEXT NOT NULL, open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
                close REAL NOT NULL, volume REAL NOT NULL, amount REAL, source TEXT NOT NULL,
                collected_at TEXT NOT NULL, PRIMARY KEY(market,canonical_symbol,interval,timestamp)
            );
            CREATE TABLE IF NOT EXISTS prediction_settlement_audit (
                prediction_id INTEGER NOT NULL, attempted_at TEXT NOT NULL, status TEXT NOT NULL,
                market TEXT, canonical_symbol TEXT, settlement_timestamp TEXT,
                settlement_price REAL, source TEXT, reason TEXT, payload_json TEXT NOT NULL,
                PRIMARY KEY(prediction_id,attempted_at)
            );
            CREATE TABLE IF NOT EXISTS research_jobs (
                job_id TEXT PRIMARY KEY, job_type TEXT NOT NULL, status TEXT NOT NULL,
                request_json TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
                result_json TEXT, error TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, started_at TEXT, completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS research_cache (
                cache_key TEXT PRIMARY KEY, dataset_hash TEXT NOT NULL, feature_hash TEXT NOT NULL,
                model_hash TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
                last_accessed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS provider_health_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, provider TEXT NOT NULL, status TEXT NOT NULL,
                last_successful_fetch TEXT, last_check TEXT NOT NULL, last_data_timestamp TEXT,
                latency_ms INTEGER, error_rate REAL, error TEXT, payload_json TEXT NOT NULL
            );"""
        )
        prediction_columns={row[1] for row in conn.execute("PRAGMA table_info(prediction_history)")}
        migrations={"prediction_id":"TEXT","model_version":"TEXT","feature_version":"TEXT","risk_reward":"REAL",
                    "expected_value":"REAL","data_quality":"REAL","status":"TEXT DEFAULT 'ACTIVE'",
                    "mae":"REAL","mfe":"REAL","expired_at":"TEXT","invalidation_reason":"TEXT",
                    "strategy_version":"TEXT","tp2":"REAL","probability_calibration":"TEXT"}
        migrations["failure_reason"]="TEXT"
        migrations.update({"market":"TEXT", "exchange":"TEXT", "settlement_status":"TEXT",
                           "settlement_attempted_at":"TEXT", "settlement_source":"TEXT"})
        for name,sql_type in migrations.items():
            if name not in prediction_columns:conn.execute(f"ALTER TABLE prediction_history ADD COLUMN {name} {sql_type}")
        # Metadata-only backfill for rows created before SymbolMaster existed.
        # Predictions, probabilities, outcomes and immutable payloads are not changed.
        conn.execute("""UPDATE prediction_history SET market=CASE
          WHEN asset_type='crypto' THEN 'CRYPTO'
          WHEN symbol GLOB '[0-9]*' THEN 'CN' ELSE 'US' END WHERE market IS NULL""")
        conn.execute("""UPDATE prediction_history SET exchange=CASE
          WHEN market='CRYPTO' THEN 'OKX'
          WHEN market='CN' AND (symbol LIKE '6%' OR symbol LIKE '9%') THEN 'SSE'
          WHEN market='CN' THEN 'SZSE' ELSE 'US' END WHERE exchange IS NULL""")
        account_columns={row[1] for row in conn.execute("PRAGMA table_info(paper_accounts)")}
        if "frozen_cash" not in account_columns:conn.execute("ALTER TABLE paper_accounts ADD COLUMN frozen_cash REAL NOT NULL DEFAULT 0")
        position_columns={row[1] for row in conn.execute("PRAGMA table_info(paper_positions)")}
        if "frozen_quantity" not in position_columns:conn.execute("ALTER TABLE paper_positions ADD COLUMN frozen_quantity REAL NOT NULL DEFAULT 0")
        order_columns={row[1] for row in conn.execute("PRAGMA table_info(paper_orders)")}
        for name,sql_type in {"user_id":"TEXT DEFAULT 'local'","order_type":"TEXT DEFAULT 'MARKET'","limit_price":"REAL","status":"TEXT DEFAULT 'filled'","filled_at":"TEXT","cancelled_at":"TEXT","reject_reason":"TEXT"}.items():
            if name not in order_columns:conn.execute(f"ALTER TABLE paper_orders ADD COLUMN {name} {sql_type}")
        conn.execute("UPDATE paper_orders SET order_type=COALESCE(order_type,'MARKET'),status=COALESCE(status,'filled'),filled_at=COALESCE(filled_at,created_at)")
        historical_columns={row[1] for row in conn.execute("PRAGMA table_info(historical_events)")}
        for name,sql_type in {"t10_return":"REAL","payload_json":"TEXT"}.items():
            if name not in historical_columns:conn.execute(f"ALTER TABLE historical_events ADD COLUMN {name} {sql_type}")
        conn.executemany("INSERT OR IGNORE INTO paper_accounts(currency,cash,initial_cash) VALUES(?,?,?)",
                         [("USDT",100000.0,100000.0),("CNY",100000.0,100000.0),("USD",100000.0,100000.0)])
        count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT INTO watchlist(symbol, asset_type) VALUES (?, ?)",
                [("600519", "stock"), ("300750", "stock"), ("BTC", "crypto"), ("ETH", "crypto")],
            )
        conn.execute("INSERT OR IGNORE INTO schema_migrations(version) VALUES(?)", (SCHEMA_VERSION,))


def save_news_intelligence(items: list[dict], symbol: str | None = None) -> int:
    """Upsert normalized observed news and derived, explicitly-labelled analysis."""
    saved = 0
    with connection() as conn:
        for item in items:
            payload = json.dumps(item, ensure_ascii=False)
            conn.execute("""INSERT OR REPLACE INTO news
                (id,title,url,source,provider,scope,published_at,collected_at,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (item["id"], item["title"], item["url"], item.get("source"), item.get("provider"),
                 item.get("scope"), item.get("published_at"), item.get("collected_at"), payload))
            event, sentiment, impact = item["event"], item["sentiment"], item["impact"]
            conn.execute("""INSERT OR REPLACE INTO news_events
                (news_id,subject,event_type,category,event_time,direction,magnitude,confidence,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?)""", (item["id"], event.get("subject"), event.get("event_type"),
                item.get("category"), event.get("event_time"), event.get("direction"), event.get("magnitude"),
                event.get("confidence"), json.dumps(event, ensure_ascii=False)))
            conn.execute("INSERT OR REPLACE INTO news_sentiment VALUES(?,?,?,?,?)",
                         (item["id"], sentiment["score"], sentiment["direction"], sentiment["method"],
                          json.dumps(sentiment, ensure_ascii=False)))
            conn.execute("INSERT OR REPLACE INTO news_impacts VALUES(?,?,?)",
                         (item["id"], impact["score"], json.dumps(impact, ensure_ascii=False)))
            # Never associate every result with the query target. Only explicit
            # entities/provider metadata become relations.
            conn.execute("DELETE FROM news_stock_relations WHERE news_id=?", (item["id"],))
            for related in item.get("symbols", []) or item.get("event", {}).get("affected_symbols", []):
                relation = "provider-metadata" if related in item.get("symbols", []) else "entity-match"
                conn.execute("INSERT OR REPLACE INTO news_stock_relations VALUES(?,?,?)",
                             (item["id"], str(related).upper(), relation))
            for relation in impact.get("secondary", []):
                conn.execute("INSERT OR REPLACE INTO news_sector_relations VALUES(?,?,?)",
                             (item["id"], relation["target"], relation["direction"]))
            saved += 1
    return saved


def load_news_intelligence(symbol: str | None = None, limit: int = 500) -> list[dict]:
    with connection() as conn:
        if symbol:
            upper=str(symbol).upper();base=re.sub(r"\.(SH|SZ)$","",upper)
            rows = conn.execute("""SELECT DISTINCT n.payload_json,h.payload_json AS outcome_json FROM news n
                JOIN news_stock_relations r ON r.news_id=n.id
                LEFT JOIN historical_events h ON h.news_id=n.id AND h.symbol=r.symbol
                WHERE r.symbol IN (?,?) ORDER BY COALESCE(n.published_at,n.collected_at) DESC LIMIT ?""", (upper,base,limit)).fetchall()
        else:
            rows = conn.execute("SELECT payload_json FROM news ORDER BY COALESCE(published_at,collected_at) DESC LIMIT ?", (limit,)).fetchall()
    result=[]
    for row in rows:
        item=json.loads(row[0])
        if len(row.keys())>1 and row["outcome_json"]: item["historical_outcome"]=json.loads(row["outcome_json"])
        result.append(item)
    return result


def query_news_intelligence(symbol: str | None = None, market: str | None = None,
                            category: str | None = None, direction: str | None = None,
                            keyword: str | None = None, hours: int | None = None,
                            page: int = 1, page_size: int = 20) -> dict:
    """Filter persisted normalized payloads and paginate after deterministic sorting."""
    from datetime import datetime, timedelta, timezone
    rows = load_news_intelligence(symbol, 5000)
    needle = (keyword or "").strip().lower()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours) if hours else None
    selected = []
    for item in rows:
        if "�" in str(item.get("title") or ""): continue
        if market and market not in {"全部", "全球"} and item.get("market") != market: continue
        if category and category != "全部" and item.get("category") != category: continue
        label = item.get("sentiment", {}).get("label")
        wanted = {"利好":"bullish", "利空":"bearish", "中性":"neutral"}.get(direction, direction)
        if wanted and wanted not in {"全部", "all"} and label != wanted: continue
        if needle and needle not in f"{item.get('title','')} {item.get('summary','')} {' '.join(item.get('symbols',[]))} {' '.join(item.get('sectors',[]))}".lower(): continue
        if cutoff:
            try:
                stamp=datetime.fromisoformat(str(item.get("published_at")).replace("Z","+00:00"))
                if stamp.tzinfo is None: stamp=stamp.replace(tzinfo=timezone.utc)
                if stamp < cutoff: continue
            except (TypeError,ValueError): continue
        selected.append(item)
    selected.sort(key=lambda x:(x.get("impact",{}).get("score",0),x.get("published_at") or ""),reverse=True)
    start=(max(1,page)-1)*page_size
    return {"items":selected[start:start+page_size],"total":len(selected),"page":max(1,page),
            "page_size":page_size,"has_more":start+page_size<len(selected)}


def get_news_intelligence(news_id: str) -> dict | None:
    with connection() as conn:
        row=conn.execute("SELECT payload_json FROM news WHERE id=?",(news_id,)).fetchone()
    return json.loads(row[0]) if row else None


def save_provider_health(statuses: list[dict]) -> None:
    from datetime import datetime, timezone
    checked=datetime.now(timezone.utc).isoformat()
    with connection() as conn:
        for row in statuses:
            raw_status=str(row.get("status") or "ERROR").upper()
            normalized={"HEALTHY":"CONNECTED","CONNECTED":"CONNECTED","PARTIAL":"DEGRADED",
                        "DEGRADED":"DEGRADED","ERROR":"ERROR","DISCONNECTED":"DISCONNECTED"}.get(raw_status,"ERROR")
            previous=conn.execute("SELECT checked_at FROM news_provider_health WHERE provider=? AND status IN ('HEALTHY','CONNECTED')",
                                  (row["provider"],)).fetchone()
            last_success=checked if normalized == "CONNECTED" else (previous[0] if previous else None)
            conn.execute("""INSERT OR REPLACE INTO news_provider_health
                (provider,status,item_count,latency_ms,error,markets,checked_at) VALUES(?,?,?,?,?,?,?)""",
                (row["provider"],row["status"],row.get("count",0),row.get("latency_ms"),row.get("error"),
                 json.dumps(row.get("markets",[]),ensure_ascii=False),checked))
            conn.execute("""INSERT INTO provider_health_events
                (provider,status,last_successful_fetch,last_check,last_data_timestamp,latency_ms,error_rate,error,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?)""",(row["provider"],normalized,last_success,checked,
                row.get("last_data_timestamp"),row.get("latency_ms"),0.0 if normalized=="CONNECTED" else 1.0,
                row.get("error"),json.dumps(row,ensure_ascii=False)))


def load_provider_health() -> list[dict]:
    with connection() as conn: rows=conn.execute("SELECT * FROM news_provider_health ORDER BY provider").fetchall()
    return [{**dict(row),"markets":json.loads(row["markets"] or "[]")} for row in rows]


def provider_health_snapshot(stale_after_seconds: int = 3600) -> list[dict]:
    """Return honest provider state; an old successful check is STALE, never CONNECTED."""
    from datetime import datetime, timezone
    now=datetime.now(timezone.utc); output=[]
    with connection() as conn:
        providers=[row[0] for row in conn.execute("SELECT DISTINCT provider FROM provider_health_events ORDER BY provider")]
        if not providers:
            legacy=[dict(row) for row in conn.execute("SELECT * FROM news_provider_health ORDER BY provider")]
            for item in legacy:
                raw=str(item.get("status") or "ERROR").upper();checked=item.get("checked_at")
                status={"HEALTHY":"CONNECTED","CONNECTED":"CONNECTED","PARTIAL":"DEGRADED"}.get(raw,raw if raw in {"DEGRADED","ERROR","DISCONNECTED"} else "ERROR")
                stamp=pd.Timestamp(checked);stamp=stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
                age=(now-stamp.to_pydatetime()).total_seconds()
                if status=="CONNECTED" and age>stale_after_seconds:status="STALE"
                output.append({"provider":item["provider"],"status":status,"last_successful_fetch":checked if raw in {"HEALTHY","CONNECTED"} else None,
                  "last_check":checked,"last_data_timestamp":None,"latency_ms":item.get("latency_ms"),"error_rate":0.0 if raw in {"HEALTHY","CONNECTED"} else 1.0,
                  "error":item.get("error"),"freshness_seconds":max(0,round(age)),"payload":item})
            return output
        for provider in providers:
            event=conn.execute("SELECT * FROM provider_health_events WHERE provider=? ORDER BY id DESC LIMIT 1",(provider,)).fetchone()
            recent=conn.execute("SELECT AVG(CASE WHEN status='CONNECTED' THEN 0.0 ELSE 1.0 END) FROM (SELECT status FROM provider_health_events WHERE provider=? ORDER BY id DESC LIMIT 20)",(provider,)).fetchone()[0]
            item=dict(event); checked=pd.Timestamp(item["last_check"])
            checked=checked.tz_localize("UTC") if checked.tzinfo is None else checked.tz_convert("UTC")
            age=(now-checked.to_pydatetime()).total_seconds()
            if item["status"]=="CONNECTED" and age>stale_after_seconds:item["status"]="STALE"
            item["freshness_seconds"]=max(0,round(age));item["error_rate"]=round(float(recent or 0),4)
            item["payload"]=json.loads(item.pop("payload_json") or "{}")
            output.append(item)
    return output


def save_historical_event_outcomes(symbol: str, outcomes: list[dict]) -> int:
    count=0
    with connection() as conn:
        for row in outcomes:
            returns=row.get("returns",{})
            conn.execute("""INSERT OR REPLACE INTO historical_events
                (news_id,symbol,event_time,entry_time,t1_return,t3_return,t5_return,t10_return,t20_return,payload_json)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",(row["news_id"],symbol,row["event_time"],row["entry_time"],
                returns.get("T+1"),returns.get("T+3"),returns.get("T+5"),returns.get("T+10"),returns.get("T+20"),
                json.dumps(row,ensure_ascii=False)));count+=1
    return count


def list_watchlist() -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute("SELECT symbol, name, asset_type, created_at FROM watchlist ORDER BY created_at")]


def add_watchlist(symbol: str, asset_type: str, name: str | None = None) -> None:
    with connection() as conn:
        conn.execute("INSERT INTO watchlist(symbol, asset_type, name) VALUES (?, ?, ?) ON CONFLICT(symbol) DO UPDATE SET name=excluded.name, asset_type=excluded.asset_type", (symbol, asset_type, name))


def paper_snapshot() -> dict:
    with connection() as conn:
        return {"accounts":[dict(r) for r in conn.execute("SELECT * FROM paper_accounts ORDER BY currency")],
                "positions":[dict(r) for r in conn.execute("SELECT * FROM paper_positions WHERE quantity > 0 ORDER BY updated_at DESC")],
                "orders":[dict(r) for r in conn.execute("SELECT * FROM paper_orders ORDER BY id DESC LIMIT 200")]}


def paper_daily_pnl(currency: str, total_equity: float, trading_date: str) -> float:
    """Persist the first observed equity of a day and compare subsequent marks to it."""
    with connection() as conn:
        conn.execute("INSERT OR IGNORE INTO paper_daily_equity(trading_date,currency,opening_equity) VALUES(?,?,?)",
                     (trading_date,currency,total_equity))
        row=conn.execute("SELECT opening_equity FROM paper_daily_equity WHERE trading_date=? AND currency=?",
                         (trading_date,currency)).fetchone()
        return round(total_equity-float(row["opening_equity"]),2)


def _paper_currency(symbol: str, asset_type: str) -> str:
    if asset_type == "crypto": return "USDT"
    return "CNY" if re.fullmatch(r"\d{6}(?:\.(?:SH|SZ))?", symbol.upper()) else "USD"


def execute_paper_order(symbol: str, name: str, asset_type: str, side: str, price: float, quantity: float, fee_rate: float) -> dict:
    currency=_paper_currency(symbol,asset_type);side=side.upper();amount=price*quantity;fee=amount*fee_rate
    if quantity<=0 or price<=0:raise ValueError("数量和价格必须大于 0")
    with connection() as conn:
        account=conn.execute("SELECT * FROM paper_accounts WHERE currency=?",(currency,)).fetchone();position=conn.execute("SELECT * FROM paper_positions WHERE symbol=? AND asset_type=?",(symbol,asset_type)).fetchone()
        if side=="BUY":
            required=amount+fee
            if account["cash"]<required:raise ValueError("模拟账户可用资金不足")
            old_q=position["quantity"] if position else 0;old_cost=(position["average_cost"]*old_q) if position else 0;new_q=old_q+quantity;avg=(old_cost+amount+fee)/new_q
            conn.execute("UPDATE paper_accounts SET cash=cash-? WHERE currency=?",(required,currency))
            conn.execute("INSERT INTO paper_positions(symbol,asset_type,currency,quantity,average_cost) VALUES(?,?,?,?,?) ON CONFLICT(symbol,asset_type) DO UPDATE SET quantity=excluded.quantity,average_cost=excluded.average_cost,updated_at=CURRENT_TIMESTAMP",(symbol,asset_type,currency,new_q,avg))
        elif side=="SELL":
            if not position or position["quantity"]-position["frozen_quantity"]+1e-12<quantity:raise ValueError("模拟持仓数量不足或已被限价单冻结")
            conn.execute("UPDATE paper_accounts SET cash=cash+? WHERE currency=?",(amount-fee,currency))
            conn.execute("UPDATE paper_positions SET quantity=quantity-?,updated_at=CURRENT_TIMESTAMP WHERE symbol=? AND asset_type=?",(quantity,symbol,asset_type))
        else:raise ValueError("side 必须是 BUY 或 SELL")
        cur=conn.execute("INSERT INTO paper_orders(symbol,name,asset_type,side,price,quantity,fee,amount,currency,order_type,status,filled_at) VALUES(?,?,?,?,?,?,?,?,?,'MARKET','filled',CURRENT_TIMESTAMP)",(symbol,name,asset_type,side,price,quantity,fee,amount,currency))
        return dict(conn.execute("SELECT * FROM paper_orders WHERE id=?",(cur.lastrowid,)).fetchone())


def create_limit_order(symbol: str, name: str, asset_type: str, side: str, limit_price: float,
                       quantity: float, fee_rate: float) -> dict:
    currency=_paper_currency(symbol,asset_type);side=side.upper()
    if quantity<=0 or limit_price<=0:raise ValueError("数量和限价必须大于0")
    reserved=limit_price*quantity*(1+fee_rate)
    with connection() as conn:
        if side=="BUY":
            account=conn.execute("SELECT * FROM paper_accounts WHERE currency=?",(currency,)).fetchone()
            if not account:conn.execute("INSERT INTO paper_accounts(currency,cash,initial_cash,frozen_cash) VALUES(?,?,?,0)",(currency,100000,100000));account=conn.execute("SELECT * FROM paper_accounts WHERE currency=?",(currency,)).fetchone()
            if account["cash"]<reserved:raise ValueError("模拟账户可用资金不足")
            conn.execute("UPDATE paper_accounts SET cash=cash-?,frozen_cash=frozen_cash+? WHERE currency=?",(reserved,reserved,currency))
        elif side=="SELL":
            pos=conn.execute("SELECT * FROM paper_positions WHERE symbol=? AND asset_type=?",(symbol,asset_type)).fetchone()
            if not pos or pos["quantity"]-pos["frozen_quantity"]+1e-12<quantity:raise ValueError("可卖持仓数量不足")
            conn.execute("UPDATE paper_positions SET frozen_quantity=frozen_quantity+? WHERE symbol=? AND asset_type=?",(quantity,symbol,asset_type))
        else:raise ValueError("side 必须是 BUY 或 SELL")
        cur=conn.execute("""INSERT INTO paper_orders(symbol,name,asset_type,side,price,limit_price,quantity,fee,amount,currency,order_type,status)
            VALUES(?,?,?,?,?,?,?,?,?,?,'LIMIT','pending')""",(symbol,name,asset_type,side,limit_price,limit_price,quantity,0,limit_price*quantity,currency))
        return dict(conn.execute("SELECT * FROM paper_orders WHERE id=?",(cur.lastrowid,)).fetchone())


def fill_limit_order(order_id: int, market_price: float, fee_rate: float) -> dict | None:
    with connection() as conn:
        order=conn.execute("SELECT * FROM paper_orders WHERE id=? AND status='pending'",(order_id,)).fetchone()
        if not order:return None
        if order["side"]=="BUY" and market_price>order["limit_price"]:return None
        if order["side"]=="SELL" and market_price<order["limit_price"]:return None
        quantity=float(order["quantity"]);amount=market_price*quantity;fee=amount*fee_rate
        if order["side"]=="BUY":
            reserved=order["limit_price"]*quantity*(1+fee_rate)
            conn.execute("UPDATE paper_accounts SET frozen_cash=frozen_cash-?,cash=cash+? WHERE currency=?",(reserved,reserved-amount-fee,order["currency"]))
            pos=conn.execute("SELECT * FROM paper_positions WHERE symbol=? AND asset_type=?",(order["symbol"],order["asset_type"])).fetchone();oldq=pos["quantity"] if pos else 0;oldcost=pos["average_cost"]*oldq if pos else 0;newq=oldq+quantity;avg=(oldcost+amount+fee)/newq
            conn.execute("INSERT INTO paper_positions(symbol,asset_type,currency,quantity,average_cost) VALUES(?,?,?,?,?) ON CONFLICT(symbol,asset_type) DO UPDATE SET quantity=excluded.quantity,average_cost=excluded.average_cost,updated_at=CURRENT_TIMESTAMP",(order["symbol"],order["asset_type"],order["currency"],newq,avg))
        else:
            conn.execute("UPDATE paper_positions SET quantity=quantity-?,frozen_quantity=frozen_quantity-?,updated_at=CURRENT_TIMESTAMP WHERE symbol=? AND asset_type=?",(quantity,quantity,order["symbol"],order["asset_type"]))
            conn.execute("UPDATE paper_accounts SET cash=cash+? WHERE currency=?",(amount-fee,order["currency"]))
        conn.execute("UPDATE paper_orders SET price=?,amount=?,fee=?,status='filled',filled_at=CURRENT_TIMESTAMP WHERE id=?",(market_price,amount,fee,order_id))
        return dict(conn.execute("SELECT * FROM paper_orders WHERE id=?",(order_id,)).fetchone())


def cancel_paper_order(order_id: int) -> dict:
    with connection() as conn:
        order=conn.execute("SELECT * FROM paper_orders WHERE id=?",(order_id,)).fetchone()
        if not order:raise ValueError("订单不存在")
        if order["status"]!="pending":raise ValueError("只有待成交订单可以撤销")
        fee_rate=.001 if order["asset_type"]=="crypto" else .0003
        if order["side"]=="BUY":
            reserved=order["limit_price"]*order["quantity"]*(1+fee_rate);conn.execute("UPDATE paper_accounts SET cash=cash+?,frozen_cash=frozen_cash-? WHERE currency=?",(reserved,reserved,order["currency"]))
        else:conn.execute("UPDATE paper_positions SET frozen_quantity=frozen_quantity-? WHERE symbol=? AND asset_type=?",(order["quantity"],order["symbol"],order["asset_type"]))
        conn.execute("UPDATE paper_orders SET status='cancelled',cancelled_at=CURRENT_TIMESTAMP WHERE id=?",(order_id,))
        return dict(conn.execute("SELECT * FROM paper_orders WHERE id=?",(order_id,)).fetchone())


def reset_paper_accounts() -> None:
    with connection() as conn:
        conn.execute("DELETE FROM paper_orders");conn.execute("DELETE FROM paper_positions");conn.execute("DELETE FROM paper_daily_equity")
        conn.execute("UPDATE paper_accounts SET cash=initial_cash,frozen_cash=0")


def save_backtest(symbol: str, asset_type: str, strategy: str, interval: str, result: dict) -> int:
    with connection() as conn:
        cursor = conn.execute("INSERT INTO backtest_runs(symbol,asset_type,strategy,interval,result_json) VALUES(?,?,?,?,?)",
                              (symbol,asset_type,strategy,interval,json.dumps(result,ensure_ascii=False)))
        return int(cursor.lastrowid)


def list_backtests(limit: int = 30) -> list[dict]:
    with connection() as conn:
        rows=conn.execute("SELECT id,symbol,asset_type,strategy,interval,result_json,created_at FROM backtest_runs ORDER BY id DESC LIMIT ?",(limit,)).fetchall()
        return [{"id":r["id"],"symbol":r["symbol"],"asset_type":r["asset_type"],"strategy":r["strategy"],"interval":r["interval"],"created_at":r["created_at"],"result":json.loads(r["result_json"])} for r in rows]


def remove_watchlist(symbol: str) -> None:
    with connection() as conn:
        conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))


def save_feature_observations(symbol: str, timestamp: str, frame: pd.DataFrame, source: str, quality: str) -> int:
    latest=frame.iloc[-1];names=[name for name in latest.index if name not in {"timestamp","timestamp_utc"}]
    now=pd.Timestamp.now(tz="UTC").isoformat();saved=0
    with connection() as conn:
        for name in names:
            try:value=float(latest[name])
            except (TypeError,ValueError):continue
            if not math.isfinite(value):continue
            cursor=conn.execute("""INSERT OR REPLACE INTO feature_observations
                (feature_timestamp,asset,feature_name,value,source,quality,collected_at) VALUES(?,?,?,?,?,?,?)""",
                (timestamp,symbol,name,value,source,quality,now));saved+=int(cursor.rowcount>0)
    return saved


def save_external_feature_observations(symbol: str, timestamp: str, external: dict, quality: str) -> int:
    rows=[];now=pd.Timestamp.now(tz="UTC").isoformat()
    def visit(prefix,value,source):
        if isinstance(value,dict):
            local_source=str(value.get("source") or source)
            for key,item in value.items():
                if key not in {"source","headlines","upcoming","errors","error"}:visit(f"{prefix}.{key}" if prefix else key,item,local_source)
        elif isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(float(value)):
            rows.append((timestamp,symbol,prefix,float(value),str(source or "external public source"),quality,now))
    for group,value in external.items():visit(group,value,value.get("source") if isinstance(value,dict) else None)
    if not rows:return 0
    with connection() as conn:
        conn.executemany("""INSERT OR REPLACE INTO feature_observations
            (feature_timestamp,asset,feature_name,value,source,quality,collected_at) VALUES(?,?,?,?,?,?,?)""",rows)
    return len(rows)


def save_quant_prediction_snapshot(symbol: str, asset_type: str, interval: str, payload: dict) -> str:
    """Append an immutable, replayable prediction snapshot."""
    prediction_id=str(payload.get("prediction_id") or uuid.uuid4())
    cutoff=str(payload.get("data_time") or payload.get("information_cutoff") or "")
    generated=str(payload.get("predicted_at") or payload.get("generated_at") or pd.Timestamp.utcnow().isoformat())
    decision=payload.get("decision_center",{});research=decision.get("research",{})
    market="CRYPTO" if asset_type=="crypto" else "CN" if str(symbol).split(".")[0].isdigit() else "US"
    snapshot_v4={
        "predictionId":prediction_id,"asset":symbol,"market":market,"timestamp":generated,"cutoffTime":cutoff,
        "datasetVersion":research.get("dataset_version") or payload.get("dataset_version") or "LIVE-UNVERSIONED",
        "featureVersion":decision.get("feature_version") or payload.get("feature_version") or "UNKNOWN",
        "modelVersion":str(payload.get("engine_version") or "unknown"),
        "priceSnapshot":{"data_time":payload.get("data_time"),"source":payload.get("data_source")},
        "technicalSnapshot":decision.get("technical_strategy"),"factorSnapshot":research.get("factor_snapshot"),
        "marketRegime":decision.get("market_regime"),"newsSnapshot":research.get("news"),
        "eventSnapshot":research.get("event_risk"),"modelOutputs":payload.get("predictions"),
        "ensembleOutput":payload.get("model"),"uncertainty":research.get("uncertainty"),
        "risk":decision.get("risk_plan"),"finalDecision":decision.get("v5_final_decision") or decision.get("decision")}
    stored={**payload,"prediction_snapshot_v4":snapshot_v4}
    with connection() as conn:
        conn.execute("""INSERT INTO quant_prediction_snapshots
            (prediction_id,symbol,asset_type,interval,data_cutoff,generated_at,model_version,payload_json)
            VALUES(?,?,?,?,?,?,?,?)""",(prediction_id,symbol,asset_type,interval,cutoff,generated,
            str(payload.get("engine_version") or "unknown"),json.dumps(stored,ensure_ascii=False,default=str)))
    return prediction_id


def quant_prediction_snapshots(symbol: str | None=None, limit: int=100) -> list[dict]:
    with connection() as conn:
        if symbol:
            rows=conn.execute("SELECT * FROM quant_prediction_snapshots WHERE symbol=? ORDER BY generated_at DESC LIMIT ?",(symbol,limit)).fetchall()
        else:
            rows=conn.execute("SELECT * FROM quant_prediction_snapshots ORDER BY generated_at DESC LIMIT ?",(limit,)).fetchall()
    return [dict(row) for row in rows]


def save_quant_research_run(result: dict) -> str:
    run_id = str(uuid.uuid4())
    dataset_version = result.get("dataset_audit", {}).get("dataset_version", "unknown")
    generated_at = result.get("generated_at") or pd.Timestamp.now(tz="UTC").isoformat()
    with connection() as conn:
        conn.execute("""INSERT INTO quant_research_runs
            (run_id,market,interval,horizon,dataset_version,status,champion,challenger,generated_at,payload_json)
            VALUES(?,?,?,?,?,?,?,?,?,?)""", (run_id, result["market"], result["interval"], result["horizon"],
            dataset_version, result["decision"], result.get("champion"), result.get("challenger"), generated_at,
            json.dumps(result, ensure_ascii=False)))
        best = result.get("model_tournament", {}).get("best_regressor")
        if best:
            version = conn.execute("SELECT COUNT(*) FROM quant_model_registry WHERE market=? AND horizon=? AND model_name=?",
                                   (result["market"], result["horizon"], best)).fetchone()[0] + 1
            model_id = f"{best.upper()}-{result['market']}-{result['horizon']}-v{version:03d}"
            windows = result.get("walk_forward", {}).get("windows", [])
            period = json.dumps({"first_train": windows[0].get("train") if windows else None,
                                 "last_test": windows[-1].get("test") if windows else None})
            metrics = result.get("model_tournament", {}).get("regression", {}).get(best, {})
            conn.execute("""INSERT INTO quant_model_registry
                (model_id,market,horizon,model_name,model_status,feature_version,dataset_version,training_period,
                 hyperparameters_json,validation_metrics_json,test_metrics_json,trained_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""", (model_id, result["market"], result["horizon"], best,
                "EXPERIMENTAL", "quant-v3-cross-sectional-1", dataset_version, period,
                json.dumps({"selection": "fixed research defaults; no test tuning"}),
                json.dumps({"method": "separate chronological validation"}), json.dumps(metrics), generated_at))
    return run_id


def latest_quant_research_runs() -> dict[str, dict]:
    with connection() as conn:
        rows = conn.execute("""SELECT q.* FROM quant_research_runs q JOIN
            (SELECT market,MAX(generated_at) AS generated_at FROM quant_research_runs GROUP BY market) latest
            ON q.market=latest.market AND q.generated_at=latest.generated_at""").fetchall()
    return {row["market"]: json.loads(row["payload_json"]) for row in rows}


def quant_model_registry(limit: int = 100) -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM quant_model_registry ORDER BY trained_at DESC LIMIT ?", (limit,))]


def save_prediction_history(symbol: str, asset_type: str, interval: str, prediction: dict, decision: dict) -> int:
    saved = 0
    market="CRYPTO" if asset_type=="crypto" else "CN" if str(symbol).split(".")[0].isdigit() else "US"
    exchange="OKX" if market=="CRYPTO" else "SSE" if str(symbol).endswith(".SH") else "SZSE" if market=="CN" else "US"
    with connection() as conn:
        for horizon, item in prediction["predictions"].items():
            if not item.get("prediction"): continue
            probs = item["probabilities"]
            research=decision.get("research",{});quality=research.get("data_quality",{}).get("score")
            rr=decision.get("risk_reward",{}).get("tp2");ev=decision.get("expected_value",{}).get("percent")
            technical=decision.get("technical_strategy",{});technical_risk=technical.get("risk_plan",{})
            technical_targets=technical_risk.get("take_profits",[])
            tp2=technical_targets[1].get("price") if len(technical_targets)>1 else None
            cursor = conn.execute(
                """INSERT OR IGNORE INTO prediction_history(
                   symbol,asset_type,interval,horizon,prediction_time,target_time,entry_price,prediction,
                   prob_down,prob_flat,prob_up,threshold,regime,decision,stop_loss,tp1,payload_json,
                   prediction_id,model_version,feature_version,risk_reward,expected_value,data_quality,status,
                   strategy_version,tp2,probability_calibration,market,exchange,settlement_status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (symbol, asset_type, interval, horizon, item["prediction_time"], item["future_timestamp"],
                 decision["support_resistance"]["current_price"], item["prediction"], probs["down"], probs["flat"], probs["up"],
                 item["threshold_percent"] / 100, decision["market_regime"]["primary"], decision["decision"]["action"],
                 decision["risk_plan"]["stop_loss"], decision["take_profits"][0]["price"], json.dumps({"prediction":item,"decision":decision}, ensure_ascii=False),
                 str(uuid.uuid4()),prediction.get("engine_version"),decision.get("feature_version"),rr,ev,quality,"ACTIVE",
                 technical.get("engine_version"),tp2,"PLATT_SCALING",market,exchange,"PENDING"))
            saved += int(cursor.rowcount > 0)
    return saved


def resolve_prediction_history(symbol: str, candles: list[dict]) -> int:
    if not candles: return 0
    frame = pd.DataFrame(candles).sort_values("timestamp")
    timestamps = pd.to_datetime(frame["timestamp"])
    if timestamps.dt.tz is None: timestamps = timestamps.dt.tz_localize("Asia/Shanghai")
    timestamps = timestamps.dt.tz_convert("UTC")
    latest = timestamps.iloc[-1]; resolved = 0
    with connection() as conn:
        rows = conn.execute("SELECT * FROM prediction_history WHERE symbol=? AND actual IS NULL", (symbol,)).fetchall()
        for row in rows:
            target = pd.Timestamp(row["target_time"])
            if target.tzinfo is None: target = target.tz_localize("UTC")
            if target > latest: continue
            eligible = np.flatnonzero((timestamps >= target).to_numpy())
            if not len(eligible): continue
            end = int(eligible[0]); start_candidates = np.flatnonzero((timestamps >= pd.Timestamp(row["prediction_time"])).to_numpy())
            start = int(start_candidates[0]) if len(start_candidates) else max(0, end-1)
            exit_price = float(frame["close"].iloc[end]); actual_return = exit_price / row["entry_price"] - 1
            threshold = float(row["threshold"]); actual = "UP" if actual_return > threshold else "DOWN" if actual_return < -threshold else "FLAT"
            path = frame.iloc[min(start+1,end):end+1]
            side = "LONG" if row["prediction"] == "UP" else "SHORT" if row["prediction"] == "DOWN" else "FLAT"
            if side=="FLAT":
                stop_hit=False;tp_hit=False;realized_r=0.0;mae=float(path["low"].min()/row["entry_price"]-1);mfe=float(path["high"].max()/row["entry_price"]-1)
            else:
                stop_hit = bool(path["low"].min() <= row["stop_loss"]) if side == "LONG" else bool(path["high"].max() >= row["stop_loss"])
                tp_hit = bool(path["high"].max() >= row["tp1"]) if side == "LONG" else bool(path["low"].min() <= row["tp1"])
                risk = abs(row["entry_price"]-row["stop_loss"]); pnl = (exit_price-row["entry_price"]) * (1 if side=="LONG" else -1)
                realized_r = pnl/max(risk,1e-12)
                mae=float(path["low"].min()/row["entry_price"]-1) if side=="LONG" else float(row["entry_price"]/path["high"].max()-1)
                mfe=float(path["high"].max()/row["entry_price"]-1) if side=="LONG" else float(row["entry_price"]/path["low"].min()-1)
            correct=int(actual==row["prediction"]);failure=None
            if not correct:
                confidence=max(float(row["prob_down"]),float(row["prob_flat"]),float(row["prob_up"]))
                if row["data_quality"] is not None and float(row["data_quality"]) < .6:
                    failure="DATA_QUALITY"
                elif confidence >= .65:
                    failure="OVERCONFIDENCE"
                elif row["prediction"]=="FLAT":
                    failure="MAGNITUDE_ERROR"
                elif abs(actual_return) > max(threshold*2,.02):
                    failure="VOLATILITY_SPIKE"
                else:
                    failure="WRONG_DIRECTION"
            conn.execute("""UPDATE prediction_history SET actual=?,actual_return=?,correct=?,stop_hit=?,tp_hit=?,realized_r=?,
                         mae=?,mfe=?,failure_reason=?,status='RESOLVED',expired_at=CURRENT_TIMESTAMP,resolved_at=CURRENT_TIMESTAMP WHERE id=?""",
                         (actual, actual_return, correct, int(stop_hit), int(tp_hit), realized_r,mae,mfe,failure,row["id"]))
            resolved += 1
    return resolved


def prediction_history(limit: int = 100) -> list[dict]:
    with connection() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM prediction_history ORDER BY id DESC LIMIT ?", (limit,))]


def prediction_statistics() -> dict:
    rows = [row for row in prediction_history(10000) if row["actual"]]
    def metrics(items):
        if not items: return {"samples":0,"status":"NO_DATA"}
        labels={"DOWN":0,"FLAT":1,"UP":2}; y=np.array([labels[x["actual"]] for x in items]); pred=np.array([labels[x["prediction"]] for x in items])
        probs=np.array([[x["prob_down"],x["prob_flat"],x["prob_up"]] for x in items]); chosen=range(3)
        precision=[];recall=[];f1=[]
        for cls in chosen:
            tp=((pred==cls)&(y==cls)).sum(); fp=((pred==cls)&(y!=cls)).sum(); fn=((pred!=cls)&(y==cls)).sum()
            p=tp/max(tp+fp,1);r=tp/max(tp+fn,1);precision.append(p);recall.append(r);f1.append(2*p*r/max(p+r,1e-12))
        one=np.eye(3)[y]; brier=float(np.mean(np.sum((probs-one)**2,axis=1))); loss=float(-np.mean(np.log(np.clip(probs[np.arange(len(y)),y],1e-12,1))))
        rs=[x["realized_r"] for x in items if x["realized_r"] is not None]; wins=sum(v for v in rs if v>0); losses=abs(sum(v for v in rs if v<0))
        actual_returns=np.asarray([float(x["actual_return"]) for x in items],float)
        score=probs[:,2]-probs[:,0]
        ic=float(np.corrcoef(score,actual_returns)[0,1]) if len(items)>2 and np.std(score)>0 and np.std(actual_returns)>0 else None
        rank_score=pd.Series(score).rank().to_numpy();rank_return=pd.Series(actual_returns).rank().to_numpy()
        rank_ic=float(np.corrcoef(rank_score,rank_return)[0,1]) if len(items)>2 and np.std(rank_score)>0 and np.std(rank_return)>0 else None
        r_values=np.asarray(rs,float);r_std=float(r_values.std(ddof=1)) if len(r_values)>1 else 0
        sharpe=float(np.sqrt(252)*r_values.mean()/r_std) if r_std>0 else None
        confidence=probs.max(axis=1);correct=(pred==y).astype(float);ece=0.0;reliability=[]
        for lower in np.linspace(0,1,11)[:-1]:
            upper=lower+.1;mask=(confidence>=lower)&(confidence<(upper if upper<1 else upper+1e-12))
            if not mask.any():continue
            predicted_conf=float(confidence[mask].mean());observed=float(correct[mask].mean());ece+=float(mask.mean())*abs(predicted_conf-observed)
            reliability.append({"lower":round(float(lower),1),"upper":round(float(upper),1),"samples":int(mask.sum()),"predicted":round(predicted_conf,4),"observed":round(observed,4)})
        return {"samples":len(items),"accuracy":round(float((pred==y).mean()),4),"precision_macro":round(float(np.mean(precision)),4),
                "recall_macro":round(float(np.mean(recall)),4),"f1_macro":round(float(np.mean(f1)),4),"brier_score":round(brier,4),"log_loss":round(loss,4),
                "calibration_gap":round(float(np.mean(abs(probs.max(axis=1)-(pred==y)))),4),"ece":round(ece,4),"reliability":reliability,
                "stop_hit_rate":round(sum(x["stop_hit"] for x in items)/len(items),4),"tp_hit_rate":round(sum(x["tp_hit"] for x in items)/len(items),4),
                "average_r":round(float(np.mean(rs)),4) if rs else None,"profit_factor":round(wins/losses,4) if losses else None,
                "ic":None if ic is None else round(ic,4),"rank_ic":None if rank_ic is None else round(rank_ic,4),
                "icir":None,"sharpe":None if sharpe is None else round(sharpe,4)}

    horizons=sorted({x["horizon"] for x in rows})
    by_horizon={h:metrics([x for x in rows if x["horizon"]==h]) for h in horizons}
    regimes=sorted({x["regime"] for x in rows if x["regime"]})
    return {"overall":metrics(rows),"by_horizon":by_horizon,"by_regime":{r:metrics([x for x in rows if x["regime"]==r]) for r in regimes}}


def save_market_intelligence_snapshot(snapshot: dict) -> str:
    """Append an immutable intelligence snapshot; historical failures stay intact."""
    snapshot_id=str(snapshot.get("snapshot_id") or uuid.uuid4())
    with connection() as conn:
        conn.execute("""INSERT INTO market_intelligence_snapshots
            (snapshot_id,symbol,asset_type,model_version,data_cutoff,generated_at,trigger_reason,payload_json)
            VALUES(?,?,?,?,?,?,?,?)""",(snapshot_id,snapshot["symbol"],snapshot["asset_type"],snapshot.get("model_version"),
            snapshot["data_cutoff"],snapshot["generated_at"],snapshot.get("trigger_reason","manual"),
            json.dumps({**snapshot,"snapshot_id":snapshot_id},ensure_ascii=False)))
    return snapshot_id


def market_intelligence_snapshots(symbol: str, asset_type: str, limit: int = 20) -> list[dict]:
    with connection() as conn:
        rows=conn.execute("""SELECT payload_json FROM market_intelligence_snapshots
            WHERE symbol=? AND asset_type=? ORDER BY generated_at DESC LIMIT ?""",(symbol,asset_type,limit)).fetchall()
    return [json.loads(row["payload_json"]) for row in rows]
