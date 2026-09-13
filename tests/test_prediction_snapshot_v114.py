import json

from backend import database


def test_snapshot_v4_is_complete_and_immutable(monkeypatch,tmp_path):
    monkeypatch.setattr(database,"DB_PATH",tmp_path/"db.sqlite3");database.init_db()
    payload={"prediction_id":"p1","data_time":"2026-01-01T00:00:00Z","engine_version":"v4","predictions":{},"decision_center":{}}
    assert database.save_quant_prediction_snapshot("NVDA","stock","1d",payload)=="p1"
    with database.connection() as conn:stored=json.loads(conn.execute("SELECT payload_json FROM quant_prediction_snapshots WHERE prediction_id='p1'").fetchone()[0])
    required={"predictionId","asset","market","timestamp","cutoffTime","datasetVersion","featureVersion","modelVersion","priceSnapshot","technicalSnapshot","factorSnapshot","marketRegime","newsSnapshot","eventSnapshot","modelOutputs","ensembleOutput","uncertainty","risk","finalDecision"}
    assert required<=set(stored["prediction_snapshot_v4"])
