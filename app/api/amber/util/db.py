"""Postgres access through psycopg2: a thread-safe connection pool and a per-request handle.

All SQL is parameterized (`%(name)s` / `%s` placeholders); never format values into SQL.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras
import psycopg2.pool

from amber.util.config import Settings

psycopg2.extras.register_uuid()  # uuid.UUID <-> Postgres uuid


class Database:
    """Connection pool. Callers block (instead of erroring) when every connection is in use."""

    def __init__(self, dsn: str, minconn: int = 1, maxconn: int = 10):
        self._pool = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, dsn)
        self._slots = threading.BoundedSemaphore(maxconn)

    @classmethod
    def from_settings(cls, settings: Settings) -> "Database":
        return cls(settings.database_dsn.get_secret_value(), settings.db_pool_min, settings.db_pool_max)

    @contextmanager
    def connection(self) -> Iterator["Db"]:
        """Yields a Db for one unit of work. Anything not committed is rolled back on exit."""
        with self._slots:
            conn = self._pool.getconn()
            try:
                yield Db(conn)
            finally:
                broken = conn.closed != 0
                if not broken:
                    conn.rollback()
                self._pool.putconn(conn, close=broken)

    def close(self) -> None:
        self._pool.closeall()


class Db:
    """One pooled connection. Rows come back as dicts. Call commit() to keep changes."""

    def __init__(self, conn: psycopg2.extensions.connection):
        self._conn = conn

    def one(self, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> int:
        """Runs a statement and returns the number of affected rows."""
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()
