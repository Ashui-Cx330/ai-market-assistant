import sqlite3
import os
import json
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
            );"""
        )
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
