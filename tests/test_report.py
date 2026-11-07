from pathlib import Path

import numpy as np

from tcg_scanner.imaging.rectify import Rectified
from tcg_scanner.recognition.api import _recognition_warnings, fuse
from tcg_scanner.recognition.match import Candidate, SearchResult
from tcg_scanner.recognition.ocr import CodeReading
from tcg_scanner.recognition.report import build_report

CORNERS = np.array([[220, 120], [690, 180], [640, 1060], [150, 990]], dtype=np.float32)


def _candidate(**overrides):
    values = {
        "card_code": "OP15-002",
        "print_index": 2,
        "card_name": "Lucy",
        "set_code": "OP15",
        "variant_label": "aa",
        "image_url": "http://img/OP15-002_p2_JP.webp",
        "score": 0.95,
        "reference_language": "jp",
        "patch_score": 0.94,
    }
    values.update(overrides)
    return Candidate(**values)


def _recognition(name, candidates, *, code="OP15-002", code_used=True, found=True):
    from tcg_scanner.recognition.api import Recognition

    rectified = Rectified(
        image=np.zeros((838, 600, 3), dtype=np.uint8),
        found=found,
        corners=CORNERS if found else None,
        source_size=(1200, 1600),
    )
    reading = CodeReading(code=code, confidence=0.8)
    search = SearchResult(candidates=candidates, code_used=code_used)
    return Recognition(
        image=Path(name),
        rectified=rectified,
        reading=reading,
        search=search,
        candidates=candidates,
        warnings=_recognition_warnings(rectified, reading, search),
    )


def _report(candidates, *, code="OP15-002", code_used=True, found=True):
    recognition = _recognition("photo.jpg", candidates, code=code, code_used=code_used, found=found)
    return build_report(
        group="photo.jpg",
        fused=fuse([recognition]),
        prices={"eur": 0.19, "usd": 0.20, "currency": "EUR"},
    )


def test_report_describes_a_match():
    report = _report([_candidate(), _candidate(card_code="OP10-099", score=0.8)])

    assert report["status"] == "matched"
    assert report["schema_version"] == 2
    assert report["group"] == "photo.jpg"
    assert report["image"] == {"path": "photo.jpg", "width": 1200, "height": 1600}
    assert report["rectification"]["size"] == [600, 838]
    assert report["rectification"]["rotation"] == 0
    detection = report["detections"][0]
    assert detection["card_code"] == "OP15-002"
    assert detection["print_index"] == 2
    assert detection["confidence"] == 0.95
    assert detection["patch_confidence"] == 0.94
    assert detection["reference"] == {"language": "jp", "preferred": "jp", "fallback": False}
    assert detection["card"]["metadata_language"] == "en"
    assert detection["ocr"]["used_as_filter"] is True
    assert report["prices"]["currency"] == "EUR"
    assert report["warnings"] == []
    assert len(report["photos"]) == 1


def test_report_warns_about_language_fallback():
    report = _report([_candidate(reference_language="en")], code_used=True)

    codes = [warning["code"] for warning in report["warnings"]]
    assert "reference_language_fallback" in codes
    assert report["detections"][0]["reference"]["fallback"] is True


def test_report_warns_when_the_code_hint_is_ignored():
    report = _report([_candidate()], code="DFO92-850", code_used=False)

    codes = [warning["code"] for warning in report["warnings"]]
    assert "ocr_hint_ignored" in codes


def test_report_warns_when_no_card_edge_was_found():
    report = _report([_candidate()], code_used=True, found=False)

    codes = [warning["code"] for warning in report["warnings"]]
    assert "card_edge_not_found" in codes
    assert report["rectification"]["corners"] is None


def test_report_handles_no_match():
    report = _report([], code=None, code_used=False)

    assert report["status"] == "no_match"
    assert report["detections"] == []
    codes = [warning["code"] for warning in report["warnings"]]
    assert "no_match" in codes
    assert "ocr_unreadable" in codes
