from __future__ import annotations

import sqlite3
from datetime import UTC, datetime


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


def accept_match(
    conn: sqlite3.Connection,
    match_id: int,
    *,
    quantity: int = 1,
    acquired_at: str | None = None,
) -> int:
    """Mark a pending match accepted and add its printing to the collection."""
    row = _pending_match(conn, match_id)
    if row["printing_id"] is None:
        raise ValueError(f"match {match_id} has no printing to accept")

    conn.execute("UPDATE matches SET status = 'accepted' WHERE id = ?", (match_id,))
    add_owned(
        conn,
        printing_id=row["printing_id"],
        quantity=quantity,
        acquired_at=acquired_at,
    )
    return int(row["printing_id"])


def reject_match(conn: sqlite3.Connection, match_id: int) -> None:
    _pending_match(conn, match_id)
    conn.execute("UPDATE matches SET status = 'rejected' WHERE id = ?", (match_id,))


def add_owned(
    conn: sqlite3.Connection,
    *,
    printing_id: int,
    quantity: int = 1,
    condition: str | None = None,
    language: str | None = None,
    acquired_at: str | None = None,
    paid_price: float | None = None,
    currency: str | None = None,
    note: str | None = None,
) -> int:
    if get_printing(conn, printing_id) is None:
        raise ValueError(f"unknown printing: {printing_id}")

    cursor = conn.execute(
        """
        INSERT INTO owned (printing_id, quantity, condition, language, acquired_at,
                           paid_price, currency, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            printing_id,
            quantity,
            condition,
            language,
            acquired_at or datetime.now(UTC).date().isoformat(),
            paid_price,
            currency,
            note,
        ),
    )
    return int(cursor.lastrowid)


def list_owned(conn: sqlite3.Connection, *, source: str = "tcgplayer") -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT owned.id, owned.quantity, owned.condition, owned.language, owned.paid_price,
               printing.card_code, printing.set_code, printing.variant_label,
               card.name AS card_name,
               price.amount AS price, price.currency
        FROM owned
        LEFT JOIN catalog.printings AS printing ON printing.id = owned.printing_id
        LEFT JOIN catalog.cards AS card ON card.code = printing.card_code
        LEFT JOIN catalog.latest_prices AS price
            ON price.printing_id = owned.printing_id AND price.source = ?
        ORDER BY owned.id
        """,
        (source,),
    ).fetchall()


def get_printing(conn: sqlite3.Connection, printing_id: int) -> sqlite3.Row | None:
    """Requires catalog.db attached as `catalog`."""
    return conn.execute(
        """
        SELECT printing.id, printing.card_code, printing.set_code, printing.variant_label,
               card.name AS card_name
        FROM catalog.printings AS printing
        JOIN catalog.cards AS card ON card.code = printing.card_code
        WHERE printing.id = ?
        """,
        (printing_id,),
    ).fetchone()


def _pending_match(conn: sqlite3.Connection, match_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown match: {match_id}")
    if row["status"] != "pending":
        raise ValueError(f"match {match_id} is already {row['status']}")
    return row
