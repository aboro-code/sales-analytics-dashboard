"""DuckDB access: one read-only database, one cursor per worker thread."""
from __future__ import annotations

import os
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

import duckdb

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "sales.duckdb"


def _jsonable(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    return v


class Database:
    """
    Opens the DuckDB file **read-only**: the API cannot modify data even if a
    query were malformed, and multiple processes may open the same file.

    FastAPI runs sync endpoints in a threadpool. A DuckDB connection must not be
    used concurrently from several threads, so each thread gets its own cursor
    (``con.cursor()`` is a cheap duplicate of the parent connection sharing the
    same database instance and buffer pool).
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path or os.environ.get("SALES_DB_PATH") or DEFAULT_DB).resolve()
        if not self.path.exists():
            raise FileNotFoundError(
                f"Database not found at {self.path}. Run `python etl/build_db.py` first."
            )
        config = {
            # Keep within a 512 MB free-tier instance; the whole DB is ~6 MB anyway.
            "memory_limit": os.environ.get("DUCKDB_MEMORY_LIMIT", "256MB"),
        }
        if threads := os.environ.get("DUCKDB_THREADS"):
            config["threads"] = int(threads)
        self._root = duckdb.connect(str(self.path), read_only=True, config=config)
        self._local = threading.local()

    @property
    def con(self) -> duckdb.DuckDBPyConnection:
        c = getattr(self._local, "con", None)
        if c is None:
            c = self._local.con = self._root.cursor()
        return c

    def all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cur = self.con.execute(sql, list(params))
        cols = [d[0] for d in cur.description]
        return [{k: _jsonable(v) for k, v in zip(cols, row)} for row in cur.fetchall()]

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any]:
        rows = self.all(sql, params)
        return rows[0] if rows else {}

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.con.execute(sql, list(params)).fetchone()
        return _jsonable(row[0]) if row else None

    def stream(self, sql: str, params: Sequence[Any] = (), batch: int = 5000) -> Iterator[tuple[list[str], list[tuple[Any, ...]]]]:
        """Yield (columns, rows) batches. Uses a dedicated cursor so it is safe to
        iterate from whichever thread the streaming response runs on."""
        cur = self._root.cursor()
        try:
            cur.execute(sql, list(params))
            cols = [d[0] for d in cur.description]
            while chunk := cur.fetchmany(batch):
                yield cols, chunk
        finally:
            cur.close()
