-- ============================================================================
-- TrafficFlowDB — Pan-India trunk network migration.
-- Adds the national highway backbone (27 city hubs + 35 trunk segments) and
-- links it to the Coimbatore metro graph via a connector segment, so routing
-- works end-to-end (e.g. Delhi -> Gandhipuram) on one connected graph.
-- Idempotent: safe to re-run on every API boot.
-- Distances are road-approximate km along the named NH corridors.
-- ============================================================================

-- Scope columns are ensured by schema.sql (runs before views); this file
-- only adds the national data. Idempotent: safe to re-run on every boot.

INSERT INTO intersection (intersection_id, name, latitude, longitude, scope) VALUES
    (101, 'Delhi',            28.6139,  77.2090, 'national'),
    (102, 'Chandigarh',       30.7333,  76.7794, 'national'),
    (103, 'Ludhiana',         30.9010,  75.8573, 'national'),
    (104, 'Jaipur',           26.9124,  75.7873, 'national'),
    (105, 'Agra',             27.1767,  78.0081, 'national'),
    (106, 'Lucknow',          26.8467,  80.9462, 'national'),
    (107, 'Kanpur',           26.4499,  80.3319, 'national'),
    (108, 'Varanasi',         25.3176,  82.9739, 'national'),
    (109, 'Patna',            25.5941,  85.1376, 'national'),
    (110, 'Kolkata',          22.5726,  88.3639, 'national'),
    (111, 'Bhubaneswar',      20.2961,  85.8245, 'national'),
    (112, 'Visakhapatnam',    17.6868,  83.2185, 'national'),
    (113, 'Vijayawada',       16.5062,  80.6480, 'national'),
    (114, 'Chennai',          13.0827,  80.2707, 'national'),
    (115, 'Bengaluru',        12.9716,  77.5946, 'national'),
    (116, 'Coimbatore Hub',   11.0200,  76.9750, 'national'),
    (117, 'Madurai',           9.9252,  78.1198, 'national'),
    (118, 'Kochi',             9.9312,  76.2673, 'national'),
    (119, 'Hyderabad',        17.3850,  78.4867, 'national'),
    (120, 'Nagpur',           21.1458,  79.0882, 'national'),
    (121, 'Bhopal',           23.2599,  77.4126, 'national'),
    (122, 'Indore',           22.7196,  75.8577, 'national'),
    (123, 'Surat',            21.1702,  72.8311, 'national'),
    (124, 'Mumbai',           19.0760,  72.8777, 'national'),
    (125, 'Pune',             18.5204,  73.8567, 'national'),
    (126, 'Ahmedabad',        23.0225,  72.5714, 'national'),
    (127, 'Guwahati',         26.1445,  91.7362, 'national')
ON CONFLICT (intersection_id) DO UPDATE SET scope = 'national';

SELECT setval('intersection_intersection_id_seq',
              (SELECT MAX(intersection_id) FROM intersection));

INSERT INTO road_segment
    (segment_id, start_intersection_id, end_intersection_id,
     segment_name, distance_km, speed_limit_kmh, road_type, capacity, is_active, scope)
