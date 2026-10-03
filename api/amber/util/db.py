"""Postgres access through psycopg2: one connection per request, rows as dicts.

All SQL is parameterized (`%(name)s` placeholders); never format values into SQL.
"""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extensions
import psycopg2.extras

from amber.util.config import Settings

psycopg2.extras.register_uuid()  # uuid.UUID <-> Postgres uuid

Connection = psycopg2.extensions.connection


@contextmanager
def connect(settings: Settings) -> Generator[Connection, None, None]:
    """Opens a connection and closes it on exit. Call conn.commit() to keep changes;
    anything uncommitted is discarded when the connection closes."""
    conn = psycopg2.connect(settings.database_dsn.get_secret_value(), cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
    finally:
        conn.close()


def fetch_one(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row is not None else None


def execute(conn: Connection, sql: str, params: dict[str, Any] | None = None) -> int:
    """Runs a statement and returns the number of affected rows."""
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount
