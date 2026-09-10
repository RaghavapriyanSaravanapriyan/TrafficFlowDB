from fastapi import APIRouter, HTTPException

from ..schemas import GpsBatch, GpsIngest
from ..services.gps_processor import ingest_point
from ..services.ingest_bulk import bulk_ingest

router = APIRouter(prefix="/api/gps", tags=["gps"])


@router.post("", summary="Ingest one GPS fix")
def ingest(point: GpsIngest):
    try:
        return ingest_point(point)
    except Exception as exc:  # surface DB trigger rejections as 422
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/batch", summary="Ingest a batch of GPS fixes (bulk path)")
def ingest_batch(batch: GpsBatch):
    try:
        out = bulk_ingest([{
            "vehicle_number": p.vehicle_number,
            "vehicle_type": p.vehicle_type,
            "latitude": p.latitude,
            "longitude": p.longitude,
            "speed_kmh": p.speed_kmh,
            "segment_id": p.segment_id,
            "recorded_at": p.timestamp.isoformat() if p.timestamp else None,
        } for p in batch.points])
    except Exception as exc:  # noqa: BLE001 — e.g. trigger rejections
        raise HTTPException(status_code=422, detail=str(exc))
    return {"ingested": out["ingested"], "results": [],
            "vehicles": out["vehicles"], "ms": out["ms"],
            "fixes_per_sec": out["fixes_per_sec"]}
