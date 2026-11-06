from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np

from tcg_scanner.recognition.index import ReferenceIndex

PrintingKey = tuple[str, int]


@dataclass(frozen=True)
class Candidate:
    card_code: str
    print_index: int
    card_name: str
    set_code: str
    variant_label: str
    image_url: str | None
    score: float


def rank(
    index: ReferenceIndex,
    query: np.ndarray,
    *,
    code: str | None = None,
    top_k: int = 5,
) -> list[tuple[PrintingKey, float]]:
    """Rank printings by their best matching reference vector."""
    if len(index) == 0:
        return []

    scores = index.vectors @ query
    if code is not None:
        mask = np.array([candidate == code for candidate in index.card_codes])
        if not mask.any():
            return []
        scores = np.where(mask, scores, -np.inf)

    # A printing can have several reference images; keep its best score.
    key_ids, inverse = np.unique(index.key_ids, return_inverse=True)
    best = np.full(len(key_ids), -np.inf, dtype=np.float32)
    np.maximum.at(best, inverse, scores)

    keep = np.isfinite(best)
    key_ids, best = key_ids[keep], best[keep]
    order = np.argsort(-best)[:top_k]
    return [(index.keys[int(key_ids[i])], float(best[i])) for i in order]


def identify(
    conn: sqlite3.Connection,
    index: ReferenceIndex,
    query: np.ndarray,
    *,
    code: str | None = None,
    top_k: int = 5,
) -> list[Candidate]:
    ranked = rank(index, query, code=code, top_k=top_k)
    if not ranked:
        return []

    condition = " OR ".join("(printing.card_code = ? AND printing.print_index = ?)" for _ in ranked)
    params = [value for key, _score in ranked for value in key]
    rows = conn.execute(
        f"""
        SELECT printing.card_code, printing.print_index, printing.set_code,
               printing.variant_label, printing.image_url, card.name AS card_name
        FROM printings AS printing
        JOIN cards AS card ON card.code = printing.card_code
        WHERE {condition}
        """,
        params,
    ).fetchall()
    details = {(row["card_code"], row["print_index"]): row for row in rows}

    return [
        Candidate(
            card_code=key[0],
            print_index=key[1],
            card_name=details[key]["card_name"],
            set_code=details[key]["set_code"],
            variant_label=details[key]["variant_label"],
            image_url=details[key]["image_url"],
            score=score,
        )
        for key, score in ranked
    ]
