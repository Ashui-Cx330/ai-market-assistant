import asyncio

from backend import database, main
from backend.market import canonical_symbol, normalize_stock_symbol


def test_symbol_resolver_normalizes_us_and_a_share():
    assert normalize_stock_symbol("NASDAQ:NVDA") == "NVDA"
    assert normalize_stock_symbol("SH600519") == "600519"
    assert normalize_stock_symbol("600519.SH") == "600519"
    assert canonical_symbol("600519", "stock") == "600519.SH"
    assert canonical_symbol("BTC-USDT", "crypto") == "BTC"


def test_market_buy_partial_sell_and_account_values(tmp_path, monkeypatch):
    monkeypatch.setattr(database,"DB_PATH",tmp_path/"paper.sqlite3");database.init_db()
    buy=database.execute_paper_order("NVDA","NVIDIA","stock","BUY",100,10,.0003)
    assert buy["status"]=="filled"
    snap=database.paper_snapshot();assert snap["positions"][0]["quantity"]==10
    assert snap["accounts"][1]["currency"]=="USD" or any(a["currency"]=="USD" and a["cash"]<100000 for a in snap["accounts"])
    database.execute_paper_order("NVDA","NVIDIA","stock","SELL",105,4,.0003)
    assert database.paper_snapshot()["positions"][0]["quantity"]==6


def test_limit_order_freeze_fill_cancel_and_reset(tmp_path, monkeypatch):
    monkeypatch.setattr(database,"DB_PATH",tmp_path/"limits.sqlite3");database.init_db()
    pending=database.create_limit_order("NVDA","NVIDIA","stock","BUY",90,10,.0003)
    snap=database.paper_snapshot();usd=next(a for a in snap["accounts"] if a["currency"]=="USD")
    assert pending["status"]=="pending" and usd["frozen_cash"]>900
    assert database.fill_limit_order(pending["id"],95,.0003) is None
    filled=database.fill_limit_order(pending["id"],89,.0003);assert filled["status"]=="filled"
    sell=database.create_limit_order("NVDA","NVIDIA","stock","SELL",110,4,.0003)
    assert database.paper_snapshot()["positions"][0]["frozen_quantity"]==4
    cancelled=database.cancel_paper_order(sell["id"]);assert cancelled["status"]=="cancelled"
    assert database.paper_snapshot()["positions"][0]["frozen_quantity"]==0
    database.reset_paper_accounts();snap=database.paper_snapshot()
    assert not snap["positions"] and not snap["orders"] and all(a["cash"]==a["initial_cash"] for a in snap["accounts"])


def test_daily_equity_baseline_and_a_share_currency(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADING_AI_DATA_DIR", raising=False)
    monkeypatch.setattr(database,"DB_PATH",tmp_path/"daily.sqlite3");database.init_db()
    assert database.paper_daily_pnl("USD",100000,"2026-09-08")==0
    assert database.paper_daily_pnl("USD",100125.5,"2026-09-08")==125.5
    order=database.execute_paper_order("600519.SH","贵州茅台","stock","BUY",100,1,.0003)
    assert order["currency"]=="CNY"


def test_marked_snapshot_returns_one_consistent_account_view(tmp_path, monkeypatch):
    monkeypatch.delenv("TRADING_AI_DATA_DIR", raising=False)
    monkeypatch.setattr(database,"DB_PATH",tmp_path/"snapshot.sqlite3")
    monkeypatch.setattr(main,"DB_PATH",database.DB_PATH)
    database.init_db()
    snapshot=asyncio.run(main._marked_snapshot())
    assert len(snapshot["accounts"])==3
    assert all(a["today_pnl"]==0 and a["total_equity"]==100000 for a in snapshot["accounts"])


def test_runtime_desktop_data_dir_wins_over_import_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", database._IMPORT_DB_PATH)
    monkeypatch.setenv("TRADING_AI_DATA_DIR", str(tmp_path))
    expected = tmp_path / "database" / "trading_ai.db"
    assert database.database_path() == expected
    database.init_db()
    assert expected.exists()
