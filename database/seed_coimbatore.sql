-- ============================================================================
-- TrafficFlowDB — Real road network seed: Coimbatore, Tamil Nadu (IN)
-- 12 intersections (graph nodes) + 19 road segments (graph edges).
-- Coordinates are real-world (WGS84). Distances are road-approximate km.
-- Re-runnable: all inserts are ON CONFLICT DO NOTHING.
-- Live vehicles/traffic are generated at runtime by the simulator — nothing
-- here is fake traffic.
-- ============================================================================

INSERT INTO intersection (intersection_id, name, latitude, longitude) VALUES
    (1,  'Gandhipuram',    11.0183, 76.9678),
    (2,  'RS Puram',       11.0075, 76.9400),
    (3,  'Saibaba Colony', 11.0288, 76.9379),
    (4,  'Peelamedu',      11.0267, 77.0066),
    (5,  'Hope College',   11.0300, 76.9930),
    (6,  'Singanallur',    10.9995, 77.0210),
    (7,  'Ukkadam',        10.9884, 76.9617),
    (8,  'Town Hall',      10.9915, 76.9659),
    (9,  'Race Course',    11.0070, 76.9860),
    (10, 'Vadavalli',      11.0360, 76.9100),
    (11, 'Thudiyalur',     11.0820, 76.9380),
    (12, 'Saravanampatti', 11.0860, 77.0210)
ON CONFLICT (intersection_id) DO NOTHING;

-- Keep the serial sequence in sync after explicit ids.
SELECT setval('intersection_intersection_id_seq',
              (SELECT MAX(intersection_id) FROM intersection));

INSERT INTO road_segment
    (segment_id, start_intersection_id, end_intersection_id,
     segment_name, distance_km, speed_limit_kmh, road_type, capacity, is_active)
VALUES
    (1,  1, 9,  'Dr Nanjappa Rd (Gandhipuram - Race Course)', 2.2, 50, 'arterial',  60, TRUE),
    (2,  9, 2,  'Race Course - RS Puram Rd',                  4.8, 50, 'arterial',  60, TRUE),
    (3,  2, 3,  'Bharathi Park Rd (RS Puram - Saibaba Colony)', 2.4, 40, 'collector', 40, TRUE),
    (4,  3, 10, 'Vadavalli Rd (Saibaba Colony - Vadavalli)',  3.6, 40, 'collector', 30, TRUE),
    (5,  3, 11, 'Mettupalayam Rd (Saibaba Colony - Thudiyalur)', 5.9, 60, 'arterial', 50, TRUE),
    (6,  11, 12, 'Sathy Rd (Thudiyalur - Saravanampatti)',    9.0, 60, 'arterial',  50, TRUE),
    (7,  12, 4,  'Sathy Rd (Saravanampatti - Peelamedu)',     6.8, 60, 'arterial',  60, TRUE),
    (8,  4, 5,  'Avinashi Rd (Peelamedu - Hope College)',     1.8, 50, 'arterial',  60, TRUE),
    (9,  5, 6,  'Trichy Rd (Hope College - Singanallur)',     3.2, 50, 'arterial',  50, TRUE),
    (10, 6, 8,  'Trichy Rd (Singanallur - Town Hall)',        6.1, 50, 'arterial',  50, TRUE),
    (11, 8, 7,  'Ukkadam - Town Hall Rd',                     0.7, 30, 'local',     30, TRUE),
    (12, 7, 2,  'Sungam - RS Puram Bypass',                   3.2, 50, 'arterial',  50, TRUE),
    (13, 1, 4,  'Avinashi Rd (Gandhipuram - Peelamedu)',      4.2, 80, 'highway',   80, TRUE),
    (14, 1, 8,  'Good Shed St (Gandhipuram - Town Hall)',     3.0, 50, 'arterial',  60, TRUE),
    (15, 9, 5,  'Huzur Rd (Race Course - Hope College)',      2.1, 40, 'collector', 40, TRUE),
    (16, 10, 2, 'Marthandam Rd (Vadavalli - RS Puram)',       4.5, 40, 'collector', 30, TRUE),
    (17, 7, 9,  'Sungam - Race Course Link',                  3.0, 40, 'collector', 40, TRUE),
    (18, 4, 6,  'Peelamedu - Singanallur Rd',                 3.5, 40, 'collector', 40, TRUE),
    (19, 9, 8,  'Race Course - Town Hall Rd',                 2.6, 50, 'arterial',  50, TRUE)
ON CONFLICT (segment_id) DO NOTHING;

SELECT setval('road_segment_segment_id_seq',
              (SELECT MAX(segment_id) FROM road_segment));

-- Initialise one traffic snapshot row per segment so the map and router work
-- before the first GPS fix arrives (free-flow defaults, not fake traffic).
INSERT INTO traffic_condition (segment_id, average_speed, vehicle_count, density, congestion_level)
SELECT s.segment_id, s.speed_limit_kmh::double precision, 0, 0, 'LOW'
FROM road_segment s
ON CONFLICT (segment_id) DO NOTHING;
