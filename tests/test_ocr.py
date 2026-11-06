import pytest

from tcg_scanner.recognition.ocr import normalize_code


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
