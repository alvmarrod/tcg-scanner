"""Filesystem and database locations for tcg-scanner.

Everything local lives under `data/` in the checkout. Override with
`TCG_SCANNER_DATA` to point at another directory (tests, alternate libraries).
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _default_data_dir() -> Path:
    # A checkout keeps its data beside the project; an installed tool has no
    # checkout to anchor to, so it uses the working directory.
    if (PROJECT_ROOT / "pyproject.toml").is_file():
        return PROJECT_ROOT / "data"
    return Path.cwd() / "data"


def data_dir() -> Path:
    override = os.environ.get("TCG_SCANNER_DATA")
    return Path(override).expanduser() if override else _default_data_dir()


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
