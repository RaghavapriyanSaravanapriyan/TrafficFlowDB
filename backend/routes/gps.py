import time

from fastapi import APIRouter, HTTPException

from .. import querylog
from ..schemas import GpsBatch, GpsIngest
from ..services.gps_processor import ingest_point

router = APIRouter(prefix="/api/gps", tags=["gps"])


@router.post("", summary="Ingest one GPS fix")
def ingest(point: GpsIngest):
    try:
        return ingest_point(point)
    except Exception as exc:  # surface DB trigger rejections as 422
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/batch", summary="Ingest a batch of GPS fixes")
def ingest_batch(batch: GpsBatch):
    t0 = time.perf_counter()
    results = []
    for point in batch.points:
        try:
            results.append(ingest_point(point))
        except Exception as exc:  # noqa: BLE001 — per-point errors don't abort batch
            results.append({"error": str(exc), "vehicle": point.vehicle_number})
    ms = (time.perf_counter() - t0) * 1000
    querylog.log(
        "SQL",
        "INSERT INTO gps_data (…) ×N; INSERT INTO vehicle_position (…) ×N; "
        "SELECT calculate_segment_traffic(seg, window)",
        ms,
        f"batch of {len(batch.points)} fixes",
    )
    return {"ingested": len(results), "results": results}
