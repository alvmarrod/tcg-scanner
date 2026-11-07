from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace

import numpy as np

from tcg_scanner.recognition.index import (
    KIND_PATCH,
    ReferenceIndex,
    from_patch_blob,
)

PrintingKey = tuple[str, int]

PATCH_MARGIN = 0.05
"""Score gap within which patch tokens decide the order.

shortcut: hardcoded until the evaluation set says what the gap should be.
"""


@dataclass(frozen=True)
class Candidate:
    card_code: str
    print_index: int
    card_name: str
    set_code: str
    variant_label: str
    image_url: str | None
    score: float
    patch_score: float | None = None


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
    if not ranked and code is not None:
        # A misread code must not turn a good image match into "no match".
        ranked = rank(index, query, code=None, top_k=top_k)
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


def verify(
    conn: sqlite3.Connection,
    candidates: list[Candidate],
    query_patches: np.ndarray,
    model_name: str,
    *,
    margin: float = PATCH_MARGIN,
) -> list[Candidate]:
    """Reorder candidates within `margin` of the top by patch-token similarity."""
    if not candidates:
        return []

    top_score = candidates[0].score
    size = sum(1 for candidate in candidates if top_score - candidate.score <= margin)
    group, rest = list(candidates[:size]), list(candidates[size:])

    scores = _patch_scores(conn, group, query_patches, model_name)
    if any((candidate.card_code, candidate.print_index) not in scores for candidate in group):
        # Incomplete patch index: do not favor candidates that happen to have one.
        return candidates

    verified = [
        replace(candidate, patch_score=scores[(candidate.card_code, candidate.print_index)])
        for candidate in group
    ]
    verified.sort(
        key=lambda candidate: (
            candidate.patch_score is None,
            -(candidate.patch_score if candidate.patch_score is not None else 0.0),
            -candidate.score,
        )
    )
    return verified + rest


def _patch_scores(
    conn: sqlite3.Connection,
    group: list[Candidate],
    query_patches: np.ndarray,
    model_name: str,
) -> dict[PrintingKey, float]:
    condition = " OR ".join("(image.card_code = ? AND image.print_index = ?)" for _ in group)
    params: list[object] = [model_name, KIND_PATCH]
    params.extend(
        value for candidate in group for value in (candidate.card_code, candidate.print_index)
    )
    rows = conn.execute(
        f"""
        SELECT image.card_code, image.print_index, embedding.vector, embedding.dim
        FROM embeddings AS embedding
        JOIN card_images AS image ON image.id = embedding.card_image_id
        WHERE embedding.model = ? AND embedding.kind = ? AND ({condition})
        """,
        params,
    ).fetchall()

    query = np.asarray(query_patches, dtype=np.float32)
    query /= np.maximum(np.linalg.norm(query, axis=1, keepdims=True), 1e-6)

    best: dict[PrintingKey, float] = {}
    for row in rows:
        reference = from_patch_blob(row["vector"], row["dim"]).astype(np.float32)
        reference /= np.maximum(np.linalg.norm(reference, axis=1, keepdims=True), 1e-6)
        score = float(np.mean(np.sum(query * reference, axis=1)))
        key = (row["card_code"], row["print_index"])
        best[key] = max(best.get(key, -1.0), score)
    return best
