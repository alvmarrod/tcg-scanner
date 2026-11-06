from __future__ import annotations

import sqlite3


def add_photo(
    conn: sqlite3.Connection,
    *,
    path: str,
    sha256: str,
    width: int | None = None,
    height: int | None = None,
) -> int:
    row = conn.execute("SELECT id FROM photos WHERE sha256 = ?", (sha256,)).fetchone()
    if row is not None:
        return row["id"]

    cursor = conn.execute(
        "INSERT INTO photos (path, sha256, width, height) VALUES (?, ?, ?, ?)",
        (path, sha256, width, height),
    )
    return int(cursor.lastrowid)


def add_match(
    conn: sqlite3.Connection,
    *,
    photo_id: int,
    printing_id: int | None,
    confidence: float | None,
    method: str,
    created_at: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO matches (photo_id, printing_id, confidence, method, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (photo_id, printing_id, confidence, method, created_at),
    )
    return int(cursor.lastrowid)
