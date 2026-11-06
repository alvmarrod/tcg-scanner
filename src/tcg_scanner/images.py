from __future__ import annotations

import hashlib
from pathlib import Path


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def store_image(data: bytes, data_root: Path, suffix: str = ".webp") -> tuple[Path, str]:
    """Write bytes content-addressed under data_root/images and return (path, sha256)."""
    digest = hashlib.sha256(data).hexdigest()
    path = data_root / "images" / digest[:2] / digest[2:4] / f"{digest}{suffix}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return path, digest
