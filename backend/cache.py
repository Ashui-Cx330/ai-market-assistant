from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from threading import RLock
from typing import Any


class TTLCache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = RLock()
        data_root = Path(os.environ.get("TRADING_AI_DATA_DIR") or Path.home() / ".ai-market-assistant")
        self._path = data_root / "cache" / "market-cache.sqlite3"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, expires REAL NOT NULL, value TEXT NOT NULL)")
            connection.commit()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._items.get(key)
            if item:
                expires, value = item
                if expires > time.monotonic():
                    return value
                self._items.pop(key, None)
            now = time.time()
            # The cache is disposable. Tests, cleanup tools, or users may remove
            # it while the process is alive; recreate it instead of breaking
            # market/search requests with "unable to open database file".
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists():
                with closing(sqlite3.connect(self._path)) as connection:
                    connection.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, expires REAL NOT NULL, value TEXT NOT NULL)")
                    connection.commit()
            with closing(sqlite3.connect(self._path)) as connection:
                row = connection.execute("SELECT expires,value FROM cache WHERE key=?", (key,)).fetchone()
                if not row:
                    return None
                if row[0] <= now:
                    connection.execute("DELETE FROM cache WHERE key=?", (key,))
                    return None
                try:
                    return json.loads(row[1])
                except (TypeError, json.JSONDecodeError):
                    connection.execute("DELETE FROM cache WHERE key=?", (key,))
                    return None

    def set(self, key: str, value: Any, ttl: int) -> Any:
        with self._lock:
            self._items[key] = (time.monotonic() + ttl, value)
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                with closing(sqlite3.connect(self._path)) as connection:
                    connection.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, expires REAL NOT NULL, value TEXT NOT NULL)")
                    connection.execute("INSERT INTO cache(key,expires,value) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET expires=excluded.expires,value=excluded.value",
                                       (key, time.time() + ttl, encoded))
                    connection.commit()
            except (TypeError, ValueError):
                pass
        return value


cache = TTLCache()
