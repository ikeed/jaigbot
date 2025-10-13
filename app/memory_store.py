"""
Memory store abstractions for session state.

This module provides two implementations:
- InMemoryStore: simple process-local dictionary (suitable for local dev only)
- RedisStore: backed by Redis / Google Memorystore with TTL and namespaced keys

These classes are intentionally decoupled from environment variables; pass
configuration values via the constructor in app.main.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple


class InMemoryStore:
    """Simple process-local store used for local development/testing.

    Implements a minimal dict-like interface that the app expects.
    """

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._store.get(key)

    def __getitem__(self, key: str) -> Dict[str, Any]:
        return self._store[key]

    def __setitem__(self, key: str, value: Dict[str, Any]) -> None:
        self._store[key] = value

    def __contains__(self, key: str) -> bool:  # pragma: no cover - trivial
        return key in self._store

    def items(self) -> List[Tuple[str, Dict[str, Any]]]:
        return list(self._store.items())

    def pop(self, key: str, default: Any = None) -> Any:
        return self._store.pop(key, default)

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._store)


class RedisStore:
    """Redis-backed store with TTL and key prefix.

    Parameters
    - url: full redis URL, if provided (takes precedence over host/port/db/password)
    - host, port, db, password: standard Redis connection fields
    - prefix: string prefix for namespacing keys
    - ttl: expiration in seconds; if > 0, applied on write
    """

    def __init__(
        self,
        *,
        url: Optional[str] = None,
        host: Optional[str] = None,
        port: int = 6379,
        db: int = 0,
        password: Optional[str] = None,
        prefix: str = "jaig:session:",
        ttl: int = 3600,
    ) -> None:
        try:
            import redis  # type: ignore
        except Exception as e:  # pragma: no cover - import error path
            raise RuntimeError(f"Redis library not available: {e}")

        self._prefix = prefix
        self._ttl = ttl

        if url:
            self.r = redis.from_url(url, decode_responses=True)
        else:
            self.r = redis.Redis(host=host, port=port, db=db, password=password, decode_responses=True)

        # Verify connection early
        try:
            self.r.ping()
        except Exception as e:  # pragma: no cover - network error path
            raise RuntimeError(f"Cannot connect to Redis: {e}")

    def _k(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        raw = self.r.get(self._k(key))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:  # pragma: no cover - corrupt value
            return None

    def __setitem__(self, key: str, value: Dict[str, Any]) -> None:
        try:
            raw = json.dumps(value)
        except Exception:  # pragma: no cover - serialization error
            raw = "{}"
        pipe = self.r.pipeline()
        pipe.set(self._k(key), raw)
        if self._ttl > 0:
            pipe.expire(self._k(key), self._ttl)
        pipe.execute()

    def items(self) -> List[Tuple[str, Dict[str, Any]]]:
        cursor = 0
        out: List[Tuple[str, Dict[str, Any]]] = []
        pattern = f"{self._prefix}*"
        while True:
            cursor, keys = self.r.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                vals = self.r.mget(keys)
                for k, v in zip(keys, vals):
                    if not v:
                        continue
                    try:
                        data = json.loads(v)
                    except Exception:
                        data = None
                    if data is not None:
                        sid = k[len(self._prefix) :]
                        out.append((sid, data))
            if cursor == 0:
                break
        return out

    def pop(self, key: str, default: Any = None) -> Any:
        val = self.get(key)
        self.r.delete(self._k(key))
        return val if val is not None else default

    def __len__(self) -> int:  # pragma: no cover - approximate
        count = 0
        cursor = 0
        pattern = f"{self._prefix}*"
        while True:
            cursor, keys = self.r.scan(cursor=cursor, match=pattern, count=500)
            count += len(keys)
            if cursor == 0:
                break
        return count
