-- ============================================================================
-- TrafficFlowDB — Triggers
-- 1. Validate raw GPS fixes (reject impossible coordinates/speeds early).
-- 2. Keep vehicle.last_seen fresh on every position insert (drives the
--    "active vehicles" metric without an extra application query).
-- 3. Guard route requests (source != destination) at the DB layer too.
-- 4. Notify listeners on congestion change via pg_notify (WS push hook).
-- ============================================================================

-- ------------------------------------------------------- 1. GPS validation --
CREATE OR REPLACE FUNCTION fn_validate_gps_data()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.latitude  < -90  OR NEW.latitude  > 90
    OR NEW.longitude < -180 OR NEW.longitude > 180 THEN
        RAISE EXCEPTION 'Invalid coordinates: %, %', NEW.latitude, NEW.longitude;
    END IF;
    IF NEW.speed_kmh < 0 OR NEW.speed_kmh > 300 THEN
        RAISE EXCEPTION 'Invalid speed: % km/h', NEW.speed_kmh;
    END IF;
    IF NEW.recorded_at > NOW() + INTERVAL '5 minutes' THEN
        RAISE EXCEPTION 'Timestamp is too far in the future: %', NEW.recorded_at;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_gps_data_validate ON gps_data;
CREATE TRIGGER trg_gps_data_validate
    BEFORE INSERT ON gps_data
    FOR EACH ROW EXECUTE FUNCTION fn_validate_gps_data();

DROP TRIGGER IF EXISTS trg_position_validate ON vehicle_position;
CREATE TRIGGER trg_position_validate
    BEFORE INSERT ON vehicle_position
    FOR EACH ROW EXECUTE FUNCTION fn_validate_gps_data();

-- ------------------------------------------------- 2. vehicle last_seen ----
CREATE OR REPLACE FUNCTION fn_touch_vehicle_last_seen()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE vehicle SET last_seen = NEW.recorded_at
    WHERE vehicle_id = NEW.vehicle_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_position_touch_last_seen ON vehicle_position;
CREATE TRIGGER trg_position_touch_last_seen
    AFTER INSERT ON vehicle_position
    FOR EACH ROW EXECUTE FUNCTION fn_touch_vehicle_last_seen();

-- ------------------------------------------------ 3. route request guard ---
CREATE OR REPLACE FUNCTION fn_validate_route_request()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.source_intersection_id = NEW.destination_intersection_id THEN
        RAISE EXCEPTION 'Source and destination must differ';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_route_request_validate ON route_request;
CREATE TRIGGER trg_route_request_validate
    BEFORE INSERT OR UPDATE ON route_request
    FOR EACH ROW EXECUTE FUNCTION fn_validate_route_request();

-- ------------------------------------------- 4. congestion change notify ---
CREATE OR REPLACE FUNCTION fn_notify_congestion_change()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.congestion_level IS DISTINCT FROM NEW.congestion_level THEN
        PERFORM pg_notify(
            'congestion_change',
            json_build_object(
                'segment_id', NEW.segment_id,
                'old', COALESCE(OLD.congestion_level, 'NONE'),
                'new', NEW.congestion_level
            )::text
        );
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_congestion_notify ON traffic_condition;
CREATE TRIGGER trg_congestion_notify
    AFTER UPDATE ON traffic_condition
    FOR EACH ROW EXECUTE FUNCTION fn_notify_congestion_change();
