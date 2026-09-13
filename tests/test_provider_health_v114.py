from datetime import datetime, timedelta, timezone

from backend import database


def test_old_healthy_provider_is_stale(monkeypatch,tmp_path):
    monkeypatch.setattr(database,"DB_PATH",tmp_path/"db.sqlite3");database.init_db()
    old=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    with database.connection() as conn:
        conn.execute("INSERT INTO provider_health_events(provider,status,last_successful_fetch,last_check,payload_json) VALUES(?,?,?,?,?)",("p","CONNECTED",old,old,"{}"))
    item=database.provider_health_snapshot(3600)[0]
    assert item["status"]=="STALE" and item["freshness_seconds"]>=7200
