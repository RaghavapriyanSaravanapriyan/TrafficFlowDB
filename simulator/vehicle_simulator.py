"""TrafficFlowDB vehicle simulator — generates the live GPS stream.

Each vehicle drives real origin→destination trips: it picks a destination,
follows the Dijkstra shortest-time path (same engine as the API router),
slows down with density, and picks a new trip on arrival. Buses dwell at
stops, emergency vehicles push through congestion.

Usage:
    python -m simulator.vehicle_simulator [--vehicles N] [--interval SEC]
        [--base-url URL] [--mode trip|wander]
        [--jam-segment ID] [--jam-count N] [--once]
"""
from __future__ import annotations

import argparse
import random
import signal
import string
import sys
import time

import httpx

from backend.services.route_optimizer import dijkstra

running = True


def _stop(*_args):
    global running
    running = False


signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)

TYPE_FACTOR = {"car": 1.0, "bus": 0.85, "emergency": 1.3}
LEVEL_FACTOR = {"LOW": 1.0, "MEDIUM": 0.55, "HIGH": 0.28}


def plate(prefix: str = "TN38") -> str:
    letters = "".join(random.choices(string.ascii_uppercase, k=2))
    return f"{prefix}{letters}{random.randint(1000, 9999)}"


def pick_type() -> str:
    r = random.random()
    if r < 0.70:
        return "car"
    if r < 0.92:
        return "bus"
    return "emergency"


def build_graph(segments: list[dict], traffic: dict[int, dict],
                nodes: list[dict]) -> dict:
    """Optimizer-shaped graph from plain API/DB rows (shared by CLI + fleet)."""
    segmap, adj = {}, {}
    for s in segments:
        t = traffic.get(s["id"], {})
        segmap[s["id"]] = {
            "segment_id": s["id"], "a": s["a"], "b": s["b"], "name": s["name"],
            "distance_km": float(s["distance_km"]), "speed_limit": int(s["speed_limit"]),
            "capacity": int(s["capacity"]), "road_type": s.get("road_type", "arterial"),
            "avg_speed": float(t.get("average_speed", s["speed_limit"])),
            "vehicle_count": int(t.get("vehicle_count", 0)),
            "level": t.get("congestion_level", "LOW"),
        }
        adj.setdefault(s["a"], []).append((s["b"], s["id"]))
        adj.setdefault(s["b"], []).append((s["a"], s["id"]))
    return {"adj": adj, "segments": segmap,
            "nodes": {n["id"]: n for n in nodes}}


def plan_trip(graph: dict, from_node: int) -> list[int]:
    """Random destination (national-biased, like real intercity flow) → leg list."""
    nodes = list(graph["nodes"].values())
    if not nodes:
        return []
    nation = [n["id"] for n in nodes if n.get("scope") == "national"]
    metro = [n["id"] for n in nodes if n.get("scope") != "national"]
    pool = nation if nation and random.random() < 0.65 else (metro or nation)
    dest = random.choice([i for i in pool if i != from_node] or [from_node])
    if dest == from_node:
        return []
    r = dijkstra(graph, from_node, dest)
    return r["segment_path"] if r else []


