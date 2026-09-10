from fastapi import APIRouter

from .. import querylog, runtime
from ..database import get_pool

router = APIRouter(prefix="/api/traffic", tags=["traffic"])


@router.get("/summary")
def summary():
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM live_traffic_summary ORDER BY segment_id")
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


@router.get("/congested")
def congested(level: str = "MEDIUM"):
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM get_congested_segments(%s)", (level.upper(),))
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]


@router.get("/segment/{segment_id}")
def segment_detail(segment_id: int):
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM live_traffic_summary WHERE segment_id = %s",
                (segment_id,),
            )
            row = cur.fetchone()
            if not row:
                return {"error": "unknown segment"}
            cols = [d[0] for d in cur.description]
            data = dict(zip(cols, row, strict=True))
            cur.execute(
                """
                SELECT average_speed, vehicle_count, density, congestion_level, calculated_at
                FROM traffic_history WHERE segment_id = %s
                ORDER BY calculated_at DESC LIMIT 60
                """,
                (segment_id,),
            )
            hcols = [d[0] for d in cur.description]
            data["history"] = [dict(zip(hcols, r, strict=True)) for r in cur.fetchall()]
            return data


@router.post("/refresh")
def refresh():
    import time
    t0 = time.perf_counter()
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM refresh_all_traffic(%s)",
                (runtime.get("traffic_window_minutes"),),
            )
            rows = cur.fetchall()
    ms = (time.perf_counter() - t0) * 1000
    querylog.log("SQL", "SELECT * FROM refresh_all_traffic(window)", ms,
                 f"{len(rows)} segments recomputed")
    return {"refreshed": rows}
