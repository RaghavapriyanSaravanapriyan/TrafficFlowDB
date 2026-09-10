# TrafficFlowDB

**Real-time traffic intelligence on a relational database — across India.**
Vehicles stream GPS into PostgreSQL, the database scores congestion per road
segment, and a Dijkstra router with live travel-time weights recommends the
fastest route. The dashboard shows every query happening under the hood, live.

> One-line pitch: a real-time traffic intelligence system in which a relational
> database acts as the central layer for collecting, managing, analyzing, and serving
> continuously changing transportation data.

Live network: **27 national highway hubs + 12 Coimbatore metro intersections,
54 segments** — one connected graph, so `Delhi → Gandhipuram` routes in a single
query. Traffic itself is generated live — no canned congestion.

---

## 1. Requirements

| Layer    | Requirement                                              |
|----------|----------------------------------------------------------|
| OS       | Linux (developed on Ubuntu), Docker 24+                  |
| Database | PostgreSQL 16 + PostGIS (provided via `docker-compose`) |
| Backend  | Python 3.12+ · FastAPI · Uvicorn · psycopg 3            |
| Frontend | Any modern browser (Leaflet + OSM tiles via CDN)         |
| Tests    | pytest                                                   |

Pinned in `requirements.txt`. No Node/build step — dependency-free vanilla HTML/CSS/JS.

## 2. Quickstart

```bash
docker compose up -d db
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
# open http://localhost:8000  (?theme=dark for dark mode)

python -m simulator.vehicle_simulator --vehicles 70   # second terminal
```

`docker compose up --build` runs the API containerized instead.
Config: `DATABASE_URL`, `TRAFFIC_WINDOW_MINUTES`, `POLL_SECONDS` (see `.env.example`;
all three are also tunable live via `PUT /api/config` / the Customize drawer).

## 3. Architecture

```
Simulator fleet → POST /api/gps/batch → map-match → PostgreSQL
    gps_data (raw) + vehicle_position (matched)
        → calculate_segment_traffic(seg, window) [stored proc, reads traffic_thresholds]
            → traffic_condition (snapshot) + traffic_history (trend)
                → Dijkstra on travel-time weights → route + route_segment
                    → REST + WebSocket /ws/live (traffic, positions, query log)
                        → glass dashboard: map, console, SQL terminal
```

`intersection` rows are nodes, `road_segment` rows are bidirectional edges
(`scope`: `metro` / `trunk` / `connector`). Each GPS insert refreshes **only its
segment** — ingest stays O(1) per fix (~60 fixes/s measured with live re-scoring).

## 4. Database design (the core)

**Entities (3NF):** `users` (+`admin_profile`, `driver_profile`) ·
`vehicle` (+`car_detail`, `bus_detail`, `emergency_vehicle_detail`) ·
`intersection` · `road_segment` · `gps_data` (append-only) ·
`vehicle_position` (map-matched) · `traffic_condition` (one live row/segment) ·
`traffic_history` (trend) · `traffic_thresholds` (live rulebook singleton) ·
`route_request` → `route` → `route_segment`.

**EER:** `VEHICLE → CAR / BUS / EMERGENCY_VEHICLE`, `USER → ADMIN / DRIVER`.

**DBMS features:** 9 time/segment/congestion indexes · views
(`live_traffic_summary`, `congested_segments`, `latest_positions`,
`segment_stats_5min`) · triggers (GPS validation, `last_seen`, route guard,
`pg_notify` on congestion change) · procedures (`calculate_segment_traffic`,
`refresh_all_traffic`, `get_congested_segments`, `find_nearby_segments`).

Files: `database/schema.sql`, `views.sql`, `triggers.sql`, `procedures.sql`,
`seed_coimbatore.sql`, `migrate_india.sql` — applied in order by `init_db()`.

## 5. Traffic analysis

Rolling window (default 5 min, live-tunable) per segment.
Rule lives in `traffic_thresholds`, read by the procedure on every call:

```
density  = distinct_vehicles / capacity
HIGH     if avg_speed < high_speed AND density > high_density   (15, 0.75)
MEDIUM   if avg_speed < med_speed  OR  density > med_density     (30, 0.50)
LOW      otherwise
```

## 6. Routing

Dijkstra, weight = live travel time `w = distance / effective_speed × 60`
(live average when observed, else limit derated by congestion multiplier
LOW 1.0 / MEDIUM 1.5 / HIGH 2.5). Emergency `priority=true` uses free-flow
weights. Requests persist `route_request → route → route_segment[]`.
Delhi → Mumbai (1,460 km, 4 legs) computes in ~0.05 ms.

