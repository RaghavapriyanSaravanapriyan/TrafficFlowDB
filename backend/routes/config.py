from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import querylog, runtime
from ..database import get_pool

router = APIRouter(prefix="/api/config", tags=["config"])


class Thresholds(BaseModel):
    high_speed: float | None = None
    high_density: float | None = None
    med_speed: float | None = None
    med_density: float | None = None


class ConfigPatch(BaseModel):
    traffic_window_minutes: int | None = None
    poll_seconds: float | None = None
    thresholds: Thresholds | None = None


@router.get("")
def read_config():
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT high_speed, high_density, med_speed, med_density "
                        "FROM traffic_thresholds WHERE id = 1")
            t = cur.fetchone()
    return {**runtime.get_all(), "thresholds": {
        "high_speed": t[0], "high_density": t[1],
        "med_speed": t[2], "med_density": t[3]}}


@router.put("")
def write_config(patch: ConfigPatch):
    import time
    t0 = time.perf_counter()
    applied = runtime.update(patch.model_dump())
    if patch.thresholds:
        vals = patch.thresholds.model_dump(exclude_none=True)
        if vals:
            sets = ", ".join(f"{k} = %s" for k in vals)
            with get_pool().connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(f"UPDATE traffic_thresholds SET {sets} WHERE id = 1",
                                tuple(vals.values()))
                    cur.execute("SELECT * FROM refresh_all_traffic(%s)",
                                (applied["traffic_window_minutes"],))
    ms = (time.perf_counter() - t0) * 1000
    querylog.log("CONFIG", "UPDATE traffic_thresholds SET …; SELECT refresh_all_traffic(%s)",
                 ms, f"window={applied['traffic_window_minutes']}min")
    return read_config()
