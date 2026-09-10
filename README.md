# TrafficFlowDB

**Real-time traffic intelligence on a relational database.** Vehicles stream GPS into
PostgreSQL, the database scores congestion per road segment, and a Dijkstra router
with live travel-time weights recommends the fastest route — re-computed as conditions change.

> One-line pitch: a real-time traffic intelligence system in which a relational
> database acts as the central layer for collecting, managing, analyzing, and serving
> continuously changing transportation data.

Live network: **12 real Coimbatore intersections, 19 road segments**. Traffic itself is
generated live by the simulator — no canned congestion.

---

## 1. Requirements

| Layer    | Requirement                                              |
|----------|----------------------------------------------------------|
| OS       | Linux (developed on Ubuntu), Docker 24+                  |
| Database | PostgreSQL 16 + PostGIS (provided via `docker-compose`) |
| Backend  | Python 3.12+ · FastAPI · Uvicorn · psycopg 3            |
| Frontend | Any modern browser (Leaflet via CDN for map tiles)       |
| Tests    | pytest                                                   |

Python dependencies are pinned in `requirements.txt`. No Node/build step — the
frontend is dependency-free vanilla HTML/CSS/JS.

## 2. Quickstart

```bash
# 1. Database (PostGIS)
docker compose up -d db

# 2. Backend (serves API + dashboard on :8000)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
# open http://localhost:8000

# 3. Traffic (second terminal — 60 vehicles, fix every 2 s)
python -m simulator.vehicle_simulator --vehicles 60
```

Fully containerized alternative: `docker compose up --build` (API on :8000).

Config lives in environment (see `.env.example`):
`DATABASE_URL`, `TRAFFIC_WINDOW_MINUTES` (rolling window, default 5),
`POLL_SECONDS` (WS/poll cadence, default 2).

## 3. Architecture

```
Vehicles / Simulator → POST /api/gps (batch) → map-match → PostgreSQL
    gps_data (raw) + vehicle_position (matched)
        → calculate_segment_traffic(segment) [stored procedure]
            → traffic_condition (snapshot) + traffic_history (trend)
                → Dijkstra on travel-time weights → route + route_segment
                    → REST + WebSocket /ws/live → Leaflet dashboard
```

Road network = graph: `intersection` rows are nodes, `road_segment` rows are
bidirectional edges. Every GPS insert refreshes **only its own segment** via the
stored procedure, so ingest stays O(1) per fix (~70 fixes/s measured on a laptop).

## 4. Database design (the core)

**Entities (3NF):** `users` (+`admin_profile`, `driver_profile` subclasses) ·
`vehicle` (+`car_detail`, `bus_detail`, `emergency_vehicle_detail` subclasses) ·
`intersection` · `road_segment` · `gps_data` (append-only raw feed) ·
`vehicle_position` (map-matched) · `traffic_condition` (one live row/segment) ·
`traffic_history` (append-only trend) · `route_request` → `route` → `route_segment`.

**EER specialization:** `VEHICLE → CAR / BUS / EMERGENCY_VEHICLE`,
`USER → ADMIN / DRIVER` (parent holds common attributes, child tables hold the rest).

**DBMS features demonstrated:**
- Indexes on `(vehicle_id, recorded_at)`, `(segment_id, recorded_at)`, congestion, endpoints
- Views: `live_traffic_summary` (dashboard reads this, not raw tables),
  `congested_segments`, `latest_positions`, `segment_stats_5min`
- Triggers: GPS validation (rejects bad coords/speeds/future timestamps),
  `vehicle.last_seen` maintenance, route-request guard, `pg_notify` on congestion change
- Stored procedures: `calculate_segment_traffic`, `refresh_all_traffic`,
  `get_congested_segments`, `find_nearby_segments` (Haversine map-match fallback)

Files: `database/schema.sql`, `views.sql`, `triggers.sql`, `procedures.sql`,
`seed_coimbatore.sql` (run in that order; `init_db()` does it automatically).

## 5. Traffic analysis

Rolling window (default 5 min) per segment:

```
density      = distinct_vehicles / capacity
HIGH         if avg_speed < 15 AND density > 0.75
MEDIUM       if avg_speed < 30 OR  density > 0.50
LOW          otherwise
```

