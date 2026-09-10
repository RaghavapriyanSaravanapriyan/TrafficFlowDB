import time

from fastapi import APIRouter

from ..database import get_pool

router = APIRouter(prefix="/api/stats", tags=["stats"])


@router.get("")
def overview():
    t0 = time.perf_counter()
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM vehicle WHERE status = 'active'")
            fleet = int(cur.fetchone()[0])
            # "Live" = heard from within ~15 ticks. last_seen is maintained by
            # the position trigger (single ingest) and bulk touch (batch path),
            # so spawn/retire reflects here in seconds, not minutes.
            cur.execute(
                "SELECT COUNT(*) FROM vehicle "
                "WHERE last_seen > NOW() - INTERVAL '30 seconds'"
            )
            vehicles = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM gps_data")
            gps_total = int(cur.fetchone()[0])
            cur.execute(
                "SELECT COUNT(*) FROM vehicle_position "
                "WHERE recorded_at > NOW() - INTERVAL '5 minutes'"
            )
            gps_recent = int(cur.fetchone()[0])
            cur.execute(
                "SELECT COUNT(*) FROM traffic_condition WHERE congestion_level = 'HIGH'"
            )
            high = int(cur.fetchone()[0])
            cur.execute(
                "SELECT COUNT(*) FROM traffic_condition WHERE congestion_level = 'MEDIUM'"
            )
            medium = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM route")
            routes = int(cur.fetchone()[0])
    ms = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "active_vehicles": vehicles,
        "fleet_total": fleet,
        "gps_updates_total": gps_total,
        "gps_updates_last_5min": gps_recent,
        "segments_high": high,
        "segments_medium": medium,
        "routes_computed": routes,
        "query_ms": ms,
    }
