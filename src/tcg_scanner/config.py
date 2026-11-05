"""Filesystem and database locations for tcg-scanner.

Everything local lives under `data/` in the checkout. Override with
`TCG_SCANNER_DATA` to point at another directory (tests, alternate libraries).
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    return Path(os.environ.get("TCG_SCANNER_DATA", PROJECT_ROOT / "data")).expanduser()


def input_dir() -> Path:
    return data_dir() / "input"


def output_dir() -> Path:
    return data_dir() / "output"


def images_dir() -> Path:
    return data_dir() / "images"


def catalog_db() -> Path:
    return data_dir() / "db" / "catalog.db"


def library_db() -> Path:
    return data_dir() / "db" / "library.db"
