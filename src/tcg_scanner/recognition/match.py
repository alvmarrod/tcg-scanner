from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import numpy as np

from tcg_scanner.recognition.index import ReferenceIndex


@dataclass(frozen=True)
class Candidate:
    printing_id: int
    card_code: str
    card_name: str
    set_code: str
    variant_label: str
    score: float


def rank(
    index: ReferenceIndex,
    query: np.ndarray,
    *,
    code: str | None = None,
    top_k: int = 5,
) -> list[tuple[int, float]]:
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
    printings, inverse = np.unique(index.printing_ids, return_inverse=True)
    best = np.full(len(printings), -np.inf, dtype=np.float32)
    np.maximum.at(best, inverse, scores)

    keep = np.isfinite(best)
    printings, best = printings[keep], best[keep]
    order = np.argsort(-best)[:top_k]
    return [(int(printings[i]), float(best[i])) for i in order]


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

    ids = [printing_id for printing_id, _ in ranked]
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT printing.id, printing.card_code, printing.set_code, printing.variant_label,
               card.name AS card_name
        FROM printings AS printing
        JOIN cards AS card ON card.code = printing.card_code
        WHERE printing.id IN ({placeholders})
        """,
        ids,
    ).fetchall()
    details = {row["id"]: row for row in rows}

    return [
        Candidate(
            printing_id=printing_id,
            card_code=details[printing_id]["card_code"],
            card_name=details[printing_id]["card_name"],
            set_code=details[printing_id]["set_code"],
            variant_label=details[printing_id]["variant_label"],
            score=score,
        )
        for printing_id, score in ranked
    ]
