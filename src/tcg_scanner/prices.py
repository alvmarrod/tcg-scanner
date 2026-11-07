from __future__ import annotations

import sqlite3


def no_prices() -> dict[str, object]:
    return {"eur": None, "usd": None, "currency": None}


def latest_prices(conn: sqlite3.Connection, card_code: str, print_index: int) -> dict[str, object]:
    rows = conn.execute(
        "SELECT source, currency, amount FROM latest_prices "
        "WHERE card_code = ? AND print_index = ?",
        (card_code, print_index),
    ).fetchall()
    by_source = {row["source"]: (row["amount"], row["currency"]) for row in rows}
    eur = by_source.get("cardmarket")
    usd = by_source.get("tcgplayer")
    currency = eur[1] if eur is not None else (usd[1] if usd is not None else None)
    return {
        "eur": eur[0] if eur is not None else None,
        "usd": usd[0] if usd is not None else None,
        "currency": currency,
    }
