import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import querylog
from ..services import scenarios

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


class JamIn(BaseModel):
    segment_id: int | None = None
    segment_name: str | None = None
    count: int = 30
    speed_kmh: float = 8.0


class RushIn(BaseModel):
    per_segment: int = 8
    n_segments: int = 12


@router.post("/jam")
def jam(body: JamIn):
    t0 = time.perf_counter()
    try:
        out = scenarios.inject_jam(body.segment_id, body.segment_name,
                                   min(body.count, 200), body.speed_kmh)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    ms = (time.perf_counter() - t0) * 1000
    querylog.log("SCENARIO",
                 "inject N slow fixes → INSERT gps_data/vehicle_position; "
                 "SELECT calculate_segment_traffic(seg)",
                 ms, f"jam '{out['segment']}' → {out['traffic']['congestion']}")
    return out


@router.post("/rush-hour")
def rush_hour(body: RushIn):
    t0 = time.perf_counter()
    out = scenarios.rush_hour(min(body.per_segment, 40), min(body.n_segments, 30))
    ms = (time.perf_counter() - t0) * 1000
    querylog.log("SCENARIO", "rush-hour inject across top-capacity segments",
                 ms, f"{out['injected']} vehicles on {out['segments']} segments")
    return out


@router.post("/reset")
def reset():
    t0 = time.perf_counter()
    out = scenarios.reset()
    ms = (time.perf_counter() - t0) * 1000
    querylog.log("SCENARIO", "DELETE FROM vehicle WHERE number LIKE 'SCN%'; "
                             "SELECT refresh_all_traffic(window)",
                 ms, f"removed {out['removed_scenario_vehicles']} vehicles")
    return out
