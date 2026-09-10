"""SQL Lab — run your own read-only SQL against the live database.

Every query runs as the SELECT-only traffic_ro role with a 5 s statement
timeout, and lands in the live query log like everything else.
"""
import time
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import querylog
from ..database import get_ro_pool
from ..services.sqllab import MAX_ROWS, SAMPLES, check

router = APIRouter(prefix="/api/sql", tags=["sql"])


class SqlIn(BaseModel):
    sql: str


@router.get("/schema")
def schema():
    try:
        with get_ro_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT table_name, column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name NOT LIKE 'pg_%'
                    ORDER BY table_name, ordinal_position
                    """)
                tables: dict[str, list] = {}
                for t, c, d in cur.fetchall():
                    tables.setdefault(t, []).append({"name": c, "type": d})
    except Exception as exc:
        raise HTTPException(status_code=503,
                            detail=f"SQL Lab unavailable: {exc}".strip()[:200])
    return {"tables": [{"name": t, "columns": cols} for t, cols in tables.items()]}


@router.get("/samples")
def samples():
    return {"samples": [{"title": t, "sql": s} for t, s in SAMPLES]}


@router.post("/run")
def run(s: SqlIn):
    ok, reason = check(s.sql)
    if not ok:
        raise HTTPException(status_code=422, detail=reason)
    t0 = time.perf_counter()
    try:
        with get_ro_pool().connection() as conn:
            with conn.cursor() as cur:
                cur.execute(s.sql)
                cols = [d[0] for d in cur.description] if cur.description else []
                raw = cur.fetchmany(MAX_ROWS + 1)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 — pg errors become 422s, not 500s
        raise HTTPException(status_code=422, detail=str(exc).strip().split("\n")[0][:300])
    ms = (time.perf_counter() - t0) * 1000
    truncated = len(raw) > MAX_ROWS
    rows = []
    for r in raw[:MAX_ROWS]:
        rows.append([v.isoformat() if hasattr(v, "isoformat")
                     else float(v) if isinstance(v, Decimal) else v for v in r])
    querylog.log("SQL", f"lab: {s.sql.strip()[:100]}", ms,
                 f"{len(rows)} rows{' (truncated)' if truncated else ''}")
    return {"columns": cols, "rows": rows, "rowcount": len(rows),
            "truncated": truncated, "ms": round(ms, 2)}
