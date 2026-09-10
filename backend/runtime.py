"""Mutable runtime configuration (customize menu).

Defaults come from the environment; PUT /api/config overrides them live
without a restart. Thresholds live authoritatively in the traffic_thresholds
table — this module only caches the window/poll knobs.
"""
from __future__ import annotations

import threading

from .config import settings

_lock = threading.Lock()
_state = {
    "traffic_window_minutes": settings.traffic_window_minutes,
    "poll_seconds": settings.poll_seconds,
}


def get_all() -> dict:
    with _lock:
        return dict(_state)


def get(key: str):
    with _lock:
        return _state[key]


def update(patch: dict) -> dict:
    with _lock:
        for key in ("traffic_window_minutes", "poll_seconds"):
            if key in patch and patch[key] is not None:
                _state[key] = patch[key]
        return dict(_state)
