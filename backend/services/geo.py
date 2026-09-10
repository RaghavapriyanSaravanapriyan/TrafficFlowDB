"""Tiny geo helpers: haversine + point-to-segment map matching.

The network is small (tens of segments), so a linear scan with an
equirectangular projection is both exact enough and effectively free
(~microseconds). No PostGIS round-trip on the ingest hot path.
"""
from __future__ import annotations

import math

EARTH_KM = 6371.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(a))


def _to_xy(lat: float, lon: float, ref_lat: float) -> tuple[float, float]:
    """Equirectangular projection (km) around ref_lat."""
    kx = math.pi / 180 * EARTH_KM * math.cos(math.radians(ref_lat))
    ky = math.pi / 180 * EARTH_KM
    return lon * kx, lat * ky


def point_to_segment_km(
    plat: float, plon: float,
    alat: float, alon: float, blat: float, blon: float,
) -> tuple[float, float, float]:
    """Distance (km) from P to segment AB + projection fraction t + interp speed n/a.

    Returns (distance_km, t, _) with t clamped to [0, 1].
    """
    ref = (plat + alat + blat) / 3.0
    px, py = _to_xy(plat, plon, ref)
    ax, ay = _to_xy(alat, alon, ref)
    bx, by = _to_xy(blat, blon, ref)
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    t = ((px - ax) * dx + (py - ay) * dy) / denom if denom else 0.0
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy), t, denom


def match_segment(
    lat: float, lon: float,
    segments: list[dict],
    max_km: float = 3.0,
) -> dict | None:
    """Return the nearest road segment dict, or None if nothing is close."""
    best: dict | None = None
    best_d = max_km
    for seg in segments:
        d, _, _ = point_to_segment_km(
            lat, lon,
            seg["start_lat"], seg["start_lon"], seg["end_lat"], seg["end_lon"],
        )
        if d < best_d:
            best_d, best = d, seg
    return best
