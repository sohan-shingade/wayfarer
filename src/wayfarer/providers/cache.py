"""Provider response cache.

Two implementations behind one tiny get/set interface:

- `TTLCache`: in-process dict (original; used by tests, no persistence).
- `SqliteCache`: persisted to disk so repeated runs of the SAME scenario reuse
  provider responses within the TTL instead of re-hitting rate-limited / metered
  vendors. This is what makes a re-run of an identical request idempotent at the
  data layer (same cached flights + hotels -> same numbers). Values are stored as
  JSON (not pickle): callers cache only JSON-native data (lists/dicts), so loading
  the local DB can never execute code.

`get_cache()` returns a process-wide SqliteCache by default; set
WAYFARER_CACHE=off for the in-memory cache (e.g. to force fresh data).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any


class TTLCache:
    def __init__(self, ttl_s: int) -> None:
        self.ttl_s = ttl_s
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        hit = self._store.get(key)
        if not hit:
            return None
        ts, val = hit
        if time.time() - ts > self.ttl_s:
            self._store.pop(key, None)
            return None
        return val

    def set(self, key: str, val: Any) -> None:
        self._store[key] = (time.time(), val)


class SqliteCache:
    def __init__(self, ttl_s: int, path: str | os.PathLike[str]) -> None:
        self.ttl_s = ttl_s
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path))
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, ts REAL, v TEXT)"
        )
        self._db.commit()

    def get(self, key: str) -> Any | None:
        row = self._db.execute("SELECT ts, v FROM cache WHERE k = ?", (key,)).fetchone()
        if not row:
            return None
        ts, blob = row
        if time.time() - ts > self.ttl_s:
            self._db.execute("DELETE FROM cache WHERE k = ?", (key,))
            self._db.commit()
            return None
        try:
            return json.loads(blob)
        except Exception:  # noqa: BLE001  corrupt entry -> treat as miss
            return None

    def set(self, key: str, val: Any) -> None:
        # JSON only -- callers cache JSON-native values (no pickle, no code exec).
        self._db.execute(
            "INSERT OR REPLACE INTO cache (k, ts, v) VALUES (?, ?, ?)",
            (key, time.time(), json.dumps(val)),
        )
        self._db.commit()


_DEFAULT_PATH = Path(
    os.environ.get("WAYFARER_CACHE_DIR", Path.home() / ".cache" / "wayfarer")
) / "providers.db"

_shared: TTLCache | SqliteCache | None = None


def get_cache(ttl_s: int) -> TTLCache | SqliteCache:
    """Process-wide provider cache. Persistent unless WAYFARER_CACHE=off."""
    global _shared
    if _shared is not None:
        return _shared
    if os.environ.get("WAYFARER_CACHE", "").lower() == "off":
        _shared = TTLCache(ttl_s)
        return _shared
    try:
        _shared = SqliteCache(ttl_s, _DEFAULT_PATH)
    except Exception:  # noqa: BLE001  fall back to memory if disk unwritable
        _shared = TTLCache(ttl_s)
    return _shared
