"""Dijkstra route optimizer with dynamic, traffic-aware edge weights.

Graph model: intersections are nodes, active road segments are (bidirectional)
edges. Edge weight = estimated travel time in minutes:

    w = distance_km / effective_speed * 60

where effective_speed is the live average speed when vehicles were observed
recently, otherwise the speed limit derated by the congestion multiplier
(LOW 1.0 / MEDIUM 1.5 / HIGH 2.5). Emergency `priority` routing uses pure
free-flow (speed limit) weights.
"""
from __future__ import annotations

import heapq
import time

from .traffic_analyzer import CONGESTION_MULTIPLIER, travel_time_min

_graph_cache: dict = {"at": 0.0, "adj": {}, "segments": {}, "nodes": {}}
GRAPH_TTL_SEC = 5.0


def refresh_graph(conn) -> dict:
    """Reload adjacency + segment/node rows; cached for GRAPH_TTL_SEC."""
    now = time.time()
    if now - _graph_cache["at"] < GRAPH_TTL_SEC and _graph_cache["adj"]:
        return _graph_cache
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT rs.segment_id, rs.start_intersection_id, rs.end_intersection_id,
                   rs.segment_name, rs.distance_km, rs.speed_limit_kmh,
                   rs.capacity, rs.road_type,
                   COALESCE(tc.average_speed, rs.speed_limit_kmh::double precision),
                   COALESCE(tc.vehicle_count, 0),
                   COALESCE(tc.congestion_level, 'LOW')
            FROM road_segment rs
            LEFT JOIN traffic_condition tc ON tc.segment_id = rs.segment_id
            WHERE rs.is_active
            """
        )
        seg_rows = cur.fetchall()
        cur.execute("SELECT intersection_id, name, latitude, longitude FROM intersection")
        node_rows = cur.fetchall()

    adj: dict[int, list[tuple[int, int]]] = {}
    segments: dict[int, dict] = {}
    for (sid, a, b, name, dist, limit, cap, rtype, avg, cnt, lvl) in seg_rows:
        segments[sid] = {
            "segment_id": sid, "a": a, "b": b, "name": name,
            "distance_km": float(dist), "speed_limit": int(limit),
            "capacity": int(cap), "road_type": rtype,
            "avg_speed": float(avg), "vehicle_count": int(cnt), "level": lvl,
        }
        adj.setdefault(a, []).append((b, sid))
        adj.setdefault(b, []).append((a, sid))  # two-way street model

    _graph_cache.update({
        "at": now, "adj": adj, "segments": segments,
        "nodes": {r[0]: {"id": r[0], "name": r[1], "lat": r[2], "lon": r[3]} for r in node_rows},
    })
    return _graph_cache


def _weight(seg: dict, priority: bool) -> tuple[float, float]:
    """(weight_minutes, speed_used)."""
    if priority:
        speed = float(seg["speed_limit"])
    elif seg["vehicle_count"] > 0:
        speed = max(seg["avg_speed"], 5.0)
    else:
        speed = max(seg["speed_limit"] / CONGESTION_MULTIPLIER.get(seg["level"], 1.0), 5.0)
    return travel_time_min(seg["distance_km"], speed), speed


def dijkstra(graph: dict, source: int, target: int, priority: bool = False) -> dict | None:
    adj, segments = graph["adj"], graph["segments"]
    if source not in adj or target not in adj:
        return None
    dist = {source: 0.0}
    prev: dict[int, tuple[int, int]] = {}  # node -> (prev_node, segment_id)
    pq: list[tuple[float, int]] = [(0.0, source)]
    visited: set[int] = set()
    while pq:
        d, u = heapq.heappop(pq)
        if u in visited:
            continue
        visited.add(u)
        if u == target:
            break
        for v, sid in adj.get(u, []):
            w, _ = _weight(segments[sid], priority)
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = (u, sid)
                heapq.heappush(pq, (nd, v))
    if target not in dist:
        return None

    # Reconstruct node + segment path.
    nodes, seg_ids = [target], []
    u = target
    while u != source:
        p, sid = prev[u]
        seg_ids.append(sid)
        nodes.append(p)
        u = p
    nodes.reverse()
    seg_ids.reverse()

    total_dist, traffic_w = 0.0, 0.0
    legs = []
    for sid in seg_ids:
        seg = segments[sid]
        w, speed = _weight(seg, priority)
        total_dist += seg["distance_km"]
        traffic_w += CONGESTION_MULTIPLIER.get(seg["level"], 1.0) * seg["distance_km"]
        legs.append({
            "segment_id": sid,
            "segment_name": seg["name"],
            "distance_km": round(seg["distance_km"], 3),
            "estimated_min": round(w, 2),
            "speed_used_kmh": round(speed, 1),
            "congestion": seg["level"],
        })
    traffic_score = round(traffic_w / total_dist, 3) if total_dist else 0.0
    return {
        "node_path": nodes,
        "segment_path": seg_ids,
        "legs": legs,
        "total_distance_km": round(total_dist, 3),
        "estimated_time_min": round(dist[target], 2),
        "traffic_score": traffic_score,
    }
