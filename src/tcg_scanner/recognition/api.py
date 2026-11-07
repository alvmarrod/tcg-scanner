from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

import cv2
import numpy as np

from tcg_scanner.imaging.rectify import Rectified, rectify_file
from tcg_scanner.recognition.embed import Embedder
from tcg_scanner.recognition.index import load_index
from tcg_scanner.recognition.match import Candidate, SearchResult, identify, verify
from tcg_scanner.recognition.ocr import CodeReader, CodeReading

OUTLIER_MARGIN = 0.15
"""Photos scoring this far below the group's best are excluded from fusion."""


@dataclass(frozen=True)
class Recognition:
    image: Path
    rectified: Rectified
    reading: CodeReading
    search: SearchResult
    candidates: list[Candidate]
    warnings: list[dict[str, str]]
    flipped: bool = False


@dataclass(frozen=True)
class FusedRecognition:
    photos: list[Recognition]
    representative: Recognition | None
    candidates: list[Candidate]
    ocr_code: str | None
    ocr_votes: dict[str, int]
    excluded: list[Path]
    warnings: list[dict[str, str]]


class Recognizer:
    """Pure recognition over images. Reads the catalog, never the user database."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        model_name: str | None = None,
        prefer: str = "jp",
        top_k: int = 5,
        origins: tuple[str, ...] = ("reference",),
        embedder: Embedder | None = None,
        reader: CodeReader | None = None,
    ) -> None:
        self.conn = conn
        self.prefer = prefer
        self.top_k = top_k
        if embedder is not None:
            self.embedder = embedder
        elif model_name is not None:
            self.embedder = Embedder(model_name)
        else:
            self.embedder = Embedder()
        self.reader = reader or CodeReader()
        self.index = load_index(conn, self.embedder.model_name, origins=origins)

    def recognize(self, image: Path, *, expansion: str | None = None) -> Recognition:
        rectified = rectify_file(image)
        upright, reading, flipped = _read_oriented(self.reader, rectified.image)
        if flipped:
            rectified = replace(
                rectified,
                image=upright,
                rotation=(rectified.rotation + 180) % 360,
            )
        code = reading.code
        if expansion and code and not code.startswith(f"{expansion.upper()}-"):
            code = None
        query, patches = self.embedder.embed_bgr(rectified.image)
        search = identify(
            self.conn,
            self.index,
            query[0],
            code=code,
            expansion=expansion,
            preferred_language=self.prefer,
            top_k=self.top_k,
        )
        candidates = verify(
            self.conn,
            search.candidates,
            patches[0],
            self.embedder.model_name,
        )
        return Recognition(
            image=image,
            rectified=rectified,
            reading=reading,
            search=search,
            candidates=candidates,
            warnings=_recognition_warnings(rectified, reading, search),
            flipped=flipped,
        )


def _read_oriented(reader: CodeReader, image: np.ndarray) -> tuple[np.ndarray, CodeReading, bool]:
    """Read the code, flipping 180 degrees if the upright crop has none."""
    reading = reader.read(image)
    if reading.code is not None:
        return image, reading, False
    flipped_image = cv2.rotate(image, cv2.ROTATE_180)
    flipped_reading = reader.read(flipped_image)
    if flipped_reading.code is not None:
        return flipped_image, flipped_reading, True
    return image, reading, False


def fuse(recognitions: list[Recognition], *, top_k: int = 5) -> FusedRecognition:
    """Combine several photos of one card into one card-level result."""
    if not recognitions:
        raise ValueError("cannot fuse an empty group")

    warnings: list[dict[str, str]] = []
    for recognition in recognitions:
        warnings.extend(
            {**warning, "photo": str(recognition.image)} for warning in recognition.warnings
        )

    scored = [recognition for recognition in recognitions if recognition.candidates]
    representative = (
        max(scored, key=lambda recognition: recognition.candidates[0].score) if scored else None
    )
    best = representative.candidates[0].score if representative is not None else None
    if best is None:
        included: list[Recognition] = []
        excluded: list[Recognition] = []
    else:
        included = [
            recognition
            for recognition in scored
            if recognition.candidates[0].score >= best - OUTLIER_MARGIN
        ]
        excluded = [
            recognition
            for recognition in scored
            if recognition.candidates[0].score < best - OUTLIER_MARGIN
        ]
        for recognition in excluded:
            warnings.append(
                {
                    "code": "photo_outlier",
                    "photo": str(recognition.image),
                    "message": (
                        f"top match {recognition.candidates[0].score:.3f} is far below "
                        f"the group best {best:.3f}; excluded from fusion"
                    ),
                }
            )

    ocr_code, ocr_votes = _vote_ocr(recognitions)
    readable = [code for code in ocr_votes if code is not None]
    if len(readable) > 1:
        warnings.append(
            {
                "code": "ocr_code_conflict",
                "message": f"photos disagree on the code: {', '.join(sorted(readable))}",
            }
        )

    best_by_key: dict[tuple[str, int], Candidate] = {}
    for recognition in included:
        for candidate in recognition.candidates:
            key = (candidate.card_code, candidate.print_index)
            current = best_by_key.get(key)
            if current is None or candidate.score > current.score:
                best_by_key[key] = candidate
    candidates = sorted(best_by_key.values(), key=lambda candidate: -candidate.score)[:top_k]

    return FusedRecognition(
        photos=recognitions,
        representative=representative,
        candidates=candidates,
        ocr_code=ocr_code,
        ocr_votes=ocr_votes,
        excluded=[recognition.image for recognition in excluded],
        warnings=warnings,
    )


def _recognition_warnings(
    rectified: Rectified,
    reading: CodeReading,
    search: SearchResult,
) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    if not rectified.found:
        warnings.append(
            {
                "code": "card_edge_not_found",
                "message": "card boundary not detected; image used unrectified",
            }
        )
    if reading.code is None:
        warnings.append({"code": "ocr_unreadable", "message": "card code could not be read"})
    elif not search.code_used:
        warnings.append(
            {
                "code": "ocr_hint_ignored",
                "message": f"code {reading.code} matched nothing; image search used instead",
            }
        )
    return warnings


def _vote_ocr(recognitions: list[Recognition]) -> tuple[str | None, dict[str, int]]:
    read_codes = [r.reading.code for r in recognitions if r.reading.code is not None]
    votes = Counter(read_codes)
    if not votes:
        return None, {}
    top_count = max(votes.values())
    tied = [code for code, count in votes.items() if count == top_count]
    if len(tied) == 1:
        return tied[0], dict(votes)

    def mean_confidence(code: str) -> float:
        values = [r.reading.confidence or 0.0 for r in recognitions if r.reading.code == code]
        return sum(values) / len(values)

    return max(tied, key=mean_confidence), dict(votes)
