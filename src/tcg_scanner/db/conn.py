from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_DIR = Path(__file__).parent

# The schema files are version 1 and stay frozen. Later changes are added as
# migrations keyed by the version they produce; fresh databases run the baseline
# and then every migration in order.
SCHEMA_VERSIONS = {"catalog": 1, "library": 1}
MIGRATIONS: dict[str, dict[int, str]] = {"catalog": {}, "library": {}}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _init(path: Path, schema_name: str) -> Path:
    conn = connect(path)
    try:
        _migrate(conn, schema_name)
        conn.commit()
    finally:
        conn.close()
    return path


def _migrate(conn: sqlite3.Connection, schema_name: str) -> None:
    version = SCHEMA_VERSIONS[schema_name]
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > version:
        raise RuntimeError(
            f"{schema_name} schema version {current} is newer than supported ({version}); "
            "upgrade tcg-scanner"
        )

    if current == 0:
        # Legacy databases already hold the version-1 schema; CREATE IF NOT EXISTS
        # keeps re-running the baseline safe.
        baseline = (_SCHEMA_DIR / f"schema_{schema_name}.sql").read_text(encoding="utf-8")
        conn.executescript(baseline)
        current = 1

    for target in range(current + 1, version + 1):
        migration = MIGRATIONS[schema_name].get(target)
        if migration is None:
            raise RuntimeError(f"{schema_name}: no migration to version {target}")
        conn.executescript(migration)
        conn.execute(f"PRAGMA user_version = {target}")

    conn.execute(f"PRAGMA user_version = {version}")


def init_catalog(path: Path) -> Path:
    return _init(path, "catalog")


def init_library(path: Path) -> Path:
    return _init(path, "library")


def open_catalog(path: Path) -> sqlite3.Connection:
    return connect(path)


def open_library(path: Path) -> sqlite3.Connection:
    return connect(path)


def attach_catalog(conn: sqlite3.Connection, path: Path) -> None:
    """Expose catalog.db as `catalog.*` so library queries can join prices."""
    conn.execute("ATTACH DATABASE ? AS catalog", (str(path),))
