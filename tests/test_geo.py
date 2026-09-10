from backend.services.geo import haversine_km, match_segment


def test_haversine_delhi_to_agra():
    # Real national pair, ~178 km apart straight-line.
    d = haversine_km(28.6139, 77.2090, 27.1767, 78.0081)
    assert 170 < d < 190


def test_haversine_zero():
    assert haversine_km(11.0, 77.0, 11.0, 77.0) == 0.0


def _segs():
    return [
        {"segment_id": 1, "start_lat": 11.0, "start_lon": 77.0,
         "end_lat": 11.0, "end_lon": 77.02},
        {"segment_id": 2, "start_lat": 11.1, "start_lon": 77.1,
         "end_lat": 11.1, "end_lon": 77.12},
    ]


def test_match_segment_picks_nearest():
    m = match_segment(11.0005, 77.01, _segs())
    assert m is not None and m["segment_id"] == 1


def test_match_segment_returns_none_when_far():
    assert match_segment(0.0, 0.0, _segs()) is None
