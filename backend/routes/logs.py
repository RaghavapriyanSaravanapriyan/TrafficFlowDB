from fastapi import APIRouter

from ..querylog import snapshot

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("")
def read_logs(since: int = 0, limit: int = 100):
    return {"logs": snapshot(since, min(limit, 400))}
