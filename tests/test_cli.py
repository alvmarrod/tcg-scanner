import pytest

from tcg_scanner.cli import _require_recognition


def test_require_recognition_accepts_installed_modules():
    _require_recognition("numpy")


def test_require_recognition_explains_the_extra():
    with pytest.raises(SystemExit, match="extra recognition"):
        _require_recognition("definitely_missing_module")
