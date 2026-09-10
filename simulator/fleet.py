"""Server-side synthetic fleet (Customize drawer engine).

Unlike the CLI simulator (a separate process), this fleet lives inside the API:
enable it, set a target size, and vehicles spawn/retire live while a background
task steps them through OD trips and writes via the bulk ingest path.
"""
from __future__ import annotations

import asyncio
import time

from ..database import get_pool
from ..services.ingest_bulk import bulk_ingest
from .vehicle_simulator import Vehicle, build_graph, plan_trip


class FleetManager:
    def __init__(self) -> None:
        self.vehicles: list[Vehicle] = []
        self.enabled = False
        self.target = 0
        self.interval = 2.0
        self.last: dict = {}
        self._task: asyncio.Task | None = None

    # -- lifecycle ------------------------------------------------------
    def start(self):
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self.enabled = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def configure(self, enabled: bool | None = None,
                  count: int | None = None,
                  interval: float | None = None) -> dict:
        if enabled is not None:
            self.enabled = bool(enabled)
        if count is not None:
            self.target = max(0, min(int(count), 2000))
        if interval is not None:
            self.interval = max(0.5, min(float(interval), 30))
        self._reconcile(sync=True)
        return self.status()

    def status(self) -> dict:
        return {"enabled": self.enabled, "target": self.target,
                "alive": len(self.vehicles), "interval": self.interval,
                "last": self.last}

    # -- fleet -----------------------------------------------------------
    def _snapshot(self) -> tuple[list[dict], list[dict], list[dict]]:
        with get_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT rs.segment_id, rs.segment_name, rs.distance_km,
                           rs.speed_limit_kmh, rs.road_type, rs.capacity, rs.scope,
                           rs.start_intersection_id, rs.end_intersection_id,
                           i1.latitude, i1.longitude, i2.latitude, i2.longitude
                    FROM road_segment rs
                    JOIN intersection i1 ON i1.intersection_id = rs.start_intersection_id
                    JOIN intersection i2 ON i2.intersection_id = rs.end_intersection_id
                    WHERE rs.is_active
                    """)
                segs = [{"id": r[0], "name": r[1], "distance_km": r[2],
                         "speed_limit": r[3], "road_type": r[4], "capacity": r[5],
                         "scope": r[6], "a": r[7], "b": r[8],
                         "a_lat": r[9], "a_lon": r[10], "b_lat": r[11], "b_lon": r[12]}
                        for r in cur.fetchall()]
                cur.execute("SELECT intersection_id, name, scope FROM intersection")
                nodes = [{"id": r[0], "name": r[1], "scope": r[2]} for r in cur.fetchall()]
                cur.execute("SELECT * FROM live_traffic_summary")
                cols = [d[0] for d in cur.description]
                traffic = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        return segs, nodes, traffic

    def _reconcile(self, segments: list[dict] | None = None):
        if not self.enabled:
            self.vehicles = []
            return
        seg_by_id = {s["id"]: s for s in (segments or [])}
        while len(self.vehicles) < self.target:
            pool = segments or []
            try:
                self.vehicles.append(Vehicle(pool, seg_by_id=seg_by_id or None))
            except Exception:
                break  # empty network — retry next reconcile
        if len(self.vehicles) > self.target:
            del self.vehicles[self.target:]

    async def _loop(self):
        ticks = 0
        while True:
            try:
                if self.enabled and self.target > 0:
                    await asyncio.to_thread(self._tick, ticks)
                    ticks += 1
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — fleet loop never dies on a bad tick
                pass
            await asyncio.sleep(self.interval)

    def _tick(self, ticks: int):
        segs, nodes, traffic = self._snapshot()
        if not segs:
            return
        self._reconcile(segs)
        if not self.vehicles:
            return
        by_seg: dict[int, list[dict]] = {}
        for s in segs:
            by_seg.setdefault(s["a"], []).append(s)
            by_seg.setdefault(s["b"], []).append(s)
        tmap = {r["segment_id"]: r for r in traffic}
        graph = build_graph(segs, tmap, nodes)
        ctx = {
            "by_seg": by_seg,
            "congestion": {r["segment_id"]: r["congestion_level"] for r in traffic},
            "loads": {r["segment_id"]: (r["vehicle_count"],
                      next((s["capacity"] for s in segs if s["id"] == r["segment_id"]), 40))
                      for r in traffic},
            "segments": segs,
            "plan": lambda node, g=graph: plan_trip(g, node),
        }
        if ticks % 15 == 0:  # re-plan stale trips against fresh weights
            for v in self.vehicles:
                v.seg_by_id = {s["id"]: s for s in segs}
        points = [v.step(ctx, self.interval) for v in self.vehicles]
        self.last = {"at": round(time.time(), 1), **bulk_ingest(points)}
