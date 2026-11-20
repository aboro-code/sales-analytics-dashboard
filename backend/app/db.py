"""SQLite access: one read-only connection per worker thread."""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "sales.db"


class Database:
    """
    Opens the SQLite file read-only and immutable.

    * ``mode=ro`` - the API can never write, even if a query were malformed.
    * ``immutable=1`` - SQLite skips file locking and change detection, which is
      safe because the file is only ever replaced by a fresh ETL build + restart.
    * Connections are per-thread because FastAPI runs sync endpoints in a
      threadpool and sqlite3 connections must not be shared across threads.
    """

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path or os.environ.get("SALES_DB_PATH") or DEFAULT_DB).resolve()
        if not self.path.exists():
            raise FileNotFoundError(
                f"SQLite database not found at {self.path}. Run `python etl/build_db.py` first."
            )
        self._local = threading.local()

    def _connect(self) -> sqlite3.Connection:
        uri = f"{self.path.as_uri()}?mode=ro&immutable=1"
        con = sqlite3.connect(uri, uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA query_only = ON")
        con.execute("PRAGMA mmap_size = 268435456")  # 256 MB memory-mapped reads
        con.execute("PRAGMA cache_size = -32000")    # ~32 MB page cache per connection
        con.execute("PRAGMA temp_store = MEMORY")
        return con

    @property
    def con(self) -> sqlite3.Connection:
        c = getattr(self._local, "con", None)
        if c is None:
            c = self._local.con = self._connect()
        return c

    def all(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [dict(r) for r in self.con.execute(sql, params).fetchall()]

    def one(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> dict[str, Any]:
        row = self.con.execute(sql, params).fetchone()
        return dict(row) if row else {}

    def scalar(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> Any:
        row = self.con.execute(sql, params).fetchone()
        return row[0] if row else None

    def cursor(self, sql: str, params: list[Any] | tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """A fresh connection-owned cursor, for streaming (export) on the calling thread."""
        return self.con.execute(sql, params)
