from __future__ import annotations

import re

import numpy as np

_TO_LETTERS = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"})
_TO_DIGITS = str.maketrans(
    {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2", "S": "5", "G": "6", "B": "8"}
)
_CANDIDATE = re.compile(r"([A-Z0-9]{1,3})[\s-]*([A-Z0-9]{2})[\s-]*([A-Z0-9]{3})")


def normalize_code(text: str) -> str | None:
    """Turn OCR output into a card code such as OP08-001, or None."""
    cleaned = re.sub(r"[^A-Z0-9\s-]", " ", text.upper())
    # Try every start position: a greedy scan would swallow the code inside a
    # preceding word ("...HAT OP08- 001" matches "HAT OPO" first).
    for start in range(len(cleaned)):
        match = _CANDIDATE.match(cleaned, start)
        if match is None:
            continue
        prefix, set_number, card_number = match.groups()
        prefix = prefix.translate(_TO_LETTERS)
        set_number = set_number.translate(_TO_DIGITS)
        card_number = card_number.translate(_TO_DIGITS)
        if not re.fullmatch(r"[A-Z]{1,3}", prefix):
            continue
        if not re.fullmatch(r"\d{1,2}", set_number):
            continue
        if not re.fullmatch(r"\d{3}", card_number):
            continue
        return f"{prefix}{int(set_number):02d}-{card_number}"
    return None


class CodeReader:
    """EasyOCR over the rectified card."""

    def __init__(self, gpu: bool | None = None) -> None:
        import easyocr
        import torch

        use_gpu = torch.cuda.is_available() if gpu is None else gpu
        self._reader = easyocr.Reader(["en"], gpu=use_gpu, verbose=False)

    def read(self, image: np.ndarray) -> str | None:
        height = image.shape[0]
        detections = self._reader.readtext(image, detail=1, paragraph=False)
        bottom = [
            detection
            for detection in detections
            if min(point[1] for point in detection[0]) >= 0.85 * height
        ]
        # The code is printed at the bottom; prefer that band so effect-text noise
        # cannot win on confidence.
        for group in (bottom, detections):
            code = _best_code(group)
            if code is not None:
                return code
        return None


def _best_code(detections: list) -> str | None:
    best: tuple[float, str] | None = None
    for _box, text, confidence in detections:
        code = normalize_code(text)
        if code is not None and (best is None or confidence > best[0]):
            best = (confidence, code)
    if best is not None:
        return best[1]
    # OCR can split "OP08-001" into "OP08-" and "001".
    return normalize_code(" ".join(text for _box, text, _confidence in detections))
