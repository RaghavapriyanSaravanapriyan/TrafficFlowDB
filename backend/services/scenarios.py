"""Server-side traffic scenario injector (customize menu engine).

Jam / rush-hour vehicles are injected straight through the normal ingest
path (ingest_point -> stored procedure), so the dashboard, logs and router
react exactly as if a real simulator fleet caused them. Scenario plates
start with SCN so reset can remove them without touching real traffic.
"""
from __future__ import annotations

import random
import time

from ..database import get_pool
from ..schemas import GpsIngest
from .gps_processor import ingest_point


def _segments_with_geo(conn, where: str = "", args: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT rs.segment_id, rs.segment_name, rs.distance_km,
                   rs.speed_limit_kmh, rs.capacity, rs.scope,
                   i1.latitude, i1.longitude, i2.latitude, i2.longitude
            FROM road_segment rs
            JOIN intersection i1 ON i1.intersection_id = rs.start_intersection_id
            JOIN intersection i2 ON i2.intersection_id = rs.end_intersection_id
            WHERE rs.is_active {where}
            """,
            args,
        )
        return [
            {"id": r[0], "name": r[1], "distance_km": r[2], "limit": r[3],
             "capacity": r[4], "scope": r[5],
             "a_lat": r[6], "a_lon": r[7], "b_lat": r[8], "b_lon": r[9]}
            for r in cur.fetchall()
        ]


def resolve_segment(segment_id: int | None = None,
                    name: str | None = None) -> dict:
    with get_pool().connection() as conn:
        if segment_id is not None:
            segs = _segments_with_geo(conn, "AND rs.segment_id = %s", (segment_id,))
        elif name:
            segs = _segments_with_geo(conn, "AND rs.segment_name ILIKE %s",
                                      (f"%{name}%",))
        else:
            segs = []
    if not segs:
        raise LookupError("no matching segment")
    return segs[0]


def _crawl(seg: dict, prefix: str, count: int, speed: float) -> int:
    n = 0
    for i in range(count):
        t = random.random()
        lat = seg["a_lat"] + (seg["b_lat"] - seg["a_lat"]) * t
        lon = seg["a_lon"] + (seg["b_lon"] - seg["a_lon"]) * t
        ingest_point(GpsIngest(
            vehicle_number=f"{prefix}-{int(time.time() * 1000) % 10**6:06d}-{i:03d}",
            latitude=round(lat + random.uniform(-0.002, 0.002), 6),
            longitude=round(lon + random.uniform(-0.002, 0.002), 6),
            speed_kmh=round(random.uniform(speed * 0.7, speed * 1.3), 1),
            segment_id=seg["id"],
        ))
        n += 1
    return n


def inject_jam(segment_id: int | None = None, name: str | None = None,
               count: int = 30, speed_kmh: float = 8.0) -> dict:
    seg = resolve_segment(segment_id, name)
    n = _crawl(seg, "SCNJAM", count, speed_kmh)
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT congestion_level, average_speed, vehicle_count, density "
                "FROM traffic_condition WHERE segment_id = %s",
                (seg["id"],),
            )
            row = cur.fetchone()
    return {"segment": seg["name"], "segment_id": seg["id"],
            "injected": n, "traffic": row and {
                "congestion": row[0], "avg_speed": round(row[1], 1),
                "vehicles": row[2], "density": round(row[3], 3)}}


def rush_hour(per_segment: int = 8, n_segments: int = 12) -> dict:
    with get_pool().connection() as conn:
        segs = _segments_with_geo(
            conn, "ORDER BY rs.capacity DESC LIMIT %s",
            (n_segments,))
    total = 0
    for seg in segs:
        total += _crawl(seg, "SCNRUSH", per_segment, seg["limit"] * 0.45)
    return {"segments": len(segs), "injected": total}


def reset() -> dict:
    from .. import runtime as _rt
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM vehicle WHERE vehicle_number LIKE 'SCN%'")
            removed = cur.rowcount
            cur.execute("SELECT * FROM refresh_all_traffic(%s)",
                        (_rt.get("traffic_window_minutes"),))
            states = cur.fetchall()
    levels = {}
    for _, lvl in states:
        levels[lvl] = levels.get(lvl, 0) + 1
    return {"removed_scenario_vehicles": removed, "segments": levels}
