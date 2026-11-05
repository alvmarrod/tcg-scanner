from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

EmbedFn = Callable[[list[Path]], np.ndarray]

# Global descriptors only for now; patch tokens are deferred until matching needs them.
KIND_GLOBAL = "global"


@dataclass(frozen=True)
class IndexResult:
    embedded: int
    missing: int


def build_index(
    conn: sqlite3.Connection,
    data_root: Path,
    embed: EmbedFn,
    model_name: str,
    *,
    batch_size: int = 8,
    limit: int | None = None,
) -> IndexResult:
    query = """
        SELECT image.id, image.path
        FROM card_images AS image
        LEFT JOIN embeddings AS embedding
            ON embedding.card_image_id = image.id
            AND embedding.model = ?
            AND embedding.kind = ?
        WHERE image.origin = 'reference' AND embedding.card_image_id IS NULL
        ORDER BY image.id
    """
    params: list[object] = [model_name, KIND_GLOBAL]
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    embedded = missing = 0
    batch: list[tuple[int, Path]] = []
    for row in conn.execute(query, params):
        path = data_root / row["path"]
        if path.is_file():
            batch.append((row["id"], path))
        else:
            missing += 1
        if len(batch) == batch_size:
            embedded += _embed_batch(conn, embed, model_name, batch)
            batch = []

    embedded += _embed_batch(conn, embed, model_name, batch)
    conn.commit()
    return IndexResult(embedded=embedded, missing=missing)


def to_blob(vector: np.ndarray) -> bytes:
    return vector.astype(np.float16).tobytes()


def from_blob(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float16).reshape(dim)


def _embed_batch(
    conn: sqlite3.Connection,
    embed: EmbedFn,
    model_name: str,
    batch: list[tuple[int, Path]],
) -> int:
    if not batch:
        return 0

    vectors = embed([path for _, path in batch])
    for (image_id, _), vector in zip(batch, vectors, strict=True):
        conn.execute(
            """
            INSERT OR REPLACE INTO embeddings (card_image_id, model, dim, kind, vector)
            VALUES (?, ?, ?, ?, ?)
            """,
            (image_id, model_name, len(vector), KIND_GLOBAL, to_blob(vector)),
        )
    conn.commit()
    return len(batch)
