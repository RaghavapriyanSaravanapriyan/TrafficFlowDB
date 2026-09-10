"""TrafficFlowDB vehicle simulator — generates the live GPS stream.

Each simulated vehicle drives the real road graph: it advances along its
current segment every tick, picks a connected segment at each intersection,
and slows down on congested roads (creating realistic jam propagation).

Demo (the money shot):
    python -m simulator.vehicle_simulator --vehicles 50
    python -m simulator.vehicle_simulator --vehicles 50 --jam-segment 13 --jam-count 40

Usage:
    python -m simulator.vehicle_simulator [--vehicles N] [--interval SEC]
        [--base-url URL] [--jam-segment ID] [--jam-count N] [--once]
"""
from __future__ import annotations

import argparse
import random
import signal
import string
import sys
import time

import httpx

running = True


def _stop(*_args):
    global running
    running = False


signal.signal(signal.SIGINT, _stop)
signal.signal(signal.SIGTERM, _stop)


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


class Vehicle:
    def __init__(self, segments: list[dict], jam_segment: int | None):
        self.number = plate()
        self.vtype = pick_type()
        # Jam vehicles are pinned to the jammed segment for the demo.
        pool = [s for s in segments if s["id"] == jam_segment] if jam_segment else segments
        self.seg = random.choice(pool or segments)
        self.t = random.random()          # progress along segment 0..1
        self.fwd = random.random() < 0.5  # travel direction
        self.speed = self.seg["speed_limit"] * random.uniform(0.5, 0.9)
        self.jammed = jam_segment is not None

    def step(self, by_seg: dict[int, list[dict]], congestion: dict[int, str],
             interval: float, segments: list[dict]) -> dict:
        if self.jammed:
            # Crawl in place on the jammed road at walking pace.
            self.speed = random.uniform(5, 12)
            self.t = (self.t + 0.002) % 1.0
        else:
            level = congestion.get(self.seg["id"], "LOW")
            factor = {"LOW": 1.0, "MEDIUM": 0.55, "HIGH": 0.25}[level]
            target = self.seg["speed_limit"] * factor * random.uniform(0.7, 1.0)
            # Ease toward target speed (no teleporting between speeds).
            self.speed += (target - self.speed) * 0.4
            self.speed = max(4.0, self.speed)
            # Advance: km covered -> fraction of segment length.
            self.t += (self.speed / 3600 * interval) / max(self.seg["distance_km"], 0.1)
            if self.t >= 1.0 or self.t <= 0.0:
                self._next_segment(by_seg, segments)

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

    def _next_segment(self, by_seg: dict[int, list[dict]], segments: list[dict]):
        node = self.seg["b"] if self.fwd else self.seg["a"]
        options = [s for s in by_seg.get(node, []) if s["id"] != self.seg["id"]]
        self.seg = random.choice(options) if options else random.choice(segments)
        entering_at_a = node == self.seg["a"]
        self.fwd = entering_at_a
        self.t = 0.0 if entering_at_a else 1.0


def main() -> int:
    ap = argparse.ArgumentParser(description="TrafficFlowDB GPS simulator")
    ap.add_argument("--vehicles", type=int, default=60)
    ap.add_argument("--interval", type=float, default=2.0)
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--jam-segment", type=int, default=None,
                    help="pin --jam-count extra vehicles crawling on this segment")
    ap.add_argument("--jam-count", type=int, default=40)
    ap.add_argument("--once", action="store_true", help="send a single tick and exit")
    args = ap.parse_args()

    client = httpx.Client(base_url=args.base_url, timeout=15)
    try:
        segments = client.get("/api/network/segments").json()
    except Exception as exc:
        print(f"cannot reach API at {args.base_url}: {exc}", file=sys.stderr)
        return 1
    if not segments:
        print("no road segments in database — is the seed loaded?", file=sys.stderr)
        return 1

    by_seg: dict[int, list[dict]] = {}
    for s in segments:
        by_seg.setdefault(s["a"], []).append(s)
        by_seg.setdefault(s["b"], []).append(s)

    fleet = [Vehicle(segments, None) for _ in range(args.vehicles)]
    fleet += [Vehicle(segments, args.jam_segment) for _ in range(args.jam_count if args.jam_segment else 0)]
    print(f"simulating {len(fleet)} vehicles on {len(segments)} segments "
          f"(tick {args.interval}s) -> {args.base_url}")

    congestion: dict[int, str] = {}
    tick = 0
    while running:
        tick += 1
        if tick % 5 == 1:  # refresh congestion snapshot every ~5 ticks
            try:
                rows = client.get("/api/traffic/summary").json()
                congestion = {r["segment_id"]: r["congestion_level"] for r in rows}
            except Exception:  # noqa: BLE001 — keep driving on stale data
                pass
        batch = [v.step(by_seg, congestion, args.interval, segments) for v in fleet]
        try:
            r = client.post("/api/gps/batch", json={"points": batch})
            r.raise_for_status()
            n_high = sum(1 for v in congestion.values() if v == "HIGH")
            print(f"tick {tick}: sent {len(batch)} fixes "
                  f"(HIGH segments: {n_high})", flush=True)
        except Exception as exc:  # noqa: BLE001 — a failed tick must not kill the stream
            print(f"tick {tick} failed: {exc}", file=sys.stderr)
        if args.once:
            break
        time.sleep(args.interval)
    print("simulator stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
