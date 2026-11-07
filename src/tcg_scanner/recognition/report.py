from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from tcg_scanner.imaging.rectify import CARD_HEIGHT, CARD_WIDTH, Rectified
from tcg_scanner.recognition.match import Candidate, SearchResult
from tcg_scanner.recognition.ocr import CodeReading

SCHEMA_VERSION = 1


def build_report(
    *,
    image: Path,
    rectified: Rectified,
    reading: CodeReading,
    search: SearchResult,
    candidates: list[Candidate],
    prices: dict[str, Any],
    match_id: int,
    preferred_language: str = "jp",
    preferred_currency: str = "EUR",
) -> dict[str, Any]:
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

    top = candidates[0] if candidates else None
    if top is None:
        warnings.append({"code": "no_match", "message": "no printing matched this image"})
    elif top.reference_language != preferred_language:
        warnings.append(
            {
                "code": "reference_language_fallback",
                "message": (
                    f"no {preferred_language} reference for {top.card_code} "
                    f"#{top.print_index}; matched against {top.reference_language}"
                ),
            }
        )

    margin = None
    if len(candidates) > 1:
        margin = candidates[0].score - candidates[1].score

    detections = []
    if top is not None:
        detections.append(
            {
                "bbox": _corners(rectified),
                "card_code": top.card_code,
                "print_index": top.print_index,
                "confidence": top.score,
                "patch_confidence": top.patch_score,
                "margin": margin,
                "image_url": top.image_url,
                "card": {
                    "name": top.card_name,
                    "set_code": top.set_code,
                    "variant_label": top.variant_label,
                    "metadata_language": "en",
                },
                "reference": {
                    "language": top.reference_language,
                    "preferred": preferred_language,
                    "fallback": top.reference_language != preferred_language,
                },
                "ocr": {
                    "code": reading.code,
                    "confidence": reading.confidence,
                    "bbox": reading.bbox,
                    "used_as_filter": search.code_used,
                },
                "prices": prices,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "image": {
            "path": str(image),
            "width": rectified.source_size[0],
            "height": rectified.source_size[1],
        },
        "rectification": {
            "found": rectified.found,
            "corners": _corners(rectified),
            "size": [CARD_WIDTH, CARD_HEIGHT],
        },
        "preferences": {"language": preferred_language, "currency": preferred_currency},
        "status": "matched" if top is not None else "no_match",
        "match_id": match_id,
        "detections": detections,
        "candidates": [
            {
                "card_code": candidate.card_code,
                "print_index": candidate.print_index,
                "score": candidate.score,
                "patch_score": candidate.patch_score,
                "reference_language": candidate.reference_language,
            }
            for candidate in candidates
        ],
        "warnings": warnings,
    }


def _corners(rectified: Rectified) -> list[list[float]] | None:
    if rectified.corners is None:
        return None
    corners: np.ndarray = rectified.corners
    return [[round(float(x), 1), round(float(y), 1)] for x, y in corners]
