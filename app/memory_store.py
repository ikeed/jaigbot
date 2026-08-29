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
import logging
import os
import tempfile
import threading
from typing import Any, Dict, List, Optional, Tuple, cast

module_logger = logging.getLogger(__name__)


class InMemoryStore:
    """Simple process-local store used for local development/testing.

    Implements a minimal dict-like interface that the app expects.
    """

    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._persist_path = persist_path
        self._store: Dict[str, Dict[str, Any]] = {}
        # Mutations and persistence must be serialized. Writes used to happen only on the
        # event-loop thread, which serialized them for free; background work now runs in a
        # worker threadpool, so two threads can reach _persist concurrently. Reentrant
        # because the mutating methods hold the lock while calling _persist.
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        if not self._persist_path:
            return
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._store = {
                    str(k): v
                    for k, v in data.items()
                    if isinstance(v, dict)
                }
                for value in self._store.values():
                    if "history" in value:
                        value["active_connections"] = []
        except FileNotFoundError:
            return
        except Exception as e:
            module_logger.error("Failed to load memory store from %s: %s", self._persist_path, e)
            self._store = {}

    def _persist(self) -> None:
        """Serialize the store to disk. Callers must hold ``self._lock``."""
        if not self._persist_path:
            return
        try:
            directory = os.path.dirname(self._persist_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            # A per-write temp file, not a single shared "<path>.tmp": two concurrent
            # writers sharing one temp path interleave their output and then both rename
            # it, leaving truncated or mixed JSON behind.
            fd, tmp_path = tempfile.mkstemp(
                dir=directory or ".", prefix=os.path.basename(self._persist_path) + ".", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._store, f, ensure_ascii=False)
                os.replace(tmp_path, self._persist_path)
            except BaseException:
                # Never leave the temp file behind on a failed write.
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception as e:
            module_logger.error("Failed to persist memory store to %s: %s", self._persist_path, e)
            pass

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        return self._store.get(key)

    def __getitem__(self, key: str) -> Dict[str, Any]:
        return self._store[key]

    def __setitem__(self, key: str, value: Dict[str, Any]) -> None:
        with self._lock:
            self._store[key] = value
            self._persist()

    # noinspection PyUnusedLocal
    def set(self, key: str, value: Dict[str, Any], ttl: Optional[int] = None) -> None:
        self.__setitem__(key, value)

    def __contains__(self, key: str) -> bool:  # pragma: no cover - trivial
        return key in self._store

    def items(self) -> List[Tuple[str, Dict[str, Any]]]:
        # Snapshot under the lock: callers iterate this while other threads may be
        # mutating the store (prune_expired walks every session and pops as it goes).
        with self._lock:
            return list(self._store.items())

    def pop(self, key: str, default: Any = None) -> Any:
        with self._lock:
            value = self._store.pop(key, default)
            self._persist()
            return value

    def __len__(self) -> int:  # pragma: no cover - trivial
        return len(self._store)


class RedisStore:
    """Redis-backed store with TTL and key prefix.

    Parameters
    - url: full redis URL, if provided (takes precedence over host/port/db/password)
    - host, port, db, password: standard Redis connection fields
    - prefix: string prefix for namespacing keys
    - fallback_prefixes: read-only legacy prefixes used during migrations
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
        prefix: str = "aims:session:",
        fallback_prefixes: Optional[List[str]] = None,
        ttl: int = 3600,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        try:
            import redis  # type: ignore
        except Exception as e:
            self.logger.error("Failed to import Redis library: %s", e)
            raise RuntimeError(f"Redis library not available: {e}")

        self._prefix = prefix
        self._fallback_prefixes = [p for p in fallback_prefixes or [] if p and p != prefix]
        self._ttl = ttl

        if url:
            self.r = redis.from_url(url, decode_responses=True)
        else:
            self.r = redis.Redis(host=host or "localhost", port=port, db=db, password=password, decode_responses=True)

        # Verify connection early
        try:
            self.r.ping()
        except Exception as e:  # pragma: no cover - network error path
            raise RuntimeError(f"Cannot connect to Redis: {e}")

    def _k(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def _candidate_keys(self, key: str) -> List[str]:
        return [self._k(key), *[f"{prefix}{key}" for prefix in self._fallback_prefixes]]

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        for redis_key in self._candidate_keys(key):
            raw = self.r.get(redis_key)
            if not raw:
                continue
            try:
                return json.loads(raw)
            except Exception as e:
                self.logger.error(f"Failed to parse Redis value for key {redis_key}: {e}")
                return None
        return None

    def set(self, key: str, value: Dict[str, Any], ttl: Optional[int] = None) -> None:
        try:
            raw = json.dumps(value)
        except Exception as e:
            self.logger.exception(f"Failed to serialize value for key {key}: {e}")
            raw = "{}"
        pipe = self.r.pipeline()
        pipe.set(self._k(key), raw)
        effective_ttl = self._ttl if ttl is None else ttl
        if effective_ttl > 0:
            pipe.expire(self._k(key), effective_ttl)
        pipe.execute()

    def __setitem__(self, key: str, value: Dict[str, Any]) -> None:
        self.set(key, value)

    def items(self) -> List[Tuple[str, Dict[str, Any]]]:
        out: List[Tuple[str, Dict[str, Any]]] = []
        seen = set()
        for prefix in [self._prefix, *self._fallback_prefixes]:
            cursor = 0
            pattern = f"{prefix}*"
            while True:
                cursor, keys = self.r.scan(cursor=cursor, match=pattern, count=200)
                if keys:
                    vals = self.r.mget(keys)
                    for k, v in zip(keys, vals):
                        if not v:
                            continue
                        redis_key = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                        try:
                            data = json.loads(v)
                        except Exception as e:
                            self.logger.debug(f"Failed to parse Redis value for key {redis_key}: {e}")
                            data = None
                        if data is not None:
                            sid = redis_key[len(prefix) :]
                            if sid not in seen:
                                seen.add(sid)
                                out.append((sid, cast(Dict[str, Any], data)))
                if cursor == 0:
                    break
        return out

    def pop(self, key: str, default: Any = None) -> Any:
        val = self.get(key)
        self.r.delete(*self._candidate_keys(key))
        return val if val is not None else default

    def __len__(self) -> int:  # pragma: no cover - approximate
        seen = set()
        for prefix in [self._prefix, *self._fallback_prefixes]:
            cursor = 0
            pattern = f"{prefix}*"
            while True:
                cursor, keys = self.r.scan(cursor=cursor, match=pattern, count=500)
                for key in keys:
                    seen.add(key[len(prefix) :])
                if cursor == 0:
                    break
        return len(seen)
