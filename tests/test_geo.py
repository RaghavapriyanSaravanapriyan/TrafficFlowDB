from backend.services.geo import haversine_km, match_segment


def test_haversine_gandhipuram_to_race_course():
    # Real Coimbatore pair, ~2.3 km apart.
    d = haversine_km(11.0183, 76.9678, 11.0070, 76.9860)
    assert 2.0 < d < 2.7


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
