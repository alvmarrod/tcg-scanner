from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

EmbedFn = Callable[[list[Path]], tuple[np.ndarray, np.ndarray]]
Progress = Callable[[int, int], None]

# Global descriptors rank candidates; pooled patch tokens verify close calls.
KIND_GLOBAL = "global"
KIND_PATCH = "patch"


@dataclass(frozen=True)
class IndexResult:
    embedded: int
    missing: int


@dataclass(frozen=True)
class ReferenceIndex:
    vectors: np.ndarray
    key_ids: np.ndarray
    keys: list[tuple[str, int]]
    card_codes: list[str]

    def __len__(self) -> int:
        return len(self.key_ids)


def load_index(conn: sqlite3.Connection, model_name: str) -> ReferenceIndex:
    rows = conn.execute(
        """
        SELECT embedding.vector, embedding.dim,
               image.card_code, image.print_index
        FROM embeddings AS embedding
        JOIN card_images AS image ON image.id = embedding.card_image_id
        WHERE embedding.model = ? AND embedding.kind = ?
        ORDER BY embedding.card_image_id
        """,
        (model_name, KIND_GLOBAL),
    ).fetchall()

    if not rows:
        return ReferenceIndex(
            vectors=np.zeros((0, 0), dtype=np.float32),
            key_ids=np.zeros(0, dtype=np.int64),
            keys=[],
            card_codes=[],
        )

    vectors = np.stack([from_blob(row["vector"], row["dim"]).astype(np.float32) for row in rows])
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    vectors /= np.maximum(norms, 1e-6)

    key_ids: list[int] = []
    keys: list[tuple[str, int]] = []
    assigned: dict[tuple[str, int], int] = {}
    for row in rows:
        key = (row["card_code"], row["print_index"])
        if key not in assigned:
            assigned[key] = len(keys)
            keys.append(key)
        key_ids.append(assigned[key])

    return ReferenceIndex(
        vectors=vectors,
        key_ids=np.array(key_ids, dtype=np.int64),
        keys=keys,
        card_codes=[row["card_code"] for row in rows],
    )


def build_index(
    conn: sqlite3.Connection,
    data_root: Path,
    embed: EmbedFn,
    model_name: str,
    *,
    batch_size: int = 8,
    limit: int | None = None,
    on_progress: Progress | None = None,
) -> IndexResult:
    query = """
        SELECT image.id, image.path
        FROM card_images AS image
        LEFT JOIN embeddings AS global_embedding
            ON global_embedding.card_image_id = image.id
            AND global_embedding.model = ?
            AND global_embedding.kind = ?
        LEFT JOIN embeddings AS patch_embedding
            ON patch_embedding.card_image_id = image.id
            AND patch_embedding.model = ?
            AND patch_embedding.kind = ?
        WHERE image.origin = 'reference'
            AND (global_embedding.card_image_id IS NULL OR patch_embedding.card_image_id IS NULL)
        ORDER BY image.id
    """
    params: list[object] = [model_name, KIND_GLOBAL, model_name, KIND_PATCH]
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    rows = conn.execute(query, params).fetchall()
    total = len(rows)

    embedded = missing = 0
    batch: list[tuple[int, Path]] = []
    for row in rows:
        path = data_root / row["path"]
        if path.is_file():
            batch.append((row["id"], path))
        else:
            missing += 1
        if len(batch) == batch_size:
            embedded += _embed_batch(conn, embed, model_name, batch)
            batch = []
            if on_progress is not None:
                on_progress(embedded, total)

    embedded += _embed_batch(conn, embed, model_name, batch)
    if on_progress is not None:
        on_progress(embedded, total)
    conn.commit()
    return IndexResult(embedded=embedded, missing=missing)


def to_blob(vector: np.ndarray) -> bytes:
    return vector.astype(np.float16).tobytes()


def from_blob(blob: bytes, dim: int) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float16).reshape(dim)


def from_patch_blob(blob: bytes, dim: int) -> np.ndarray:
    """Patch tokens keep `dim` columns and one row per grid cell."""
    return np.frombuffer(blob, dtype=np.float16).reshape(-1, dim)


def _embed_batch(
    conn: sqlite3.Connection,
    embed: EmbedFn,
    model_name: str,
    batch: list[tuple[int, Path]],
) -> int:
    if not batch:
        return 0

    vectors, patches = embed([path for _, path in batch])
    for (image_id, _), vector, patch in zip(batch, vectors, patches, strict=True):
        conn.execute(
            """
            INSERT OR REPLACE INTO embeddings (card_image_id, model, dim, kind, vector)
            VALUES (?, ?, ?, ?, ?)
            """,
            (image_id, model_name, len(vector), KIND_GLOBAL, to_blob(vector)),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO embeddings (card_image_id, model, dim, kind, vector)
            VALUES (?, ?, ?, ?, ?)
            """,
            (image_id, model_name, patch.shape[1], KIND_PATCH, to_blob(patch)),
        )
    conn.commit()
    return len(batch)
