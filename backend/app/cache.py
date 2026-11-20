"""
A small thread-safe LRU cache with TTL, keyed by (endpoint, normalised filters, params).

Why in-process and not Redis: the data is immutable for the life of a build,
there is a single instance, and the key space (filter combinations people
actually click) is small. A miss costs ~5–30 ms of DuckDB time, so the cache
mainly smooths repeated dashboards and cold free-tier CPUs. With several
instances, a shared cache (Redis) or a CDN in front of the GET endpoints would
be the next step.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable


class TTLCache:
    def __init__(self, maxsize: int = 512, ttl_seconds: float = 3600) -> None:
        self.maxsize = maxsize
        self.ttl = ttl_seconds
        self._data: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: Hashable) -> tuple[bool, Any]:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return False, None
            expires, value = entry
            if expires < time.monotonic():
                del self._data[key]
                self.misses += 1
                return False, None
            self._data.move_to_end(key)
            self.hits += 1
            return True, value

    def set(self, key: Hashable, value: Any) -> None:
        with self._lock:
            self._data[key] = (time.monotonic() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def get_or_compute(self, key: Hashable, fn: Callable[[], Any]) -> tuple[bool, Any]:
        """Return (hit, value). Concurrent misses on the same key may both compute;
        that's acceptable here (idempotent, cheap reads) and avoids per-key locks."""
        hit, value = self.get(key)
        if hit:
            return True, value
        value = fn()
        self.set(key, value)
        return False, value

    def stats(self) -> dict[str, Any]:
        with self._lock:
            total = self.hits + self.misses
            return {
                "size": len(self._data),
                "maxsize": self.maxsize,
                "ttl_seconds": self.ttl,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else None,
            }
