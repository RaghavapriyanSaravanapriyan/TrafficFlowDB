"""Dijkstra tests on a synthetic graph (no database needed).

    1 ---- s1 (2 km, fast) ---- 2 ---- s2 (2 km, fast) ---- 3
    1 ---- s3 (3 km, jammed) -- 3
"""
from backend.services.route_optimizer import dijkstra


def _graph(level_s3="HIGH", avg_s3=8.0, count_s3=50):
    segments = {
        1: {"segment_id": 1, "a": 1, "b": 2, "name": "s1",
            "distance_km": 2.0, "speed_limit": 50, "capacity": 60,
            "road_type": "arterial", "avg_speed": 48.0,
            "vehicle_count": 5, "level": "LOW"},
        2: {"segment_id": 2, "a": 2, "b": 3, "name": "s2",
            "distance_km": 2.0, "speed_limit": 50, "capacity": 60,
            "road_type": "arterial", "avg_speed": 45.0,
            "vehicle_count": 4, "level": "LOW"},
        3: {"segment_id": 3, "a": 1, "b": 3, "name": "s3-direct",
            "distance_km": 3.0, "speed_limit": 50, "capacity": 40,
            "road_type": "arterial", "avg_speed": avg_s3,
            "vehicle_count": count_s3, "level": level_s3},
    }
    adj = {1: [(2, 1), (3, 3)], 2: [(1, 1), (3, 2)], 3: [(2, 2), (1, 3)]}
    nodes = {i: {"id": i, "name": f"N{i}", "lat": 0.0, "lon": 0.0} for i in (1, 2, 3)}
    return {"adj": adj, "segments": segments, "nodes": nodes}


def test_avoids_jammed_direct_road():
    r = dijkstra(_graph(), 1, 3)
    assert r is not None
    assert r["segment_path"] == [1, 2]  # longer, but much faster


def test_uses_direct_road_when_free():
    r = dijkstra(_graph(level_s3="LOW", avg_s3=50.0, count_s3=2), 1, 3)
    assert r is not None
    assert r["segment_path"] == [3]


def test_priority_ignores_congestion():
    r = dijkstra(_graph(), 1, 3, priority=True)
    assert r is not None
    assert r["segment_path"] == [3]  # free-flow: 3 km direct wins


def test_unreachable_returns_none():
    g = _graph()
    g["adj"] = {1: [], 9: []}
    g["nodes"][9] = {"id": 9, "name": "N9", "lat": 0.0, "lon": 0.0}
    assert dijkstra(g, 1, 9) is None


def test_totals_are_consistent():
    r = dijkstra(_graph(), 1, 3)
    assert r["total_distance_km"] == 4.0
    assert r["estimated_time_min"] > 0
    assert abs(sum(l["estimated_min"] for l in r["legs"]) - r["estimated_time_min"]) < 0.05


def test_distance_mode_picks_shortest_km():
    r = dijkstra(_graph(), 1, 3, mode="distance")
    assert r is not None
    assert r["segment_path"] == [3]
    assert r["total_distance_km"] == 3.0
    # ...but its ETA (live speeds) is worse than the fastest route's.
    fast = dijkstra(_graph(), 1, 3, mode="time")
    assert r["estimated_time_min"] > fast["estimated_time_min"]
    assert fast["total_distance_km"] > r["total_distance_km"]


def test_modes_agree_when_free():
    g = _graph(level_s3="LOW", avg_s3=50.0, count_s3=2)
    assert dijkstra(g, 1, 3, mode="time")["segment_path"] == [3]
    assert dijkstra(g, 1, 3, mode="distance")["segment_path"] == [3]
