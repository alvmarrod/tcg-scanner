from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA_DIR = Path(__file__).parent

# The schema files are version 1 and stay frozen. Later changes are added as
# migrations keyed by the version they produce; fresh databases run the baseline
# and then every migration in order.
SCHEMA_VERSIONS = {"catalog": 3, "library": 2}
MIGRATIONS: dict[str, dict[int, str]] = {
    "catalog": {
        2: """
            ALTER TABLE card_images ADD COLUMN language TEXT NOT NULL DEFAULT 'jp';

            -- Backfill existing reference images from the printing URL: only the
            -- Japanese-only fallbacks do not end in _EN.webp.
            UPDATE card_images SET language = 'en'
            WHERE EXISTS (
                SELECT 1 FROM printings
                WHERE printings.card_code = card_images.card_code
                  AND printings.print_index = card_images.print_index
                  AND printings.image_url LIKE '%_EN.webp'
            );

            CREATE INDEX IF NOT EXISTS idx_card_images_language
                ON card_images (card_code, print_index, language);
        """,
        3: """
            CREATE TABLE IF NOT EXISTS image_misses (
                card_code   TEXT NOT NULL,
                print_index INTEGER NOT NULL,
                language    TEXT NOT NULL,
                checked_at  TEXT NOT NULL,
                PRIMARY KEY (card_code, print_index, language),
                FOREIGN KEY (card_code, print_index)
                    REFERENCES printings (card_code, print_index) ON DELETE CASCADE
            );

            -- Version 2 stored an English file under a 'jp' slot when the Japanese
            -- asset did not exist. That is a miss, not a Japanese image.
            INSERT OR REPLACE INTO image_misses (card_code, print_index, language, checked_at)
            SELECT image.card_code, image.print_index, 'jp', 'migration'
            FROM card_images AS image
            WHERE image.language = 'jp'
              AND EXISTS (
                  SELECT 1 FROM card_images AS english
                  WHERE english.card_code = image.card_code
                    AND english.print_index = image.print_index
                    AND english.language = 'en'
                    AND english.path = image.path
              );

            DELETE FROM card_images
            WHERE language = 'jp'
              AND EXISTS (
                  SELECT 1 FROM card_images AS english
                  WHERE english.card_code = card_images.card_code
                    AND english.print_index = card_images.print_index
                    AND english.language = 'en'
                    AND english.path = card_images.path
              );
        """,
    },
    "library": {
        2: """
            CREATE TABLE IF NOT EXISTS reviews (
                id                    INTEGER PRIMARY KEY,
                run                   TEXT NOT NULL,
                result_group          TEXT NOT NULL,
                status                TEXT NOT NULL CHECK (status IN ('right', 'wrong')),
                expansion             TEXT,
                predicted_card_code   TEXT,
                predicted_print_index INTEGER,
                score                 REAL,
                note                  TEXT,
                created_at            TEXT NOT NULL,
                updated_at            TEXT NOT NULL,
                UNIQUE (run, result_group)
            );

            CREATE INDEX IF NOT EXISTS idx_reviews_run ON reviews (run);
        """,
    },
}


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
