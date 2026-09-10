"""TrafficFlowDB API — FastAPI entrypoint.

Serves REST + WebSocket on /api and the static dashboard on /.
Run:  uvicorn backend.main:app --reload
"""
from __future__ import annotations

import asyncio
import json
import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import querylog, runtime
from .config import settings
from .database import close_pool, get_pool, init_db, wait_for_db
from .routes import command, config, gps, logs, network, routing, scenarios, stats, traffic, vehicles

FRONTEND_DIR = pathlib.Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    wait_for_db()
    init_db(seed=True)
    querylog.log("NET", "lifespan: schema + seed + migrations applied", 0,
                 "API ready")
    yield
    close_pool()


app = FastAPI(title="TrafficFlowDB", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (gps.router, vehicles.router, traffic.router,
               network.router, routing.router, stats.router,
               config.router, scenarios.router, command.router, logs.router):
    app.include_router(router)


@app.get("/api/health")
def health():
    with get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    return {"status": "ok"}


def _jsonable(rows: list[dict]) -> list[dict]:
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()
    return rows


@app.websocket("/ws/live")
async def live(ws: WebSocket):
    """Push traffic + positions + fresh query-log entries every poll tick."""
    await ws.accept()
    try:
        while True:
            with get_pool().connection() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT * FROM live_traffic_summary ORDER BY segment_id")
                    cols = [d[0] for d in cur.description]
                    traffic_rows = _jsonable(
                        [dict(zip(cols, r, strict=True)) for r in cur.fetchall()])
                    cur.execute("SELECT * FROM latest_positions")
                    pcols = [d[0] for d in cur.description]
                    pos_rows = _jsonable(
                        [dict(zip(pcols, r, strict=True)) for r in cur.fetchall()])
            await ws.send_text(json.dumps({
                "traffic": traffic_rows,
                "positions": pos_rows,
                "logs": querylog.snapshot(limit=25),
            }))
            await asyncio.sleep(runtime.get("poll_seconds"))
    except WebSocketDisconnect:
        pass


# Static dashboard (mounted last so /api routes win).
if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