## 7. Console — ask in plain English

`POST /api/command {"text": "..."}` (parser in `backend/services/command.py`,
unit-tested). Dashboard: type or press `Ctrl K`. Clickable example chips included.

```
Route Delhi to Mumbai        Delhi to Chennai          (bare "A to B" works too)
Route Gandhipuram to Singanallur
Traffic on Avinashi Rd       Where is it jammed?       Stats
Jam Sathy Rd                 Jam NH44 50               Rush hour    Reset
```

Ambiguous names return pick-lists; unknown input returns examples, never silence.

## 8. REST + WebSocket API

| Method | Endpoint                        | Purpose                                        |
|--------|---------------------------------|------------------------------------------------|
| GET    | `/api/health`                   | readiness                                      |
| POST   | `/api/gps` · `/api/gps/batch`   | ingest 1 / ≤500 fixes                          |
| GET    | `/api/network/*`                | intersections, segments (+scope), live positions |
| GET    | `/api/traffic/summary`          | live snapshot (drives map + table)             |
| GET    | `/api/traffic/congested?level=` | worst-first                                    |
| GET    | `/api/traffic/segment/{id}`     | snapshot + 60-pt history                       |
| POST   | `/api/traffic/refresh`          | recompute all segments                         |
| POST   | `/api/routes/request`           | `{source_id, destination_id, priority?}`       |
| GET    | `/api/routes/history`           | past recommendations                           |
| GET/PUT| `/api/config`                   | window, poll cadence, congestion thresholds    |
| POST   | `/api/scenarios/jam`            | inject N crawling vehicles on a segment        |
| POST   | `/api/scenarios/rush-hour`      | peak load on top-capacity corridors            |
| POST   | `/api/scenarios/reset`          | remove scenario vehicles, recompute            |
| POST   | `/api/command` · GET `/api/command/examples` | NL console                         |
| GET    | `/api/logs?since=&limit=`       | live query-log ring buffer                     |
| WS     | `/ws/live`                      | traffic + positions + log entries every tick   |

Docs: `:8000/docs`. The **Under the hood** terminal streams the query log
(SQL text + ms + context) with category filters, pause, and running averages —
kept in a bounded in-memory ring so logging never slows ingest.

## 9. Demo script

1. `docker compose up -d db` → `uvicorn backend.main:app` → `:8000`.
2. `python -m simulator.vehicle_simulator --vehicles 70` — India + metro light up.
3. Console: `Jam NH44` (or drawer → Cause jam) — corridor turns red.
4. Console: `Route Delhi to Mumbai` — watch it swerve around the jam.
5. Open **Under the hood** while doing 3–4: every `INSERT`, `calculate_segment_traffic`
   and Dijkstra lands in the terminal with timings.

## 10. Metrics (measured)

~60 fixes/s sustained ingest with per-fix re-scoring · stats ~3–8 ms ·
Dijkstra 39 nodes/54 edges ~0.05 ms · dashboard tick 2 s (WS push + poll fallback).

## 11. Layout

```
backend/   main, database pool, runtime config, querylog, schemas,
           routes/ (gps, network, traffic, routing, vehicles, stats,
                    config, scenarios, command, logs)
           services/ (geo, gps_processor, traffic_analyzer,
                      route_optimizer, scenarios, command)
simulator/ graph-driving GPS fleet (60/40 metro/trunk split, jam mode)
frontend/  glass dashboard: index.html, styles.css, app.js (Leaflet)
database/  schema, views, triggers, procedures, Coimbatore seed, India migration
tests/     28 pytest tests: geo, congestion rules, Dijkstra, console parser
```

## 12. Testing

```bash
pytest tests -q   # 28 passed: Haversine/map-match, classifier boundaries,
                  # Dijkstra (avoidance, priority, unreachable, totals),
                  # console parser (routes, fuzzy, jam, synonyms, unknown)
```

## 13. Methodology (for the report)

Requirement analysis → conceptual design (ER/EER: 10 entities, 2 specializations) →
logical design → 3NF (positions reference segments; snapshot/history split;
thresholds factored into their own table) → physical design (PK/FK/checks,
indexes, views, triggers, procedures) → implementation (DB → API → simulator →
analyzer → router → dashboard) → verification (live E2E: jam → red map → reroute).