The rule lives in `calculate_segment_traffic()` and is mirrored in
`backend/services/traffic_analyzer.py` (routing/simulator) — one rule, two call sites.

## 6. Routing

Dijkstra over the live graph. Edge weight = **estimated travel time**:

```
w = distance_km / effective_speed × 60          (minutes)
effective_speed = live avg (if observed)
                | speed_limit / congestion_multiplier (LOW 1.0 / MEDIUM 1.5 / HIGH 2.5)
```

Emergency `priority=true` routing uses free-flow (speed-limit) weights.
Every request persists `route_request → route → route_segment[]`, so recommendations
are auditable. Graph rows are cached 5 s — routes always reflect fresh traffic.

## 7. REST + WebSocket API

| Method | Endpoint                    | Purpose                                    |
|--------|-----------------------------|--------------------------------------------|
| GET    | `/api/health`               | readiness                                  |
| POST   | `/api/gps` · `/api/gps/batch` | ingest 1 / up to 500 fixes               |
| GET    | `/api/network/intersections`| graph nodes                                |
| GET    | `/api/network/segments`     | graph edges + geometry                     |
| GET    | `/api/network/positions`    | latest fix per vehicle                     |
| GET    | `/api/traffic/summary`      | `live_traffic_summary`                     |
| GET    | `/api/traffic/congested?level=` | worst-first congested roads            |
| GET    | `/api/traffic/segment/{id}` | snapshot + 60-pt history                   |
| POST   | `/api/traffic/refresh`      | recompute all segments                     |
| POST   | `/api/routes/request`       | `{source_id, destination_id, priority?}` → route |
| GET    | `/api/routes/history`       | past recommendations                       |
| GET    | `/api/vehicles` · POST      | fleet registry (+subtype rows)             |
| GET    | `/api/stats`                | headline metrics + query ms                |
| WS     | `/ws/live`                  | traffic + positions push every ~2 s        |

Interactive docs: `http://localhost:8000/docs`.

## 8. Demo script (the money shot)

1. `docker compose up -d db` → `uvicorn backend.main:app` → open `:8000`.
2. `python -m simulator.vehicle_simulator --vehicles 50` — map glows green.
3. `python -m simulator.vehicle_simulator --vehicles 50 --jam-segment 13 --jam-count 40`
   — Avinashi Rd turns red (`HIGH`: ~8 km/h, density > 0.75).
4. Request **Gandhipuram → Singanallur**: was `13 → 18`, now reroutes
   `1 → 15 → 9` (slightly longer, much faster). That reroute *is* the project.

## 9. Metrics (measured, local laptop)

~70 GPS fixes/s sustained ingest · stats endpoint ~2–3 ms ·
route computation < 5 ms on 12 nodes/19 edges · dashboard refresh 2 s (WS push + poll fallback).

## 10. Project layout

```
TrafficFlowDB/
├── backend/            # FastAPI: main, database pool, schemas, routes/, services/
│   └── services/       # geo (map-match), traffic_analyzer, route_optimizer, gps_processor
├── simulator/          # graph-driving GPS vehicle simulator
├── frontend/           # vanilla dashboard: index.html, styles.css, app.js (Leaflet)
├── database/           # schema, views, triggers, procedures, Coimbatore seed
├── tests/              # pytest: geo, congestion rules, Dijkstra (17 tests)
├── docker-compose.yml  # PostGIS + API · Dockerfile
└── requirements.txt
```

## 11. Testing

```bash
pytest tests -q
```

Covers Haversine/map-matching, the congestion classifier (LOW/MEDIUM/HIGH boundaries),
and Dijkstra: jam avoidance, free-flow preference, emergency priority, unreachable
pairs, and leg-total consistency. DB integration is exercised live via the demo script.

## 12. Methodology (for the report)

Requirement analysis → conceptual design (ER/EER: 9 entities, 2 specializations) →
logical design (relational mapping) → normalization to 3NF (positions reference
segments instead of duplicating road attributes; snapshot/history split) →
physical design (PK/FK/checks, 9 indexes, 4 views, 4 triggers, 4 procedures) →
implementation (API → simulator → analyzer → router → dashboard).
