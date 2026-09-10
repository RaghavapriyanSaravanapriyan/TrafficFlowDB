from backend.services.sqllab import SAMPLES, check


def test_select_passes():
    ok, _ = check("SELECT * FROM vehicle LIMIT 5;")
    assert ok


def test_with_passes():
    ok, _ = check("WITH a AS (SELECT 1) SELECT * FROM a")
    assert ok


def test_case_and_whitespace_tolerant():
    ok, _ = check("  select 1")
    assert ok


def test_insert_blocked():
    ok, reason = check("INSERT INTO vehicle DEFAULT VALUES")
    assert not ok and "read-only" in reason


def test_update_delete_drop_blocked():
    for q in ("UPDATE vehicle SET x=1", "DELETE FROM vehicle",
              "DROP TABLE vehicle", "TRUNCATE vehicle"):
        ok, _ = check(q)
        assert not ok, q


def test_stacking_blocked():
    ok, reason = check("SELECT 1; DROP TABLE vehicle;")
    assert not ok and "stacking" in reason


def test_empty_and_oversize_blocked():
    assert not check("")[0]
    assert not check("SELECT " + "x" * 9000)[0]


def test_samples_are_valid_selects():
    assert len(SAMPLES) == 6
    titles = [t for t, _ in SAMPLES]
    assert len(set(titles)) == 6
    for title, sql in SAMPLES:
        ok, reason = check(sql)
        assert ok, f"{title}: {reason}"
