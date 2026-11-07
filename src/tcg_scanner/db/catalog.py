from __future__ import annotations

import sqlite3

from tcg_scanner.catalog.parse import ParsedCard

# The source does not expose card rarity; variant labels from the prints table
# ("aa", ...) are what distinguish printings for this database.
RARITY_UNKNOWN = "unknown"


def upsert_set(
    conn: sqlite3.Connection,
    *,
    code: str,
    name: str,
    kind: str,
    release_date: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO sets (code, name, kind, release_date) VALUES (?, ?, ?, ?)
        ON CONFLICT (code) DO UPDATE SET
            name = excluded.name,
            kind = excluded.kind,
            release_date = COALESCE(excluded.release_date, sets.release_date)
        """,
        (code, name, kind, release_date),
    )


def upsert_card(conn: sqlite3.Connection, card: ParsedCard, set_code: str) -> None:
    conn.execute(
        """
        INSERT INTO cards (code, name, card_type, color, cost, power, counter, life,
                           attribute, traits, effect_text, set_code)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (code) DO UPDATE SET
            name = excluded.name,
            card_type = excluded.card_type,
            color = excluded.color,
            cost = excluded.cost,
            power = excluded.power,
            counter = excluded.counter,
            life = excluded.life,
            attribute = excluded.attribute,
            traits = excluded.traits,
            effect_text = excluded.effect_text,
            set_code = excluded.set_code
        """,
        (
            card.code,
            card.name,
            card.category,
            card.color,
            card.cost,
            card.power,
            card.counter,
            card.life,
            card.attribute,
            card.traits,
            card.effect,
            set_code,
        ),
    )


def upsert_printing(
    conn: sqlite3.Connection,
    *,
    card_code: str,
    set_code: str,
    variant_label: str,
    print_index: int,
    image_url: str,
    tcgplayer_id: str | None,
    cardmarket_id: str | None,
) -> tuple[str, int]:
    conn.execute(
        """
        INSERT INTO printings (card_code, print_index, set_code, rarity, variant_label,
                               image_url, tcgplayer_id, cardmarket_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (card_code, print_index) DO UPDATE SET
            set_code = excluded.set_code,
            rarity = excluded.rarity,
            variant_label = excluded.variant_label,
            tcgplayer_id = excluded.tcgplayer_id,
            cardmarket_id = excluded.cardmarket_id
        """,
        (
            card_code,
            print_index,
            set_code,
            RARITY_UNKNOWN,
            variant_label,
            image_url,
            tcgplayer_id,
            cardmarket_id,
        ),
    )
    return card_code, print_index


def add_price(
    conn: sqlite3.Connection,
    *,
    card_code: str,
    print_index: int,
    source: str,
    currency: str,
    amount: float,
    fetched_at: str,
) -> bool:
    latest = conn.execute(
        """
        SELECT amount, currency FROM prices
        WHERE card_code = ? AND print_index = ? AND source = ?
        ORDER BY fetched_at DESC LIMIT 1
        """,
        (card_code, print_index, source),
    ).fetchone()
    if latest and latest["amount"] == amount and latest["currency"] == currency:
        return False

    conn.execute(
        """
        INSERT INTO prices (card_code, print_index, source, currency, amount, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (card_code, print_index, source, currency, amount, fetched_at),
    )
    return True


def has_reference_image(
    conn: sqlite3.Connection, card_code: str, print_index: int, language: str
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM card_images
        WHERE card_code = ? AND print_index = ? AND origin = 'reference' AND language = ?
        LIMIT 1
        """,
        (card_code, print_index, language),
    ).fetchone()
    return row is not None


def add_card_image(
    conn: sqlite3.Connection,
    *,
    card_code: str,
    print_index: int,
    language: str,
    path: str,
    sha256: str,
    width: int | None = None,
    height: int | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO card_images (card_code, print_index, language, path, sha256,
                                 width, height, origin)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'reference')
        """,
        (card_code, print_index, language, path, sha256, width, height),
    )


def has_image_miss(
    conn: sqlite3.Connection, card_code: str, print_index: int, language: str
) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM image_misses
        WHERE card_code = ? AND print_index = ? AND language = ?
        """,
        (card_code, print_index, language),
    ).fetchone()
    return row is not None


def record_image_miss(
    conn: sqlite3.Connection,
    *,
    card_code: str,
    print_index: int,
    language: str,
    checked_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO image_misses (card_code, print_index, language, checked_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (card_code, print_index, language) DO UPDATE SET
            checked_at = excluded.checked_at
        """,
        (card_code, print_index, language, checked_at),
    )


def clear_image_miss(
    conn: sqlite3.Connection, card_code: str, print_index: int, language: str
) -> None:
    conn.execute(
        "DELETE FROM image_misses WHERE card_code = ? AND print_index = ? AND language = ?",
        (card_code, print_index, language),
    )
