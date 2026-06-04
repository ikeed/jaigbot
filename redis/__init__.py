from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any
from urllib.parse import urlparse

from .exceptions import (
    AuthenticationError,
    ConnectionError,
    InvalidData,
    InvalidResponse,
    RedisError,
    ResponseError,
)

__all__ = [
    "AuthenticationError",
    "ConnectionError",
    "ConnectionPool",
    "InvalidData",
    "InvalidResponse",
    "Redis",
    "RedisError",
    "ResponseError",
    "from_url",
]


_DATABASES: dict[tuple[str, int, int], dict[str, str]] = {}
_LOCK = RLock()


def _shared_store(host: str, port: int, db: int) -> dict[str, str]:
    key = (host, port, db)
    with _LOCK:
        return _DATABASES.setdefault(key, {})


@dataclass
class ConnectionPool:
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: str | None = None
    decode_responses: bool = True


class _Pipeline:
    def __init__(self, client: "Redis") -> None:
        self._client = client
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    def set(self, key: str, value: str) -> "_Pipeline":
        self._ops.append(("set", (key, value)))
        return self

    def expire(self, key: str, ttl: int) -> "_Pipeline":
        self._ops.append(("expire", (key, ttl)))
        return self

    def execute(self) -> list[Any]:
        out: list[Any] = []
        for op, args in self._ops:
            out.append(getattr(self._client, op)(*args))
        self._ops.clear()
        return out


class _PubSub:
    def __init__(self, client: "Redis", ignore_subscribe_messages: bool = True) -> None:
        self._client = client
        self._channels: set[str] = set()
        self._ignore = ignore_subscribe_messages

    def subscribe(self, *channels: str) -> None:
        for channel in channels:
            self._channels.add(channel)

    def listen(self):
        # Socket.IO expects an iterable here and uses `yield from` on it.
        # Returning an empty iterator keeps the stub non-blocking.
        return iter(())

    def unsubscribe(self, *channels: str) -> None:
        if not channels:
            self._channels.clear()
            return
        for channel in channels:
            self._channels.discard(channel)


class _Sentinel:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def master_for(self, service_name: str) -> "Redis":
        return Redis()


class _SentinelModule:
    Sentinel = _Sentinel


class Redis:
    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        decode_responses: bool = True,
        **_: Any,
    ) -> None:
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.decode_responses = decode_responses
        self._store = _shared_store(host, port, db)
        self._expirations: dict[str, int] = {}

    @classmethod
    def from_url(cls, url: str, **kwargs: Any) -> "Redis":
        parsed = urlparse(url)
        host = parsed.hostname or kwargs.pop("host", "localhost")
        port = int(parsed.port or kwargs.pop("port", 6379))
        db = int(parsed.path.lstrip("/") or kwargs.pop("db", 0))
        password = parsed.password or kwargs.pop("password", None)
        return cls(host=host, port=port, db=db, password=password, **kwargs)

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self._store.get(key)

    def set(self, key: str, value: str) -> bool:
        self._store[key] = value
        return True

    def expire(self, key: str, ttl: int) -> bool:
        self._expirations[key] = ttl
        return True

    def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self._store:
                removed += 1
                self._store.pop(key, None)
            self._expirations.pop(key, None)
        return removed

    def pipeline(self) -> _Pipeline:
        return _Pipeline(self)

    def scan(self, cursor: int = 0, match: str | None = None, count: int = 200):
        keys = list(self._store.keys())
        if match:
            prefix = match[:-1] if match.endswith("*") else match
            keys = [key for key in keys if key.startswith(prefix)]
        start = int(cursor or 0)
        chunk = keys[start : start + count]
        next_cursor = 0 if start + count >= len(keys) else start + count
        return next_cursor, chunk

    def mget(self, keys: list[str]):
        return [self._store.get(key) for key in keys]

    def pubsub(self, ignore_subscribe_messages: bool = True) -> _PubSub:
        return _PubSub(self, ignore_subscribe_messages=ignore_subscribe_messages)

    def publish(self, channel: str, data: str) -> int:
        return 0

    sentinel = _SentinelModule()


def from_url(url: str, decode_responses: bool = True, **kwargs: Any) -> Redis:
    return Redis.from_url(url, decode_responses=decode_responses, **kwargs)
