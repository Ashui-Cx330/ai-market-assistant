from datetime import datetime, timedelta, timezone

import backend.database as database
import pandas as pd
from backend.settlement import PredictionSettlementEngine, TradingCalendar, persist_result
from backend.symbol_master import resolve
from backend.horizons import future_timestamp


def bars(start: datetime, count: int, hours: int = 24):
    return [{"timestamp": (start + timedelta(hours=index * hours)).isoformat(),
             "open": 100 + index, "high": 102 + index, "low": 99 + index,
             "close": 101 + index, "volume": 1000} for index in range(count)]


def prediction(symbol="NVDA", asset_type="stock", horizon="1D", interval="1d"):
    return {"id": 1, "symbol": symbol, "asset_type": asset_type, "interval": interval,
            "horizon": horizon, "prediction_time": "2026-09-04T20:00:00+00:00",
            "entry_price": 100, "prediction": "UP", "threshold": .005,
            "stop_loss": 95, "tp1": 110}


def test_symbol_master_normalizes_all_required_aliases(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_AI_DATA_DIR", str(tmp_path))
    database.DB_PATH = tmp_path / "database" / "trading_ai.db"; database.init_db()
    assert resolve("600000.SS", "stock").canonical_symbol == "600000.SH"
    assert resolve("NASDAQ:NVDA", "stock").canonical_symbol == "NVDA"
    assert resolve("BTCUSDT", "crypto").canonical_symbol == "BTC"
    assert resolve("BTC/USDT", "crypto").session == "24x7"
    assert resolve("NVDA", "stock").timezone == "America/New_York"
    us=future_timestamp(pd.Timestamp("2026-01-02T21:00:00Z"),"stock","1d","1D","US")
    assert us.tz_convert("America/New_York").date().isoformat()=="2026-01-05"


def test_us_daily_settlement_uses_next_observed_session_not_plus_24h(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_AI_DATA_DIR", str(tmp_path))
    database.DB_PATH = tmp_path / "database" / "trading_ai.db"; database.init_db()
    # Friday prediction; supplied bars are Monday, Tuesday, Wednesday.
    rows = bars(datetime(2026, 9, 7, 20, tzinfo=timezone.utc), 3)
    result = PredictionSettlementEngine().settle(prediction(), rows, "fixture")
    assert result.status == "SETTLED"
    assert result.settlement_timestamp.startswith("2026-09-07")


def test_cn_t5_and_crypto_horizons_are_distinct(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_AI_DATA_DIR", str(tmp_path))
    database.DB_PATH = tmp_path / "database" / "trading_ai.db"; database.init_db()
    daily = bars(datetime(2026, 9, 5, tzinfo=timezone.utc), 8)
    cn = prediction("600000", "stock", "T+5", "1d")
    assert PredictionSettlementEngine().settle(cn, daily).settlement_timestamp.startswith("2026-09-09")
    hourly = bars(datetime(2026, 9, 4, 21, tzinfo=timezone.utc), 10, 1)
    crypto = prediction("BTC-USDT", "crypto", "4H", "1h")
    assert PredictionSettlementEngine().settle(crypto, hourly).settlement_timestamp.startswith("2026-09-05T00:00")


def test_settlement_persistence_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_AI_DATA_DIR", str(tmp_path))
    database.DB_PATH = tmp_path / "database" / "trading_ai.db"; database.init_db()
    with database.connection() as conn:
        conn.execute("""INSERT INTO prediction_history(id,symbol,asset_type,interval,horizon,prediction_time,
            target_time,entry_price,prediction,prob_down,prob_flat,prob_up,threshold,payload_json)
            VALUES(1,'NVDA','stock','1d','1D','2026-09-04T20:00:00+00:00','2026-09-07T20:00:00+00:00',
            100,'UP',.2,.2,.6,.005,'{}')""")
    row = prediction(); result = PredictionSettlementEngine().settle(
        row, bars(datetime(2026, 9, 7, 20, tzinfo=timezone.utc), 3))
    assert persist_result(row, result) is True
    assert persist_result(row, result) is False
    with database.connection() as conn:
        saved = conn.execute("SELECT actual,settlement_status FROM prediction_history WHERE id=1").fetchone()
    assert saved[0] == "UP" and saved[1] == "SETTLED"
