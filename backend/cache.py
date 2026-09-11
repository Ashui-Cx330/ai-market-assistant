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
        # Disk cache is disposable and must never stall the API event loop when
        # a background refresh is writing. The lock above protects memory only.
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists():
                with closing(sqlite3.connect(self._path,timeout=.2)) as connection:
                    connection.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, expires REAL NOT NULL, value TEXT NOT NULL)")
                    connection.commit()
            with closing(sqlite3.connect(self._path,timeout=.2)) as connection:
                row = connection.execute("SELECT expires,value FROM cache WHERE key=?", (key,)).fetchone()
                if not row:
                    return None
                if row[0] <= now:
                    return None
                try:
                    value=json.loads(row[1])
                    with self._lock:
                        self._items[key]=(time.monotonic()+max(0,row[0]-now),value)
                    return value
                except (TypeError, json.JSONDecodeError):
                    return None
        except sqlite3.Error:
            return None

    def get_stale(self, key: str) -> Any | None:
        """Return the last persisted value even after its freshness TTL elapsed.

        Market screens use this for stale-while-revalidate rendering: an expired
        observed value is labelled as stale and shown immediately while a
        background task asks the external provider for a newer observation.
        """
        with self._lock:
            item = self._items.get(key)
            if item:
                return item[1]
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if not self._path.exists(): return None
            with closing(sqlite3.connect(self._path,timeout=.2)) as connection:
                row = connection.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
                if not row:
                    return None
                try:
                    value=json.loads(row[0])
                    with self._lock:
                        # Stale memory values remain addressable only through
                        # get_stale; a normal get still checks this timestamp.
                        self._items[key]=(time.monotonic()-1,value)
                    return value
                except (TypeError, json.JSONDecodeError):
                    return None
        except sqlite3.Error:
            return None

    def set(self, key: str, value: Any, ttl: int) -> Any:
        with self._lock:
            self._items[key] = (time.monotonic() + ttl, value)
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            with closing(sqlite3.connect(self._path,timeout=.2)) as connection:
                connection.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, expires REAL NOT NULL, value TEXT NOT NULL)")
                connection.execute("INSERT INTO cache(key,expires,value) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET expires=excluded.expires,value=excluded.value",
                                   (key, time.time() + ttl, encoded))
                connection.commit()
        except (TypeError, ValueError, sqlite3.Error):
            pass
        return value


cache = TTLCache()
