# TrafficFlowDB

**Real-time traffic intelligence on a relational database — across India.**
Vehicles drive real origin→destination trips, stream GPS into PostgreSQL, the
database scores congestion per segment, and Dijkstra reroutes around it.
You can spawn fleets, inject jams, rewrite the congestion rulebook live —
and query the database yourself in the SQL Lab while every query streams
through the Under-the-hood terminal.

> One-line pitch: a real-time traffic intelligence system in which a relational
> database acts as the central layer for collecting, managing, analyzing, and serving
> continuously changing transportation data.

Live network: **26 national highway hubs, 32 trunk corridors** — one connected
graph, so `Delhi → Kochi` (3,570 km) routes in a single query.
Traffic is generated live — no canned congestion.

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
```

Traffic — pick either (or both):

```bash
# A. CLI fleet: OD-trip driving, density-aware speeds, bus dwell (own terminal)
python -m simulator.vehicle_simulator --vehicles 70 --mode trip

# B. Server fleet: no terminal needed — drawer → Customize → fleet → Apply,
#    or: curl -X POST localhost:8000/api/fleet -d '{"enabled":true,"count":200}'
```

Config: `DATABASE_URL`, `TRAFFIC_WINDOW_MINUTES`, `POLL_SECONDS`,
`READONLY_DB_PASSWORD` (see `.env.example`; the first three are also tunable
live via `PUT /api/config` / the Customize drawer).

## 3. Architecture

```
Fleet (CLI and/or server-side) → POST /api/gps/batch → bulk ingest:
    upsert vehicles → bulk INSERT gps_data + vehicle_position
        → ONE SELECT refresh_all_traffic(window) per batch
            → traffic_condition (snapshot) + traffic_history (trend)
                → Dijkstra on travel-time weights → route + route_segment
                    → REST + WebSocket /ws/live (traffic, positions, query log)
                        → glass dashboard: SQL Lab, map, live SQL terminal
