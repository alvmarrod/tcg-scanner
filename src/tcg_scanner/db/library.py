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
    confidence: float | None,
    method: str,
    created_at: str,
    card_code: str | None = None,
    print_index: int | None = None,
    card_name: str | None = None,
    set_code: str | None = None,
    variant_label: str | None = None,
    image_url: str | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO matches (photo_id, card_code, print_index, card_name, set_code,
                             variant_label, image_url, confidence, method, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            photo_id,
            card_code,
            print_index,
            card_name,
            set_code,
            variant_label,
            image_url,
            confidence,
            method,
            created_at,
        ),
    )
    return int(cursor.lastrowid)


def accept_match(
    conn: sqlite3.Connection,
    match_id: int,
    *,
    quantity: int = 1,
    condition: str | None = None,
    language: str | None = None,
    acquired_at: str | None = None,
) -> tuple[str, int]:
    """Mark a pending match accepted and add its printing to the collection."""
    row = _pending_match(conn, match_id)
    if row["card_code"] is None or row["print_index"] is None:
        raise ValueError(f"match {match_id} has no printing to accept")

    conn.execute("UPDATE matches SET status = 'accepted' WHERE id = ?", (match_id,))
    add_owned(
        conn,
        card_code=row["card_code"],
        print_index=row["print_index"],
        expected_image_url=row["image_url"],
        quantity=quantity,
        condition=condition,
        language=language,
        acquired_at=acquired_at,
    )
    return row["card_code"], row["print_index"]


def reject_match(conn: sqlite3.Connection, match_id: int) -> None:
    _pending_match(conn, match_id)
    conn.execute("UPDATE matches SET status = 'rejected' WHERE id = ?", (match_id,))


def add_owned(
    conn: sqlite3.Connection,
    *,
    card_code: str,
    print_index: int,
    expected_image_url: str | None = None,
    quantity: int = 1,
    condition: str | None = None,
    language: str | None = None,
    acquired_at: str | None = None,
    paid_price: float | None = None,
    currency: str | None = None,
    note: str | None = None,
) -> int:
    printing = get_printing(conn, card_code, print_index)
    if printing is None:
        raise ValueError(f"unknown printing: {card_code} #{print_index}")
    if expected_image_url is not None and printing["image_url"] != expected_image_url:
        raise ValueError(
            f"printing {card_code} #{print_index} changed in the catalog; re-run identify"
        )

    existing = conn.execute(
        """
        SELECT id FROM owned
        WHERE card_code = ? AND print_index = ? AND condition IS ? AND language IS ?
        ORDER BY id LIMIT 1
        """,
        (card_code, print_index, condition, language),
    ).fetchone()
    if existing is not None:
        # shortcut: merges by printing, condition and language; the paid price of
        # the first row is kept, not averaged.
        conn.execute(
            "UPDATE owned SET quantity = quantity + ? WHERE id = ?",
            (quantity, existing["id"]),
        )
        return int(existing["id"])

    cursor = conn.execute(
        """
        INSERT INTO owned (card_code, print_index, card_name, set_code, variant_label,
                           image_url, quantity, condition, language, acquired_at,
                           paid_price, currency, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            card_code,
            print_index,
            printing["card_name"],
            printing["set_code"],
            printing["variant_label"],
            printing["image_url"],
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
        SELECT owned.id, owned.card_code, owned.print_index, owned.card_name,
               owned.set_code, owned.variant_label, owned.quantity, owned.condition,
               owned.language, owned.paid_price,
               printing.card_code AS resolved,
               CASE WHEN printing.card_code IS NULL THEN NULL ELSE price.amount END AS price,
               CASE WHEN printing.card_code IS NULL THEN NULL ELSE price.currency END
                   AS currency
        FROM owned
        LEFT JOIN catalog.printings AS printing
            ON printing.card_code = owned.card_code
            AND printing.print_index = owned.print_index
            AND printing.image_url = owned.image_url
        LEFT JOIN catalog.latest_prices AS price
            ON price.card_code = owned.card_code
            AND price.print_index = owned.print_index
            AND price.source = ?
        ORDER BY owned.id
        """,
        (source,),
    ).fetchall()


def get_printing(conn: sqlite3.Connection, card_code: str, print_index: int) -> sqlite3.Row | None:
    """Requires catalog.db attached as `catalog`."""
    return conn.execute(
        """
        SELECT printing.card_code, printing.print_index, printing.set_code,
               printing.variant_label, printing.image_url, card.name AS card_name
        FROM catalog.printings AS printing
        JOIN catalog.cards AS card ON card.code = printing.card_code
        WHERE printing.card_code = ? AND printing.print_index = ?
        """,
        (card_code, print_index),
    ).fetchone()


def _pending_match(conn: sqlite3.Connection, match_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown match: {match_id}")
    if row["status"] != "pending":
        raise ValueError(f"match {match_id} is already {row['status']}")
    return row


def update_owned(
    conn: sqlite3.Connection,
    owned_id: int,
    *,
    quantity: int | None = None,
    condition: str | None = None,
    language: str | None = None,
    paid_price: float | None = None,
    currency: str | None = None,
    note: str | None = None,
) -> None:
    if quantity is not None and quantity <= 0:
        raise ValueError("quantity must be positive")

    changes = {
        "quantity": quantity,
        "condition": condition,
        "language": language,
        "paid_price": paid_price,
        "currency": currency,
        "note": note,
    }
    updates = {column: value for column, value in changes.items() if value is not None}
    if not updates:
        return
    if conn.execute("SELECT 1 FROM owned WHERE id = ?", (owned_id,)).fetchone() is None:
        raise ValueError(f"unknown owned row: {owned_id}")

    assignments = ", ".join(f"{column} = ?" for column in updates)
    conn.execute(
        f"UPDATE owned SET {assignments} WHERE id = ?",
        (*updates.values(), owned_id),
    )


def remove_owned(conn: sqlite3.Connection, owned_id: int) -> None:
    cursor = conn.execute("DELETE FROM owned WHERE id = ?", (owned_id,))
    if cursor.rowcount == 0:
        raise ValueError(f"unknown owned row: {owned_id}")


def collection_total(rows: list[sqlite3.Row]) -> tuple[float, int]:
    """Sum price x quantity over rows with a resolved price; count the rest."""
    total = 0.0
    unpriced = 0
    for row in rows:
        if row["price"] is None:
            unpriced += 1
        else:
            total += row["price"] * row["quantity"]
    return total, unpriced
