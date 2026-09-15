from __future__ import annotations

import sqlite3
import time

from backend.cache import TTLCache


def test_cache_startup_removes_expired_rows_and_caps_growth(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_AI_DATA_DIR", str(tmp_path))
    cache_path = tmp_path / "cache" / "market-cache.sqlite3"
    cache_path.parent.mkdir(parents=True)
    with sqlite3.connect(cache_path) as connection:
        connection.execute("CREATE TABLE cache (key TEXT PRIMARY KEY, expires REAL NOT NULL, value TEXT NOT NULL)")
        connection.executemany(
            "INSERT INTO cache VALUES(?,?,?)",
            [(f"expired-{index}", time.time() - 1, "{}") for index in range(150)]
            + [(f"live-{index}", time.time() + 3600 + index, "{}") for index in range(140)],
        )
    instance = TTLCache()
    with sqlite3.connect(instance._path) as connection:
        rows = connection.execute("SELECT key,expires FROM cache").fetchall()
    assert len(rows) == instance.MAX_DISK_ITEMS
    assert all(expires > time.time() for _, expires in rows)


def test_cache_set_prunes_expired_memory_and_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("TRADING_AI_DATA_DIR", str(tmp_path))
    instance = TTLCache()
    instance._items["expired"] = (time.monotonic() - 1, {"old": True})
    instance.set("fresh", {"value": 1}, 60)
    assert "expired" not in instance._items
    assert instance.get("fresh") == {"value": 1}