```

`intersection` rows are nodes, `road_segment` rows are bidirectional edges.
Bulk ingest keeps round trips constant per batch:
**~1,300–1,600 fixes/sec** measured (200-fix batch in ~110 ms).

## 4. Realistic traffic

Vehicles don't random-walk — each one picks a destination (national-biased,
like real intercity flow), follows the Dijkstra shortest-time path, and
re-plans on arrival:

- **Density-aware speed**: target speed folds in live segment load
  (`1 − density × 0.6`), eased toward — jams propagate organically.
- **Driver personalities**: per-vehicle aggression factor × type factor
  (bus 0.85, emergency 1.3 and congestion-immune).
- **Bus dwell**: buses pause 1–3 ticks at nodes (stops) with 40% probability.
- **Capacity-weighted spawn**: big corridors naturally carry more flow.

At ~200+ vehicles the busy corridors start jamming on their own — no scripted congestion.

## 5. Database design (the core)

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
`refresh_all_traffic`, `get_congested_segments`, `find_nearby_segments`) ·
a SELECT-only `traffic_ro` role provisioned at boot for the SQL Lab.

Files: `database/schema.sql`, `views.sql`, `triggers.sql`, `procedures.sql`,
`migrate_india.sql`, `migrate_all_india.sql` — applied in order by `init_db()`.

## 6. Traffic analysis

Rolling window (default 5 min, live-tunable) per segment.
Rule lives in `traffic_thresholds`, read by the procedure on every call:

```
density  = distinct_vehicles / capacity
HIGH     if avg_speed < high_speed AND density > high_density   (15, 0.75)
MEDIUM   if avg_speed < med_speed  OR  density > med_density     (30, 0.50)
LOW      otherwise
```

## 7. Routing

Dijkstra, weight = live travel time `w = distance / effective_speed × 60`
(live average when observed, else limit derated by congestion multiplier
LOW 1.0 / MEDIUM 1.5 / HIGH 2.5). Emergency `priority=true` uses free-flow
weights. Requests persist `route_request → route → route_segment[]`.
Delhi → Mumbai (1,460 km, 4 legs) computes in ~0.05 ms.

## 8. SQL Lab — query it yourself

Dashboard → SQL Lab: schema browser (24 tables & views) + editor
(`Ctrl K` focuses, `Ctrl ⏎` runs) + results grid. Triple-locked reads:

1. Parser allowlist — `SELECT`/`WITH` only, single statement, no stacking,
   no catalog snooping (`pg_*`, `version()`).
2. The `traffic_ro` role holds SELECT-only grants — even a smuggled write
   dies with `permission denied` (verified live).
3. `statement_timeout = 5 s` on the read-only pool; 200-row cap.

Recommended starter queries (one click each, all verified live):

1. **Congested right now** — live leaderboard from `live_traffic_summary`.
2. **Slowest trunk corridors** — where the highways are bleeding speed.
3. **Load by scope** — trunk segment/vehicle/speed rollup.
4. **Fleet mix, live** — car/bus/emergency counts + speeds from `latest_positions`.
5. **Fixes per minute (15 min)** — ingest firehose rate from `gps_data`.
6. **Hourly speed trend** — 12-hour network performance from `traffic_history`.

(`POST /api/command` NL console from v2 remains as an API extra.)

## 9. REST + WebSocket API

| Method | Endpoint                        | Purpose                                        |
|--------|---------------------------------|------------------------------------------------|
| GET    | `/api/health`                   | readiness                                      |
| POST   | `/api/gps` · `/api/gps/batch`   | ingest 1 fix / bulk batch (constant round trips) |
| GET    | `/api/network/*`                | intersections, segments (+scope), live positions |
| GET    | `/api/traffic/summary`          | live snapshot (drives map + table)             |
| GET    | `/api/traffic/congested?level=` | worst-first                                    |
| GET    | `/api/traffic/segment/{id}`     | snapshot + 60-pt history                       |
| POST   | `/api/traffic/refresh`          | recompute all segments                         |
| POST   | `/api/routes/request`           | `{source_id, destination_id, priority?}`       |
| GET    | `/api/routes/history`           | past recommendations                           |
| GET/PUT| `/api/config`                   | window, poll cadence, congestion thresholds    |
| GET/POST| `/api/fleet`                   | server fleet status / spawn-retire control     |
| POST   | `/api/scenarios/jam`            | inject N crawling vehicles on a segment        |
| POST   | `/api/scenarios/rush-hour`      | peak load on top-capacity corridors            |
| POST   | `/api/scenarios/reset`          | remove scenario vehicles, recompute            |
| GET/POST| `/api/sql/*`                   | schema, samples, read-only query runner        |
| GET    | `/api/logs?since=&limit=`       | live query-log ring buffer                     |
| WS     | `/ws/live`                      | traffic + positions + log entries every tick   |

Docs: `:8000/docs`. The **Under the hood** terminal streams the query log
(SQL text + ms + context) with category filters, pause, and running averages —
a bounded in-memory ring, so logging never slows ingest.

## 10. Demo script

1. `docker compose up -d db` → `uvicorn backend.main:app` → `:8000`.
2. Drawer → fleet → 200 vehicles → Apply (or CLI sim). The corridors light up.
3. SQL Lab → run **Congested right now** — your own query, live rows.
4. Drawer → jam NH44 (or console scenario) — corridor turns red in seconds.
5. `Route Delhi to Mumbai` — watch it swerve around the jam; check the
   terminal for the 0.05 ms Dijkstra line.

## 11. Metrics (measured)

Bulk ingest **~1,300–1,600 fixes/s** (200-fix batch ≈ 110 ms, 1 refresh) ·
stats ~5–15 ms under load · Dijkstra 26 nodes/32 edges ~0.05 ms ·
dashboard tick 2 s (WS push + poll fallback).

## 12. Layout

```
backend/   main, database pool (+read-only role), runtime config, querylog,
           schemas, routes/ (gps, network, traffic, routing, vehicles, stats,
           config, fleet, scenarios, command, sql, logs)
           services/ (geo, gps_processor, ingest_bulk, traffic_analyzer,
           route_optimizer, scenarios, command, sqllab)
simulator/ OD-trip fleet (Vehicle mover, build_graph/plan_trip),
           vehicle_simulator.py (CLI), fleet.py (server FleetManager)
frontend/  glass dashboard: index.html, styles.css, app.js (Leaflet)
database/  schema, views, triggers, procedures, India migrations
tests/     36 pytest tests: geo, congestion rules, Dijkstra, console parser, SQL guard
```

## 13. Testing

```bash
pytest tests -q   # 36 passed: Haversine/map-match, classifier boundaries,
                  # Dijkstra (avoidance, priority, unreachable, totals),
                  # console parser, SQL Lab guard (writes/stacking/catalog blocked,
                  # all 6 samples valid)
```

## 14. Methodology (for the report)

Requirement analysis → conceptual design (ER/EER: 10 entities, 2 specializations) →
logical design → 3NF (positions reference segments; snapshot/history split;
thresholds factored out; SELECT-only role separation) → physical design (PK/FK/checks,
indexes, views, triggers, procedures) → implementation (DB → bulk API → OD fleet →
analyzer → router → dashboard) → verification (live E2E: spawn → density jam →
red map → reroute → your own SQL confirms it).
