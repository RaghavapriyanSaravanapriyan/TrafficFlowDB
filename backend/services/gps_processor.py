"""GPS + map-matched position ingest (the real-time hot path)."""
from __future__ import annotations

from .. import runtime
from ..database import get_pool
from ..schemas import GpsIngest
from ..services import geo

# In-memory segment geometry for map matching (refreshed lazily).
_geo_cache: dict = {"segments": []}


def segment_geometries(conn) -> list[dict]:
    if _geo_cache["segments"]:
        return _geo_cache["segments"]
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rs.segment_id,
                   i1.latitude, i1.longitude, i2.latitude, i2.longitude
            FROM road_segment rs
            JOIN intersection i1 ON i1.intersection_id = rs.start_intersection_id
            JOIN intersection i2 ON i2.intersection_id = rs.end_intersection_id
            WHERE rs.is_active
            """
        )
        _geo_cache["segments"] = [
            {"segment_id": r[0], "start_lat": r[1], "start_lon": r[2],
             "end_lat": r[3], "end_lon": r[4]}
            for r in cur.fetchall()
        ]
    return _geo_cache["segments"]


def ensure_vehicle(conn, point: GpsIngest) -> int:
    """Get-or-create a vehicle by number, stamping its subtype row once."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT vehicle_id FROM vehicle WHERE vehicle_number = %s",
            (point.vehicle_number,),
        )
        row = cur.fetchone()
        if row:
            return int(row[0])
        cur.execute(
            "INSERT INTO vehicle (vehicle_number, vehicle_type) VALUES (%s, %s) "
            "RETURNING vehicle_id",
            (point.vehicle_number, point.vehicle_type),
        )
        vid = int(cur.fetchone()[0])
        if point.vehicle_type == "car":
            cur.execute(
                "INSERT INTO car_detail (vehicle_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (vid,),
            )
        elif point.vehicle_type == "bus":
            cur.execute(
                "INSERT INTO bus_detail (vehicle_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (vid,),
            )
        else:
            cur.execute(
                "INSERT INTO emergency_vehicle_detail (vehicle_id, emergency_type) "
                "VALUES (%s, 'ambulance') ON CONFLICT DO NOTHING",
                (vid,),
            )
        return vid


def ingest_point(point: GpsIngest) -> dict:
    """Validate -> map-match -> store raw + matched -> refresh that segment."""
    pool = get_pool()
    with pool.connection() as conn:
        vehicle_id = ensure_vehicle(conn, point)

        segment_id = point.segment_id
        if segment_id is None:
            match = geo.match_segment(
                point.latitude, point.longitude, segment_geometries(conn)
            )
            segment_id = match["segment_id"] if match else None
            if segment_id is None:  # off-network fix: nearest by DB fallback
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT segment_id FROM find_nearby_segments(%s, %s, 1)",
                        (point.latitude, point.longitude),
                    )
                    row = cur.fetchone()
                    segment_id = int(row[0]) if row else None

        ts = point.timestamp.isoformat() if point.timestamp else None
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO gps_data (vehicle_id, latitude, longitude, speed_kmh, recorded_at)
                VALUES (%s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()))
                """,
                (vehicle_id, point.latitude, point.longitude, point.speed_kmh, ts),
            )
            cur.execute(
                """
                INSERT INTO vehicle_position
                    (vehicle_id, segment_id, latitude, longitude, speed_kmh, recorded_at)
                VALUES (%s, %s, %s, %s, %s, COALESCE(%s::timestamptz, NOW()))
                """,
                (vehicle_id, segment_id, point.latitude, point.longitude,
                 point.speed_kmh, ts),
            )
            level = "LOW"
            if segment_id is not None:
                cur.execute(
                    "SELECT calculate_segment_traffic(%s, %s)",
                    (segment_id, runtime.get("traffic_window_minutes")),
                )
                level = str(cur.fetchone()[0])
    return {"vehicle_id": vehicle_id, "segment_id": segment_id, "congestion": level}
