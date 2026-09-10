"""Live query/activity log — the "under the hood" feed.

Every interesting database interaction is appended here with its SQL template
and wall time. A bounded in-memory ring (NOT a table) keeps the hot ingest
path allocation-free-ish and fast: no extra writes per GPS fix.
"""
from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from typing import Any

MAX_ENTRIES = 400

_lock = threading.Lock()
_seq = itertools.count(1)
_entries: deque[dict[str, Any]] = deque(maxlen=MAX_ENTRIES)
_started_at = time.time()


def log(category: str, sql: str, ms: float = 0.0, detail: str = "") -> dict:
    """Append one entry. category: SQL | ROUTE | SCENARIO | CONFIG | NET | ERROR."""
    entry = {
        "id": next(_seq),
        "t": round(time.time() - _started_at, 1),
        "cat": category,
        "sql": sql,
        "ms": round(ms, 2),
        "detail": detail,
    }
    with _lock:
        _entries.append(entry)
    return entry


def snapshot(since: int = 0, limit: int = 100) -> list[dict]:
    with _lock:
        items = [e for e in _entries if e["id"] > since]
    return items[-limit:]
