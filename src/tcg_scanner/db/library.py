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
    language = language or "jp"
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


def list_owned(conn: sqlite3.Connection, *, source: str = "auto") -> list[sqlite3.Row]:
    if source not in ("auto", "eur", "usd"):
        raise ValueError(f"unknown price source: {source}")

    return conn.execute(
        """
        SELECT owned.id, owned.card_code, owned.print_index, owned.card_name,
               owned.set_code, owned.variant_label, owned.quantity, owned.condition,
               owned.language, owned.paid_price,
               printing.card_code AS resolved,
               CASE
                   WHEN printing.card_code IS NULL THEN NULL
                   WHEN :source = 'usd' THEN usd.amount
                   WHEN :source = 'eur' THEN eur.amount
                   ELSE COALESCE(eur.amount, usd.amount)
               END AS price,
               CASE
                   WHEN printing.card_code IS NULL THEN NULL
                   WHEN :source = 'usd' THEN usd.currency
                   WHEN :source = 'eur' THEN eur.currency
                   ELSE COALESCE(eur.currency, usd.currency)
               END AS currency
        FROM owned
        LEFT JOIN catalog.printings AS printing
            ON printing.card_code = owned.card_code
            AND printing.print_index = owned.print_index
            AND printing.image_url = owned.image_url
        LEFT JOIN catalog.latest_prices AS eur
            ON eur.card_code = owned.card_code
            AND eur.print_index = owned.print_index
            AND eur.source = 'cardmarket'
        LEFT JOIN catalog.latest_prices AS usd
            ON usd.card_code = owned.card_code
            AND usd.print_index = owned.print_index
            AND usd.source = 'tcgplayer'
        ORDER BY owned.id
        """,
        {"source": source},
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


def list_matches(conn: sqlite3.Connection, *, status: str = "pending") -> list[sqlite3.Row]:
    if status not in ("pending", "accepted", "rejected", "all"):
        raise ValueError(f"unknown match status: {status}")

    clause = "" if status == "all" else "WHERE matches.status = ?"
    params: tuple[object, ...] = () if status == "all" else (status,)
    return conn.execute(
        f"""
        SELECT matches.id, matches.status, matches.confidence, matches.method,
               matches.created_at, matches.card_code, matches.print_index,
               matches.card_name, matches.set_code, matches.variant_label,
               matches.image_url, printing.card_code AS resolved
        FROM matches
        LEFT JOIN catalog.printings AS printing
            ON printing.card_code = matches.card_code
            AND printing.print_index = matches.print_index
            AND printing.image_url = matches.image_url
        {clause}
        ORDER BY matches.id
        """,
        params,
    ).fetchall()


def set_review(
    conn: sqlite3.Connection,
    *,
    run: str,
    result_group: str,
    iteration: int = 0,
    status: str,
    expansion: str | None = None,
    predicted_card_code: str | None = None,
    predicted_print_index: int | None = None,
    score: float | None = None,
    note: str | None = None,
) -> sqlite3.Row | None:
    if status not in ("right", "wrong", "unmarked"):
        raise ValueError(f"unknown review status: {status}")

    expansion = expansion.strip().upper() if expansion else None
    if status == "right":
        expansion = None

    if status == "unmarked" and expansion is None and note is None:
        clear_review(conn, run, result_group, iteration)
        return None

    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO reviews (run, result_group, iteration, status, expansion,
                             predicted_card_code, predicted_print_index, score, note,
                             created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (run, result_group, iteration) DO UPDATE SET
            status = excluded.status,
            expansion = excluded.expansion,
            predicted_card_code = excluded.predicted_card_code,
            predicted_print_index = excluded.predicted_print_index,
            score = excluded.score,
            note = excluded.note,
            updated_at = excluded.updated_at
        """,
        (
            run,
            result_group,
            iteration,
            status,
            expansion,
            predicted_card_code,
            predicted_print_index,
            score,
            note,
            now,
            now,
        ),
    )
    conn.commit()
    return get_review(conn, run, result_group, iteration)


def clear_review(conn: sqlite3.Connection, run: str, result_group: str, iteration: int = 0) -> bool:
    cursor = conn.execute(
        "DELETE FROM reviews WHERE run = ? AND result_group = ? AND iteration = ?",
        (run, result_group, iteration),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_review(
    conn: sqlite3.Connection, run: str, result_group: str, iteration: int = 0
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM reviews WHERE run = ? AND result_group = ? AND iteration = ?",
        (run, result_group, iteration),
    ).fetchone()


def list_reviews(conn: sqlite3.Connection, *, run: str | None = None) -> list[sqlite3.Row]:
    clause = "WHERE run = ?" if run is not None else ""
    params: tuple[object, ...] = (run,) if run is not None else ()
    return conn.execute(
        f"SELECT * FROM reviews {clause} ORDER BY run, result_group, iteration",
        params,
    ).fetchall()


def review_stats(
    conn: sqlite3.Connection,
    *,
    run: str | None = None,
    latest: dict[tuple[str, str], int] | None = None,
) -> dict[str, object]:
    rows = list_reviews(conn, run=run)
    if latest is not None:
        rows = [
            row for row in rows if latest.get((row["run"], row["result_group"])) == row["iteration"]
        ]

    reviewed = [row for row in rows if row["status"] in ("right", "wrong")]
    right = sum(1 for row in reviewed if row["status"] == "right")
    wrong = len(reviewed) - right

    by_expansion: dict[str, dict[str, int]] = {}
    claimed: dict[str, int] = {}
    for row in reviewed:
        code = row["predicted_card_code"] or ""
        expansion = code.split("-")[0] if code else "unknown"
        bucket = by_expansion.setdefault(expansion, {"right": 0, "wrong": 0})
        bucket[row["status"]] += 1
        if row["status"] == "wrong" and row["expansion"]:
            claimed[row["expansion"]] = claimed.get(row["expansion"], 0) + 1

    return {
        "reviewed": len(reviewed),
        "right": right,
        "wrong": wrong,
        "unmarked": len(rows) - len(reviewed),
        "accuracy": right / len(reviewed) if reviewed else None,
        "by_expansion": dict(sorted(by_expansion.items())),
        "claimed_expansion": dict(sorted(claimed.items())),
    }
