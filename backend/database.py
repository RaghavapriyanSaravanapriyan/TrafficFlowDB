"""PostgreSQL connection pool + schema bootstrap.

Uses psycopg 3 with a small thread-safe pool. The ingest path is raw SQL
(prepared once per checkout) — no ORM overhead on the hot path.
"""
from __future__ import annotations

import pathlib
import time

import psycopg
from psycopg_pool import ConnectionPool

from .config import settings

_pool: ConnectionPool | None = None

SCHEMA_FILES = ("schema.sql", "views.sql", "triggers.sql", "procedures.sql")
MIGRATION_FILES = ("migrate_india.sql",)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            settings.database_url,
            min_size=2,
            max_size=20,
            kwargs={"autocommit": True},
            open=True,
        )
    return _pool


def wait_for_db(timeout: float = 60.0) -> None:
    """Block until Postgres accepts connections (docker-compose bring-up)."""
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            with psycopg.connect(settings.database_url, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            return
        except Exception as exc:  # noqa: BLE001 — retry on anything during boot
            last = exc
            time.sleep(1.0)
    raise RuntimeError(f"Database never became ready: {last}")


def init_db(seed: bool = True) -> None:
    """Create schema in dependency order, load the road network, run migrations."""
    base = pathlib.Path(__file__).resolve().parent.parent / "database"
    pool = get_pool()
    with pool.connection() as conn:
        with conn.cursor() as cur:
            for name in SCHEMA_FILES:
                cur.execute((base / name).read_text())
        if seed:
            with conn.cursor() as cur:
                cur.execute((base / "seed_coimbatore.sql").read_text())
        with conn.cursor() as cur:
            for name in MIGRATION_FILES:
                cur.execute((base / name).read_text())


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
