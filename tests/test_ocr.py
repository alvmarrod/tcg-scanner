import numpy as np
import pytest

from tcg_scanner.recognition.ocr import CodeReader, normalize_code


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("OP08-001", "OP08-001"),
        ("op08 001", "OP08-001"),
        ("OPO8-OO1", "OP08-001"),
        ("OPO8- 001", "OP08-001"),
        ("  ST01-001 ", "ST01-001"),
        ("PRB01-001", "PRB01-001"),
        ("P-001", None),
    ],
)
def test_normalize_code(text, expected):
    assert normalize_code(text) == expected


def test_normalize_code_rejects_plain_text():
    assert normalize_code("Tony Tony.Chopper") is None
    assert normalize_code("Animal/Drum Kingdom") is None


def test_normalize_code_finds_a_code_after_a_word_boundary():
    text = "STRAW HAT OPO8- 001 STRIY TONY CREW"
    assert normalize_code(text) == "OP08-001"


class _FakeReader:
    def __init__(self, results):
        self.results = results

    def readtext(self, image, detail, paragraph):
        return self.results


def _box(y0, y1, x0=0, x1=600):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def _reader_with(results):
    reader = CodeReader.__new__(CodeReader)
    reader._reader = _FakeReader(results)
    return reader


def test_reader_prefers_the_bottom_band_over_confident_noise():
    image = np.zeros((1000, 600, 3), dtype=np.uint8)
    results = [
        (_box(600, 660), "AKR05-283", 0.95),
        (_box(970, 990, 400, 550), "OP15-001", 0.55),
    ]

    assert _reader_with(results).read(image) == "OP15-001"


def test_reader_joins_a_split_code():
    image = np.zeros((1000, 600, 3), dtype=np.uint8)
    results = [
        (_box(970, 990, 200, 300), "OP08-", 0.9),
        (_box(970, 990, 310, 380), "001", 0.9),
    ]

    assert _reader_with(results).read(image) == "OP08-001"


def test_reader_falls_back_to_all_detections():
    image = np.zeros((1000, 600, 3), dtype=np.uint8)
    results = [(_box(500, 540), "OP08-001", 0.9)]

    assert _reader_with(results).read(image) == "OP08-001"
