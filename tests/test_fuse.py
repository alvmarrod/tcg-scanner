from pathlib import Path

import numpy as np
import pytest

from tcg_scanner.imaging.rectify import Rectified
from tcg_scanner.recognition.api import Recognition, fuse
from tcg_scanner.recognition.match import Candidate, SearchResult
from tcg_scanner.recognition.ocr import CodeReading

CORNERS = np.array([[0, 0], [600, 0], [600, 838], [0, 838]], dtype=np.float32)


def _candidate(code: str, score: float, print_index: int = 0) -> Candidate:
    return Candidate(
        card_code=code,
        print_index=print_index,
        card_name=code,
        set_code="OP15",
        variant_label="base",
        image_url=None,
        score=score,
        reference_language="jp",
    )


def _recognition(
    name: str,
    candidates: list[Candidate],
    *,
    code: str | None = "OP15-001",
    confidence: float = 0.8,
) -> Recognition:
    rectified = Rectified(
        image=np.zeros((838, 600, 3), dtype=np.uint8),
        found=True,
        corners=CORNERS,
        source_size=(1200, 1600),
    )
    reading = CodeReading(code=code, confidence=confidence)
    search = SearchResult(candidates=candidates, code_used=code is not None)
    return Recognition(
        image=Path(name),
        rectified=rectified,
        reading=reading,
        search=search,
        candidates=candidates,
        warnings=[],
    )


def test_fuse_takes_the_best_score_per_printing():
    a = _recognition("a.jpg", [_candidate("OP15-001", 0.9), _candidate("OP15-002", 0.7)])
    b = _recognition("b.jpg", [_candidate("OP15-001", 0.8), _candidate("OP15-003", 0.75)])

    fused = fuse([a, b])

    assert fused.representative is a
    assert [(c.card_code, c.score) for c in fused.candidates] == [
        ("OP15-001", 0.9),
        ("OP15-003", 0.75),
        ("OP15-002", 0.7),
    ]


def test_fuse_excludes_an_outlier_photo():
    good = _recognition("good.jpg", [_candidate("OP15-001", 0.9)])
    bad = _recognition("bad.jpg", [_candidate("OP08-067", 0.4)])

    fused = fuse([good, bad])

    assert fused.excluded == [Path("bad.jpg")]
    assert fused.candidates[0].card_code == "OP15-001"
    assert any(warning["code"] == "photo_outlier" for warning in fused.warnings)


def test_fuse_votes_on_the_ocr_code():
    photos = [
        _recognition("a.jpg", [_candidate("OP15-001", 0.9)], code="OP15-001"),
        _recognition("b.jpg", [_candidate("OP15-001", 0.8)], code="OP15-001"),
        _recognition("c.jpg", [_candidate("OP15-002", 0.7)], code="OP15-002", confidence=0.99),
    ]

    fused = fuse(photos)

    assert fused.ocr_code == "OP15-001"
    assert fused.ocr_votes == {"OP15-001": 2, "OP15-002": 1}
    assert any(warning["code"] == "ocr_code_conflict" for warning in fused.warnings)


def test_fuse_breaks_an_ocr_tie_by_confidence():
    photos = [
        _recognition("a.jpg", [_candidate("OP15-001", 0.9)], code="OP15-001", confidence=0.6),
        _recognition("b.jpg", [_candidate("OP15-002", 0.9)], code="OP15-002", confidence=0.95),
    ]

    fused = fuse(photos)

    assert fused.ocr_code == "OP15-002"


def test_fuse_rejects_an_empty_group():
    with pytest.raises(ValueError, match="empty group"):
        fuse([])


def test_read_oriented_flips_when_the_upright_crop_has_no_code():
    import cv2

    from tcg_scanner.recognition.api import _read_oriented
    from tcg_scanner.recognition.ocr import CodeReading

    class FlipReader:
        def __init__(self):
            self.calls = 0

        def read(self, image):
            self.calls += 1
            if self.calls == 1:
                return CodeReading(code=None)
            return CodeReading(code="OP15-001", confidence=0.9)

    image = np.zeros((100, 60, 3), dtype=np.uint8)
    upright, reading, flipped = _read_oriented(FlipReader(), image)

    assert flipped is True
    assert reading.code == "OP15-001"
    assert np.array_equal(upright, cv2.rotate(image, cv2.ROTATE_180))
