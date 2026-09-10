"""SQL Lab guard + sample library (pure, unit-tested).

Defense in depth for browser-submitted SQL:
1. This parser allowlist (SELECT/WITH, single statement, length cap).
2. The traffic_ro PostgreSQL role, which holds SELECT-only grants —
   even a bypassed guard cannot write.
3. statement_timeout=5s on the read-only pool.
"""
from __future__ import annotations

MAX_SQL_LEN = 8000
MAX_ROWS = 200


def check(sql: str) -> tuple[bool, str]:
    """Return (ok, reason). Only single read-only statements pass."""
    text = (sql or "").strip()
    if not text:
        return False, "empty query"
    if len(text) > MAX_SQL_LEN:
        return False, f"query too long (>{MAX_SQL_LEN} chars)"
    body = text[:-1].rstrip() if text.endswith(";") else text
    if ";" in body:
        return False, "one statement at a time — no stacking"
    first = body.lstrip(" (").split(None, 1)
    if not first or first[0].upper() not in ("SELECT", "WITH"):
        return False, "read-only: queries must start with SELECT or WITH"
    lowered = f" {body.lower()} "
    for banned in (" pg_", "current_setting", "version()"):
        if banned in lowered:
            return False, "system catalog access is blocked"
    return True, ""


SAMPLES = [
    ("Congested right now",
     "SELECT segment_name, scope, average_speed AS avg_kmh, vehicle_count,\n"
     "       ROUND(density::numeric, 2) AS density, congestion_level\n"
     "FROM live_traffic_summary\n"
     "WHERE congestion_level <> 'LOW'\n"
     "ORDER BY density DESC\nLIMIT 10;"),
    ("Slowest trunk corridors",
     "SELECT segment_name, distance_km, average_speed AS avg_kmh, vehicle_count\n"
     "FROM live_traffic_summary\n"
     "WHERE scope = 'trunk'\n"
     "ORDER BY average_speed\nLIMIT 8;"),
    ("Load by scope",
     "SELECT scope, COUNT(*) AS segments, SUM(vehicle_count) AS vehicles,\n"
     "       ROUND(AVG(average_speed)::numeric, 1) AS avg_kmh\n"
     "FROM live_traffic_summary\n"
     "GROUP BY scope\nORDER BY scope;"),
    ("Fleet mix, live",
     "SELECT vehicle_type, COUNT(*) AS vehicles,\n"
     "       ROUND(AVG(speed_kmh)::numeric, 1) AS avg_kmh\n"
     "FROM latest_positions\n"
     "GROUP BY vehicle_type;"),
    ("Fixes per minute (15 min)",
     "SELECT date_trunc('minute', recorded_at) AS minute, COUNT(*) AS fixes\n"
     "FROM gps_data\n"
     "WHERE recorded_at > NOW() - INTERVAL '15 minutes'\n"
     "GROUP BY 1\nORDER BY 1 DESC\nLIMIT 15;"),
    ("Hourly speed trend",
     "SELECT date_trunc('hour', calculated_at) AS hour,\n"
     "       ROUND(AVG(average_speed)::numeric, 1) AS avg_kmh,\n"
     "       SUM(vehicle_count) AS vehicles\n"
     "FROM traffic_history\n"
     "WHERE calculated_at > NOW() - INTERVAL '12 hours'\n"
     "GROUP BY 1\nORDER BY 1;"),
]
