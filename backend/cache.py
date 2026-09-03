from __future__ import annotations

import time
from threading import RLock
from typing import Any


class TTLCache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = RLock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._items.get(key)
            if not item:
                return None
            expires, value = item
            if expires <= time.monotonic():
                self._items.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl: int) -> Any:
        with self._lock:
            self._items[key] = (time.monotonic() + ttl, value)
        return value


cache = TTLCache()

