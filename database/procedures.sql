-- ============================================================================
-- TrafficFlowDB — Stored procedures / functions (DBMS showcase)
-- The API calls these instead of inlining analytics SQL, so congestion
-- rules live in exactly one place: the database.
--
-- Congestion rule (shared with the Python analyzer, kept in sync):
--   density = live_vehicles / capacity
--   HIGH   if avg_speed < 15 AND density > 0.75
--   MEDIUM if avg_speed < 30 OR  density > 0.50
--   LOW    otherwise
-- ============================================================================

-- Recompute traffic for ONE segment from the last `p_window_minutes` of
-- positions. Upserts traffic_condition + appends traffic_history.
-- Returns the new congestion level.
CREATE OR REPLACE FUNCTION calculate_segment_traffic(
    p_segment_id      INTEGER,
    p_window_minutes  INTEGER DEFAULT 5
)
RETURNS VARCHAR AS $$
DECLARE
    v_count    INTEGER;
    v_avg      DOUBLE PRECISION;
    v_capacity INTEGER;
    v_limit    INTEGER;
    v_density  DOUBLE PRECISION;
    v_level    VARCHAR(10);
BEGIN
    SELECT capacity, speed_limit_kmh INTO v_capacity, v_limit
    FROM road_segment WHERE segment_id = p_segment_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown segment %', p_segment_id;
    END IF;

    SELECT COUNT(DISTINCT vehicle_id), COALESCE(AVG(speed_kmh), v_limit)
    INTO v_count, v_avg
    FROM vehicle_position
    WHERE segment_id = p_segment_id
      AND recorded_at > NOW() - (p_window_minutes || ' minutes')::INTERVAL;

    v_density := CASE WHEN v_capacity > 0
                      THEN v_count::double precision / v_capacity
                      ELSE 0 END;

    IF v_avg < 15 AND v_density > 0.75 THEN
        v_level := 'HIGH';
    ELSIF v_avg < 30 OR v_density > 0.50 THEN
        v_level := 'MEDIUM';
    ELSE
        v_level := 'LOW';
    END IF;

    INSERT INTO traffic_condition
        (segment_id, average_speed, vehicle_count, density, congestion_level, calculated_at)
    VALUES (p_segment_id, v_avg, v_count, v_density, v_level, NOW())
    ON CONFLICT (segment_id) DO UPDATE SET
        average_speed    = EXCLUDED.average_speed,
        vehicle_count    = EXCLUDED.vehicle_count,
        density          = EXCLUDED.density,
        congestion_level = EXCLUDED.congestion_level,
        calculated_at    = EXCLUDED.calculated_at;

    INSERT INTO traffic_history
        (segment_id, average_speed, vehicle_count, density, congestion_level)
    VALUES (p_segment_id, v_avg, v_count, v_density, v_level);

    RETURN v_level;
END;
$$ LANGUAGE plpgsql;

-- Recompute traffic for EVERY active segment. Called by the API on a timer
-- and by the /api/traffic/refresh endpoint.
CREATE OR REPLACE FUNCTION refresh_all_traffic(p_window_minutes INTEGER DEFAULT 5)
RETURNS TABLE (segment_id INTEGER, congestion_level VARCHAR) AS $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN SELECT s.segment_id FROM road_segment s WHERE s.is_active LOOP
        PERFORM calculate_segment_traffic(r.segment_id, p_window_minutes);
    END LOOP;
    RETURN QUERY SELECT t.segment_id, t.congestion_level FROM traffic_condition t;
END;
$$ LANGUAGE plpgsql;

-- Congested segments at or above a severity ('MEDIUM' returns MEDIUM+HIGH).
CREATE OR REPLACE FUNCTION get_congested_segments(p_level VARCHAR DEFAULT 'MEDIUM')
RETURNS TABLE (
    segment_id       INTEGER,
    segment_name     VARCHAR,
    average_speed    DOUBLE PRECISION,
    vehicle_count    INTEGER,
    density          DOUBLE PRECISION,
    congestion_level VARCHAR
) AS $$
BEGIN
    IF p_level = 'HIGH' THEN
        RETURN QUERY
        SELECT l.segment_id, l.segment_name, l.average_speed,
               l.vehicle_count, l.density, l.congestion_level
        FROM live_traffic_summary l
        WHERE l.congestion_level = 'HIGH'
        ORDER BY l.density DESC;
    ELSE
        RETURN QUERY
        SELECT l.segment_id, l.segment_name, l.average_speed,
               l.vehicle_count, l.density, l.congestion_level
        FROM live_traffic_summary l
        WHERE l.congestion_level IN ('MEDIUM', 'HIGH')
        ORDER BY CASE l.congestion_level WHEN 'HIGH' THEN 0 ELSE 1 END,
                 l.density DESC;
    END IF;
END;
$$ LANGUAGE plpgsql;

-- Nearest active segments to a point (Haversine, km). Used by the API's
-- map-matcher fallback and debuggable straight from psql.
CREATE OR REPLACE FUNCTION find_nearby_segments(
    p_lat   DOUBLE PRECISION,
    p_lon   DOUBLE PRECISION,
    p_limit INTEGER DEFAULT 3
)
RETURNS TABLE (segment_id INTEGER, segment_name VARCHAR, dist_km DOUBLE PRECISION) AS $$
BEGIN
    RETURN QUERY
    SELECT
        rs.segment_id,
        rs.segment_name,
        (6371 * acos(LEAST(1, GREATEST(-1,
            cos(radians(p_lat)) * cos(radians(
                (i1.latitude + i2.latitude) / 2)) *
            cos(radians(
                (i1.longitude + i2.longitude) / 2) - radians(p_lon)) +
            sin(radians(p_lat)) * sin(radians(
                (i1.latitude + i2.latitude) / 2))
        )))) AS dist_km
    FROM road_segment rs
    JOIN intersection i1 ON i1.intersection_id = rs.start_intersection_id
    JOIN intersection i2 ON i2.intersection_id = rs.end_intersection_id
    WHERE rs.is_active
    ORDER BY dist_km
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql;
