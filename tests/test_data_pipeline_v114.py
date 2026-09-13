from backend import database
from backend.data_pipeline_v4 import data_hash, persist_universe, store_incremental, validate_candles


def _rows():
    return [{"timestamp":f"2026-01-0{i}T00:00:00Z","open":10+i,"high":12+i,"low":9+i,"close":11+i,"volume":100} for i in range(1,4)]


def test_ohlc_validation_rejects_bad_data():
    rows=_rows();rows[1]["high"]=1
    result=validate_candles(rows)
    assert result["status"]=="FAILED" and result["errors"][0]["code"]=="BAD_OHLC"


def test_incremental_is_idempotent_and_hashes(monkeypatch,tmp_path):
    monkeypatch.setattr(database,"DB_PATH",tmp_path/"db.sqlite3");database.init_db()
    first=store_incremental("BTC","crypto","1d",_rows(),"unit")
    second=store_incremental("BTC","crypto","1d",_rows(),"unit")
    assert first["inserted"]==3 and second["inserted"]==0 and len(data_hash())==64


def test_universe_version_is_deterministic(monkeypatch,tmp_path):
    monkeypatch.setattr(database,"DB_PATH",tmp_path/"db.sqlite3");database.init_db()
    members=[{"symbol":"BTC"},{"symbol":"ETH"}]
    one=persist_universe("CRYPTO",members,"unit","2026-01-01")
    two=persist_universe("CRYPTO",members,"unit","2026-01-01")
    assert one["universeVersion"]==two["universeVersion"] and one["memberCount"]==2
