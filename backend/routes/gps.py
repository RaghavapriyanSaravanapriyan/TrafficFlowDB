from fastapi import APIRouter, HTTPException

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
    results = []
    for point in batch.points:
        try:
            results.append(ingest_point(point))
        except Exception as exc:  # noqa: BLE001 — per-point errors don't abort batch
            results.append({"error": str(exc), "vehicle": point.vehicle_number})
    return {"ingested": len(results), "results": results}
