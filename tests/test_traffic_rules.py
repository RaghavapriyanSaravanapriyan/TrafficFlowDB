from backend.services.traffic_analyzer import (
    classify,
    density_of,
    effective_speed_kmh,
    travel_time_min,
)


def test_classify_high():
    assert classify(10, 0.8) == "HIGH"


def test_classify_medium_by_speed():
    assert classify(25, 0.1) == "MEDIUM"


def test_classify_medium_by_density():
    assert classify(55, 0.6) == "MEDIUM"


def test_classify_low():
    assert classify(55, 0.1) == "LOW"


def test_density():
    assert density_of(20, 40) == 0.5
    assert density_of(5, 0) == 0.0


def test_travel_time():
    assert travel_time_min(60, 60) == 60.0
    assert travel_time_min(30, 60) == 30.0


def test_effective_speed_prefers_live():
    assert effective_speed_kmh(12, 30, 50, "HIGH") == 12


def test_effective_speed_derates_limit_without_data():
    assert effective_speed_kmh(0, 0, 50, "HIGH") == 20.0  # 50 / 2.5
    assert effective_speed_kmh(0, 0, 50, "LOW") == 50.0
