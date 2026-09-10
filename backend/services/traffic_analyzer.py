"""Traffic analysis helpers.

The authoritative congestion rule lives in the stored procedure
`calculate_segment_traffic`. This module mirrors it for in-Python use
(routing weights, simulator) — keep the two in sync.
"""
from __future__ import annotations

CONGESTION_MULTIPLIER = {"LOW": 1.0, "MEDIUM": 1.5, "HIGH": 2.5}
MIN_SPEED_KMH = 5.0


def classify(avg_speed: float, density: float) -> str:
    if avg_speed < 15 and density > 0.75:
        return "HIGH"
    if avg_speed < 30 or density > 0.50:
        return "MEDIUM"
    return "LOW"


def density_of(vehicle_count: int, capacity: int) -> float:
    return vehicle_count / capacity if capacity > 0 else 0.0


def effective_speed_kmh(
    avg_speed: float, vehicle_count: int, speed_limit: int, level: str
) -> float:
    """Live average when observed, else limit derated by congestion level."""
    if vehicle_count > 0:
        return max(avg_speed, MIN_SPEED_KMH)
    return max(speed_limit / CONGESTION_MULTIPLIER.get(level, 1.0), MIN_SPEED_KMH)


def travel_time_min(distance_km: float, speed_kmh: float) -> float:
    return distance_km / max(speed_kmh, MIN_SPEED_KMH) * 60.0
