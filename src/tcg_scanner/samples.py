from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import cv2

from tcg_scanner.imaging.rectify import rectify_file


@dataclass(frozen=True)
class AddedSample:
    id: int
    path: str
    rectified: bool


def add_sample(
    conn: sqlite3.Connection,
    data_root: Path,
    *,
    image: Path,
    card_code: str,
    print_index: int,
    language: str = "jp",
) -> AddedSample:
    printing = conn.execute(
        "SELECT 1 FROM printings WHERE card_code = ? AND print_index = ?",
        (card_code, print_index),
    ).fetchone()
    if printing is None:
        raise ValueError(f"unknown printing: {card_code} #{print_index}")

    rectified = rectify_file(image)
    ok, encoded = cv2.imencode(".jpg", rectified.image)
    if not ok:
        raise OSError(f"could not encode {image}")
    data = encoded.tobytes()
    sha256 = hashlib.sha256(data).hexdigest()
    relative = Path("samples") / card_code / str(print_index) / f"{sha256}.jpg"

    existing = conn.execute(
        "SELECT id FROM card_images WHERE card_code = ? AND print_index = ? AND sha256 = ?",
        (card_code, print_index, sha256),
    ).fetchone()
    if existing is not None:
        return AddedSample(id=existing["id"], path=relative.as_posix(), rectified=rectified.found)

    path = data_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    cursor = conn.execute(
        """
        INSERT INTO card_images (card_code, print_index, language, path, sha256, origin)
        VALUES (?, ?, ?, ?, ?, 'user')
        """,
        (card_code, print_index, language, relative.as_posix(), sha256),
    )
    conn.commit()
    return AddedSample(
        id=int(cursor.lastrowid),
        path=relative.as_posix(),
        rectified=rectified.found,
    )


def list_samples(conn: sqlite3.Connection, *, card_code: str | None = None) -> list[sqlite3.Row]:
    clause = "AND card_code = ?" if card_code is not None else ""
    params: tuple[object, ...] = (card_code,) if card_code is not None else ()
    return conn.execute(
        f"""
        SELECT id, card_code, print_index, language, path, sha256
        FROM card_images
        WHERE origin = 'user' {clause}
        ORDER BY card_code, print_index, id
        """,
        params,
    ).fetchall()


def remove_sample(conn: sqlite3.Connection, data_root: Path, sample_id: int) -> str:
    row = conn.execute(
        "SELECT path FROM card_images WHERE id = ? AND origin = 'user'",
        (sample_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"unknown sample: {sample_id}")

    conn.execute("DELETE FROM card_images WHERE id = ?", (sample_id,))
    conn.commit()

    remaining = conn.execute(
        "SELECT 1 FROM card_images WHERE path = ? LIMIT 1", (row["path"],)
    ).fetchone()
    if remaining is None:
        file_path = data_root / row["path"]
        if file_path.is_file():
            file_path.unlink()
        # Drop the now-empty <code>/<print_index> folders, never the samples root.
        for directory in (file_path.parent, file_path.parent.parent):
            try:
                directory.rmdir()
            except OSError:
                break
    return row["path"]
