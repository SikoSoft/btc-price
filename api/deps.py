"""
FastAPI dependency providers for bitcoin_analyzer.

Using FastAPI's dependency injection keeps route handlers thin and makes
the DB connection lifecycle easy to reason about: one connection per request,
always closed on completion (even on exceptions).

Usage in a route:
    @router.get("/example")
    def example(conn: DbConn):
        return get_something(conn)
"""

import sqlite3
from typing import Annotated, Generator

from fastapi import Depends

from config import DB_PATH
from db.database import init_db


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """
    Yield an open SQLite connection for the duration of a request.
    Ensures the schema exists before yielding (idempotent DDL).
    Always closes the connection, even if the handler raises.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row   # lets callers access columns by name
    try:
        init_db(conn)
        yield conn
    finally:
        conn.close()


# Annotated shorthand used in route signatures:
#   def my_route(conn: DbConn): ...
DbConn = Annotated[sqlite3.Connection, Depends(get_db)]
