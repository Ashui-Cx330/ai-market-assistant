import sqlite3
import os
import json
import math
import numpy as np
import pandas as pd
import uuid
from contextlib import contextmanager
from pathlib import Path

data_root = os.environ.get("TRADING_AI_DATA_DIR")
if data_root:
    DB_PATH = Path(data_root) / "database" / "trading_ai.db"
else:
    DB_PATH = Path(__file__).resolve().parent.parent / "trading_ai.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
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
            );"""
        )
        prediction_columns={row[1] for row in conn.execute("PRAGMA table_info(prediction_history)")}
        migrations={"prediction_id":"TEXT","model_version":"TEXT","feature_version":"TEXT","risk_reward":"REAL",
                    "expected_value":"REAL","data_quality":"REAL","status":"TEXT DEFAULT 'ACTIVE'",
                    "mae":"REAL","mfe":"REAL","expired_at":"TEXT","invalidation_reason":"TEXT"}
        for name,sql_type in migrations.items():
            if name not in prediction_columns:conn.execute(f"ALTER TABLE prediction_history ADD COLUMN {name} {sql_type}")
        conn.executemany("INSERT OR IGNORE INTO paper_accounts(currency,cash,initial_cash) VALUES(?,?,?)",
                         [("USDT",100000.0,100000.0),("CNY",100000.0,100000.0)])
        count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
        if count == 0:
            conn.executemany(
                "INSERT INTO watchlist(symbol, asset_type) VALUES (?, ?)",
                [("600519", "stock"), ("300750", "stock"), ("BTC", "crypto"), ("ETH", "crypto")],
            )


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


def execute_paper_order(symbol: str, name: str, asset_type: str, side: str, price: float, quantity: float, fee_rate: float) -> dict:
    currency="USDT" if asset_type=="crypto" else "CNY";side=side.upper();amount=price*quantity;fee=amount*fee_rate
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
            if not position or position["quantity"]+1e-12<quantity:raise ValueError("模拟持仓数量不足")
            conn.execute("UPDATE paper_accounts SET cash=cash+? WHERE currency=?",(amount-fee,currency))
            conn.execute("UPDATE paper_positions SET quantity=quantity-?,updated_at=CURRENT_TIMESTAMP WHERE symbol=? AND asset_type=?",(quantity,symbol,asset_type))
        else:raise ValueError("side 必须是 BUY 或 SELL")
        cur=conn.execute("INSERT INTO paper_orders(symbol,name,asset_type,side,price,quantity,fee,amount,currency) VALUES(?,?,?,?,?,?,?,?,?)",(symbol,name,asset_type,side,price,quantity,fee,amount,currency))
        return dict(conn.execute("SELECT * FROM paper_orders WHERE id=?",(cur.lastrowid,)).fetchone())


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


def save_prediction_history(symbol: str, asset_type: str, interval: str, prediction: dict, decision: dict) -> int:
    saved = 0
    with connection() as conn:
        for horizon, item in prediction["predictions"].items():
            if not item.get("prediction"): continue
            probs = item["probabilities"]
            research=decision.get("research",{});quality=research.get("data_quality",{}).get("score")
            rr=decision.get("risk_reward",{}).get("tp2");ev=decision.get("expected_value",{}).get("percent")
            cursor = conn.execute(
                """INSERT OR IGNORE INTO prediction_history(
                   symbol,asset_type,interval,horizon,prediction_time,target_time,entry_price,prediction,
                   prob_down,prob_flat,prob_up,threshold,regime,decision,stop_loss,tp1,payload_json,
                   prediction_id,model_version,feature_version,risk_reward,expected_value,data_quality,status)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (symbol, asset_type, interval, horizon, item["prediction_time"], item["future_timestamp"],
                 decision["support_resistance"]["current_price"], item["prediction"], probs["down"], probs["flat"], probs["up"],
                 item["threshold_percent"] / 100, decision["market_regime"]["primary"], decision["decision"]["action"],
                 decision["risk_plan"]["stop_loss"], decision["take_profits"][0]["price"], json.dumps({"prediction":item,"decision":decision}, ensure_ascii=False),
                 str(uuid.uuid4()),prediction.get("engine_version"),decision.get("feature_version"),rr,ev,quality,"ACTIVE"))
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
            conn.execute("""UPDATE prediction_history SET actual=?,actual_return=?,correct=?,stop_hit=?,tp_hit=?,realized_r=?,
                         mae=?,mfe=?,status='RESOLVED',expired_at=CURRENT_TIMESTAMP,resolved_at=CURRENT_TIMESTAMP WHERE id=?""",
                         (actual, actual_return, int(actual==row["prediction"]), int(stop_hit), int(tp_hit), realized_r,mae,mfe,row["id"]))
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
        return {"samples":len(items),"accuracy":round(float((pred==y).mean()),4),"precision_macro":round(float(np.mean(precision)),4),
                "recall_macro":round(float(np.mean(recall)),4),"f1_macro":round(float(np.mean(f1)),4),"brier_score":round(brier,4),"log_loss":round(loss,4),
                "calibration_gap":round(float(np.mean(abs(probs.max(axis=1)-(pred==y)))),4),
                "stop_hit_rate":round(sum(x["stop_hit"] for x in items)/len(items),4),"tp_hit_rate":round(sum(x["tp_hit"] for x in items)/len(items),4),
                "average_r":round(float(np.mean(rs)),4) if rs else None,"profit_factor":round(wins/losses,4) if losses else None}
    by_horizon={h:metrics([x for x in rows if x["horizon"]==h]) for h in ("1H","4H","1D")}
    regimes=sorted({x["regime"] for x in rows if x["regime"]})
    return {"overall":metrics(rows),"by_horizon":by_horizon,"by_regime":{r:metrics([x for x in rows if x["regime"]==r]) for r in regimes}}