VALUES
    (20, 101, 102, 'NH44 (Delhi - Chandigarh)',              250, 100, 'highway', 300, TRUE, 'trunk'),
    (21, 102, 103, 'NH44 (Chandigarh - Ludhiana)',           100,  80, 'highway', 250, TRUE, 'trunk'),
    (22, 101, 104, 'NH48 (Delhi - Jaipur)',                  280, 100, 'highway', 300, TRUE, 'trunk'),
    (23, 101, 105, 'Yamuna Expy (Delhi - Agra)',             230, 100, 'highway', 400, TRUE, 'trunk'),
    (24, 105, 106, 'Agra - Lucknow Expy',                    335, 100, 'highway', 400, TRUE, 'trunk'),
    (25, 106, 107, 'NH27 (Lucknow - Kanpur)',                 90,  80, 'highway', 250, TRUE, 'trunk'),
    (26, 105, 107, 'NH19 (Agra - Kanpur)',                   285,  80, 'highway', 250, TRUE, 'trunk'),
    (27, 107, 108, 'NH19 (Kanpur - Varanasi)',               330,  80, 'highway', 250, TRUE, 'trunk'),
    (28, 108, 109, 'NH31 (Varanasi - Patna)',                250,  80, 'highway', 250, TRUE, 'trunk'),
    (29, 109, 110, 'NH19/16 (Patna - Kolkata)',              580,  80, 'highway', 250, TRUE, 'trunk'),
    (30, 110, 111, 'NH16 (Kolkata - Bhubaneswar)',           440,  80, 'highway', 300, TRUE, 'trunk'),
    (31, 111, 112, 'NH16 (Bhubaneswar - Visakhapatnam)',     440,  80, 'highway', 300, TRUE, 'trunk'),
    (32, 112, 113, 'NH16 (Visakhapatnam - Vijayawada)',      350,  80, 'highway', 300, TRUE, 'trunk'),
    (33, 113, 114, 'NH16 (Vijayawada - Chennai)',            460,  80, 'highway', 300, TRUE, 'trunk'),
    (34, 114, 115, 'NH48 (Chennai - Bengaluru)',             350, 100, 'highway', 350, TRUE, 'trunk'),
    (35, 115, 116, 'NH44 (Bengaluru - Coimbatore)',          365, 100, 'highway', 350, TRUE, 'trunk'),
    (36, 116, 118, 'NH544 (Coimbatore - Kochi)',             190,  80, 'highway', 250, TRUE, 'trunk'),
    (37, 116, 117, 'NH83 (Coimbatore - Madurai)',            215,  80, 'highway', 250, TRUE, 'trunk'),
    (38, 117, 114, 'NH38/32 (Madurai - Chennai)',            460,  80, 'highway', 250, TRUE, 'trunk'),
    (39, 115, 119, 'NH44 (Bengaluru - Hyderabad)',           570, 100, 'highway', 350, TRUE, 'trunk'),
    (40, 119, 113, 'NH65 (Hyderabad - Vijayawada)',          270,  80, 'highway', 300, TRUE, 'trunk'),
    (41, 119, 120, 'NH44 (Hyderabad - Nagpur)',              500,  80, 'highway', 300, TRUE, 'trunk'),
    (42, 120, 121, 'NH46 (Nagpur - Bhopal)',                 350,  80, 'highway', 250, TRUE, 'trunk'),
    (43, 121, 122, 'NH52 (Bhopal - Indore)',                 195,  80, 'highway', 250, TRUE, 'trunk'),
    (44, 122, 123, 'NH53 (Indore - Surat)',                  365,  80, 'highway', 250, TRUE, 'trunk'),
    (45, 123, 124, 'NH48 (Surat - Mumbai)',                  290, 100, 'highway', 350, TRUE, 'trunk'),
    (46, 124, 125, 'Mumbai - Pune Expy',                     150, 100, 'highway', 400, TRUE, 'trunk'),
    (47, 125, 115, 'NH48 (Pune - Bengaluru)',                840,  80, 'highway', 300, TRUE, 'trunk'),
    (48, 104, 126, 'NH48 (Jaipur - Ahmedabad)',              660,  80, 'highway', 300, TRUE, 'trunk'),
    (49, 126, 123, 'NH48 (Ahmedabad - Surat)',               230, 100, 'highway', 350, TRUE, 'trunk'),
    (50, 105, 104, 'NH21 (Agra - Jaipur)',                   240,  80, 'highway', 250, TRUE, 'trunk'),
    (51, 120, 108, 'NH19 (Nagpur - Varanasi)',               600,  80, 'highway', 250, TRUE, 'trunk'),
    (52, 108, 106, 'NH31 (Varanasi - Lucknow)',              320,  80, 'highway', 250, TRUE, 'trunk'),
    (53, 110, 127, 'NH27 (Kolkata - Guwahati)',             1000,  80, 'highway', 250, TRUE, 'trunk'),
    (54, 116, 4,   'Coimbatore Hub - Peelamedu Link',         6.5,  50, 'arterial', 60, TRUE, 'connector')
ON CONFLICT (segment_id) DO NOTHING;

SELECT setval('road_segment_segment_id_seq',
              (SELECT MAX(segment_id) FROM road_segment));

-- Free-flow snapshot rows for the new segments (not fake traffic — just the
-- "no observations yet" default the analyzer overwrites on first fix).
INSERT INTO traffic_condition (segment_id, average_speed, vehicle_count, density, congestion_level)
SELECT s.segment_id, s.speed_limit_kmh::double precision, 0, 0, 'LOW'
FROM road_segment s
ON CONFLICT (segment_id) DO NOTHING;
