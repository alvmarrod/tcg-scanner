from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass(frozen=True)
class ImageGroup:
    name: str
    images: list[Path]


def find_images(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    )


def discover_groups(directory: Path) -> list[ImageGroup]:
    """First-level folders are cards; loose images become single-photo groups."""
    if not directory.is_dir():
        return []

    groups: list[ImageGroup] = []
    used: set[str] = set()

    def unique(name: str) -> str:
        candidate = name
        suffix = 2
        while candidate in used:
            candidate = f"{name}-{suffix}"
            suffix += 1
        used.add(candidate)
        return candidate

    for entry in sorted(directory.iterdir()):
        if entry.is_dir():
            images = find_images(entry)
            if images:
                groups.append(ImageGroup(name=unique(entry.name), images=images))
        elif entry.is_file() and entry.suffix.lower() in IMAGE_SUFFIXES:
            groups.append(ImageGroup(name=unique(entry.stem), images=[entry]))
    return groups


def result_path(output_dir: Path, name: str) -> Path:
    return output_dir / f"{name}.json"