class Vehicle:
    def __init__(self, segments: list[dict], jam_segment: int | None = None,
                 seg_by_id: dict[int, dict] | None = None):
        self.number = plate()
        self.vtype = pick_type()
        self.aggression = random.uniform(0.75, 1.25)
        self.seg_by_id = seg_by_id or {s["id"]: s for s in segments}
        if jam_segment:
            pool = [s for s in segments if s["id"] == jam_segment] or segments
            self.seg = random.choice(pool)
        else:
            # Capacity-weighted spawn: big corridors naturally carry more flow.
            self.seg = random.choices(
                segments,
                weights=[max(s.get("capacity", 40), 1) for s in segments],
                k=1)[0]
        self.t = random.random()
        self.fwd = random.random() < 0.5
        self.speed = self.seg["speed_limit"] * random.uniform(0.5, 0.9)
        self.jammed = jam_segment is not None
        self.trip: list[int] = []     # remaining leg segment ids
        self.dwell = 0                # bus-stop pause ticks
        self.node = self.seg["a"]     # last intersection departed/arrived

    # -- movement ---------------------------------------------------------
    def step(self, ctx, interval: float) -> dict:
        """ctx: dict(by_seg, congestion, loads, segments, plan=None)."""
        if self.jammed:
            self.speed = random.uniform(5, 12)
            self.t = (self.t + 0.002) % 1.0
        elif self.dwell > 0:
            self.dwell -= 1
            self.speed = 0.0
        else:
            level = ctx["congestion"].get(self.seg["id"], "LOW")
            factor = LEVEL_FACTOR[level] if self.vtype != "emergency" else 0.9
            count, cap = ctx["loads"].get(self.seg["id"], (0, self.seg["capacity"]))
            density_cut = max(0.3, 1 - (count / max(cap, 1)) * 0.6)
            target = (self.seg["speed_limit"] * TYPE_FACTOR[self.vtype]
                      * self.aggression * factor * density_cut)
            top = self.seg["speed_limit"] * 1.3
            if self.vtype == "emergency":
                top = max(top, 120)
            self.speed += (min(target, top) - self.speed) * 0.35
            self.speed = max(0.0, self.speed)
            self.t += (self.speed / 3600 * interval) / max(self.seg["distance_km"], 0.1)
            if self.t >= 1.0 or self.t <= 0.0:
                self._arrive(ctx)

        a_lat, a_lon = self.seg["a_lat"], self.seg["a_lon"]
        b_lat, b_lon = self.seg["b_lat"], self.seg["b_lon"]
        if not self.fwd:
            a_lat, a_lon, b_lat, b_lon = b_lat, b_lon, a_lat, a_lon
        lat = a_lat + (b_lat - a_lat) * self.t + random.uniform(-0.0004, 0.0004)
        lon = a_lon + (b_lon - a_lon) * self.t + random.uniform(-0.0004, 0.0004)
        return {
            "vehicle_number": self.number,
            "vehicle_type": self.vtype,
            "latitude": round(lat, 6),
            "longitude": round(lon, 6),
            "speed_kmh": round(self.speed, 1),
            "segment_id": self.seg["id"],
        }

    def _enter(self, seg: dict, from_node: int):
        self.seg = seg
        self.node = from_node
        if seg["a"] == from_node:
            self.fwd, self.t = True, 0.0
        else:
            self.fwd, self.t = False, 1.0

    def _arrive(self, ctx):
        node = self.seg["b"] if self.fwd else self.seg["a"]
        self.node = node
        # 1. continue a planned trip if the next leg touches this node.
        while self.trip:
            nxt = self.seg_by_id.get(self.trip.pop(0))
            if nxt and (nxt["a"] == node or nxt["b"] == node):
                if self.vtype == "bus" and random.random() < 0.4:
                    self.dwell = random.randint(1, 3)  # bus stop
                self._enter(nxt, node)
                return
        # 2. plan a fresh trip, else wander.
        plan = ctx.get("plan")
        if plan:
            legs = plan(node) or []
            self.trip = [i for i in legs
                         if i in self.seg_by_id and i != self.seg["id"]]
            if self.trip:
                self._arrive(ctx)
                return
        options = [s for s in ctx["by_seg"].get(node, []) if s["id"] != self.seg["id"]]
        nxt = random.choice(options) if options else random.choice(ctx["segments"])
        self._enter(nxt, node)


def main() -> int:
    ap = argparse.ArgumentParser(description="TrafficFlowDB GPS simulator")
    ap.add_argument("--vehicles", type=int, default=70)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--mode", choices=("trip", "wander"), default="trip")
    ap.add_argument("--jam-segment", type=int, default=None)
    ap.add_argument("--jam-count", type=int, default=40)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=20)
    try:
        segments = client.get("/api/network/segments").json()
        nodes = client.get("/api/network/intersections").json()
    except Exception as exc:
        print(f"cannot reach API at {args.base_url}: {exc}", file=sys.stderr)
        return 1
    if not segments:
        print("no road segments — is the seed loaded?", file=sys.stderr)
        return 1

    seg_by_id = {s["id"]: s for s in segments}
    by_seg: dict[int, list[dict]] = {}
    for s in segments:
        by_seg.setdefault(s["a"], []).append(s)
        by_seg.setdefault(s["b"], []).append(s)

    fleet = [Vehicle(segments, None, seg_by_id) for _ in range(args.vehicles)]
    fleet += [Vehicle(segments, args.jam_segment, seg_by_id)
              for _ in range(args.jam_count if args.jam_segment else 0)]
    print(f"simulating {len(fleet)} vehicles ({args.mode} mode) on "
          f"{len(segments)} segments -> {args.base_url}")

    ctx: dict = {"by_seg": by_seg, "congestion": {}, "loads": {},
                 "segments": segments, "plan": None}
    graph = None
    tick = 0
    while running:
        tick += 1
        if tick % 8 == 1:  # refresh traffic + routing graph ~every 8 ticks
            try:
                rows = client.get("/api/traffic/summary").json()
                ctx["congestion"] = {r["segment_id"]: r["congestion_level"] for r in rows}
                ctx["loads"] = {r["segment_id"]: (r["vehicle_count"],
                                next((s["capacity"] for s in segments
                                      if s["id"] == r["segment_id"]), 40)) for r in rows}
                if args.mode == "trip":
                    graph = build_graph(segments, {r["segment_id"]: r for r in rows}, nodes)
                    ctx["plan"] = lambda node, g=graph: plan_trip(g, node)
            except Exception:  # noqa: BLE001 — keep driving on stale data
                pass
        batch = [v.step(ctx, args.interval) for v in fleet]
        try:
            r = client.post("/api/gps/batch", json={"points": batch})
            r.raise_for_status()
            info = r.json()
            print(f"tick {tick}: {info.get('ingested', len(batch))} fixes in "
                  f"{info.get('ms', '?')} ms "
                  f"({info.get('fixes_per_sec', '?')}/s)", flush=True)
        except Exception as exc:  # noqa: BLE001 — failed ticks must not kill the stream
            print(f"tick {tick} failed: {exc}", file=sys.stderr)
        if args.once:
            break
        time.sleep(args.interval)
    print("simulator stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
