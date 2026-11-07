from __future__ import annotations

from typing import Any

import numpy as np

from tcg_scanner.imaging.rectify import CARD_HEIGHT, CARD_WIDTH, Rectified
from tcg_scanner.recognition.api import FusedRecognition
from tcg_scanner.recognition.ocr import CodeReading

SCHEMA_VERSION = 2


def build_report(
    *,
    group: str,
    fused: FusedRecognition,
    prices: dict[str, Any],
    preferred_language: str = "jp",
    preferred_currency: str = "EUR",
) -> dict[str, Any]:
    representative = fused.representative or fused.photos[0]
    warnings = list(fused.warnings)
    top = fused.candidates[0] if fused.candidates else None
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
    if len(fused.candidates) > 1:
        margin = fused.candidates[0].score - fused.candidates[1].score

    detections = []
    if top is not None:
        detections.append(
            {
                "bbox": _corners(representative.rectified),
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
                "ocr": _detection_ocr(fused),
                "photos_used": len(fused.photos) - len(fused.excluded),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "group": group,
        "image": {
            "path": str(representative.image),
            "width": representative.rectified.source_size[0],
            "height": representative.rectified.source_size[1],
        },
        "rectification": {
            "found": representative.rectified.found,
            "corners": _corners(representative.rectified),
            "size": [CARD_WIDTH, CARD_HEIGHT],
        },
        "preferences": {"language": preferred_language, "currency": preferred_currency},
        "status": "matched" if top is not None else "no_match",
        "detections": detections,
        "photos": [
            {
                "image": str(recognition.image),
                "ocr": {
                    "code": recognition.reading.code,
                    "confidence": recognition.reading.confidence,
                },
                "top": (
                    {
                        "card_code": recognition.candidates[0].card_code,
                        "print_index": recognition.candidates[0].print_index,
                        "score": recognition.candidates[0].score,
                    }
                    if recognition.candidates
                    else None
                ),
                "excluded": recognition.image in fused.excluded,
                "warnings": recognition.warnings,
            }
            for recognition in fused.photos
        ],
        "candidates": [
            {
                "card_code": candidate.card_code,
                "print_index": candidate.print_index,
                "score": candidate.score,
                "patch_score": candidate.patch_score,
                "reference_language": candidate.reference_language,
            }
            for candidate in fused.candidates
        ],
        "prices": prices,
        "warnings": warnings,
    }


def _detection_ocr(fused: FusedRecognition) -> dict[str, Any]:
    matching = next(
        (recognition for recognition in fused.photos if recognition.reading.code == fused.ocr_code),
        None,
    )
    reading: CodeReading | None = matching.reading if matching is not None else None
    return {
        "code": fused.ocr_code,
        "confidence": reading.confidence if reading is not None else None,
        "bbox": reading.bbox if reading is not None else None,
        "votes": fused.ocr_votes,
        "used_as_filter": any(recognition.search.code_used for recognition in fused.photos),
    }


def _corners(rectified: Rectified) -> list[list[float]] | None:
    if rectified.corners is None:
        return None
    corners: np.ndarray = rectified.corners
    return [[round(float(x), 1), round(float(y), 1)] for x, y in corners]
