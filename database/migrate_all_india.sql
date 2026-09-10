-- ============================================================================
-- TrafficFlowDB — All-India relaunch.
-- Retires the Coimbatore metro graph (and the old Coimbatore Hub shortcut):
-- the network is now 26 national hubs + 33 trunk corridors, south rewired
-- via NH85 Madurai - Kochi. Transactional demo traffic is wiped with it.
-- Idempotent: safe to re-run on every API boot.
-- ============================================================================

TRUNCATE gps_data, vehicle_position, traffic_history,
         route_segment, route, route_request, vehicle
         RESTART IDENTITY CASCADE;

-- Legacy rows (no-ops on fresh databases that never had them).
DELETE FROM road_segment WHERE scope IN ('metro', 'connector');
DELETE FROM road_segment WHERE segment_id IN (35, 36, 37, 54);
DELETE FROM intersection WHERE scope = 'metro';
DELETE FROM intersection WHERE intersection_id = 116;  -- old Coimbatore Hub

SELECT setval('intersection_intersection_id_seq',
              (SELECT MAX(intersection_id) FROM intersection));
SELECT setval('road_segment_segment_id_seq',
              (SELECT MAX(segment_id) FROM road_segment));

-- Free-flow defaults for anything missing a snapshot row.
INSERT INTO traffic_condition (segment_id, average_speed, vehicle_count, density, congestion_level)
SELECT s.segment_id, s.speed_limit_kmh::double precision, 0, 0, 'LOW'
FROM road_segment s
ON CONFLICT (segment_id) DO NOTHING;
