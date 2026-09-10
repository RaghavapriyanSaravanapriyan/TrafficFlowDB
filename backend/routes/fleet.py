from fastapi import APIRouter, Request
from pydantic import BaseModel

from .. import querylog

router = APIRouter(prefix="/api/fleet", tags=["fleet"])


class FleetPatch(BaseModel):
    enabled: bool | None = None
    count: int | None = None
    interval: float | None = None


@router.get("")
def read_fleet(request: Request):
    return request.app.state.fleet.status()


@router.post("")
def write_fleet(patch: FleetPatch, request: Request):
    fleet = request.app.state.fleet
    before = len(fleet.vehicles)
    out = fleet.configure(patch.enabled, patch.count, patch.interval)
    querylog.log("FLEET",
                 "fleet configure + reconcile (spawn/retire to target)",
                 0, f"{before} → {out['alive']} vehicles, "
                    f"enabled={out['enabled']}, every {out['interval']}s")
    return out
