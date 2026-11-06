from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_DIR = Path(__file__).parent


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _init(path: Path, schema_name: str) -> Path:
    schema = (_SCHEMA_DIR / schema_name).read_text(encoding="utf-8")
    conn = connect(path)
    try:
        conn.executescript(schema)
        conn.commit()
    finally:
        conn.close()
    return path


def init_catalog(path: Path) -> Path:
    return _init(path, "schema_catalog.sql")


def init_library(path: Path) -> Path:
    return _init(path, "schema_library.sql")


def open_catalog(path: Path) -> sqlite3.Connection:
    return connect(path)


def open_library(path: Path) -> sqlite3.Connection:
    return connect(path)


def attach_catalog(conn: sqlite3.Connection, path: Path) -> None:
    """Expose catalog.db as `catalog.*` so library queries can join prices."""
    conn.execute("ATTACH DATABASE ? AS catalog", (str(path),))
