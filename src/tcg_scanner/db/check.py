from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CheckResult:
    owned_total: int
    unresolved_owned: tuple[int, ...]
    matches_total: int
    unresolved_matches: tuple[int, ...]
    images_total: int
    missing_files: tuple[str, ...]
    unreferenced_files: tuple[str, ...]
    unindexed_images: int

    @property
    def ok(self) -> bool:
        return not (
            self.unresolved_owned
            or self.unresolved_matches
            or self.missing_files
            or self.unreferenced_files
            or self.unindexed_images
        )


def check(conn: sqlite3.Connection, data_root: Path, model_name: str) -> CheckResult:
    """Look for user rows the catalog no longer explains, and index drift.

    Requires catalog.db attached as `catalog`.
    """
    unresolved_owned = tuple(
        row[0]
        for row in conn.execute(
            """
            SELECT owned.id
            FROM owned
            LEFT JOIN catalog.printings AS printing
                ON printing.card_code = owned.card_code
                AND printing.print_index = owned.print_index
                AND printing.image_url = owned.image_url
            WHERE printing.card_code IS NULL
            ORDER BY owned.id
            """
        )
    )
    unresolved_matches = tuple(
        row[0]
        for row in conn.execute(
            """
            SELECT match.id
            FROM matches AS match
            LEFT JOIN catalog.printings AS printing
                ON printing.card_code = match.card_code
                AND printing.print_index = match.print_index
                AND printing.image_url = match.image_url
            WHERE match.card_code IS NOT NULL
                AND match.status IN ('pending', 'accepted')
                AND printing.card_code IS NULL
            ORDER BY match.id
            """
        )
    )

    referenced = {row["path"] for row in conn.execute("SELECT path FROM card_images ORDER BY path")}
    missing_files = tuple(sorted(path for path in referenced if not (data_root / path).is_file()))

    images_root = data_root / "images"
    on_disk = (
        {
            path.relative_to(data_root).as_posix()
            for path in images_root.rglob("*")
            if path.is_file() and not path.name.startswith(".")
        }
        if images_root.is_dir()
        else set()
    )
    unreferenced_files = tuple(sorted(on_disk - referenced))

    unindexed = conn.execute(
        """
        SELECT COUNT(*)
        FROM card_images AS image
        LEFT JOIN embeddings AS global_embedding
            ON global_embedding.card_image_id = image.id
            AND global_embedding.model = ?
            AND global_embedding.kind = 'global'
        LEFT JOIN embeddings AS patch_embedding
            ON patch_embedding.card_image_id = image.id
            AND patch_embedding.model = ?
            AND patch_embedding.kind = 'patch'
        WHERE image.origin = 'reference'
            AND (global_embedding.card_image_id IS NULL OR patch_embedding.card_image_id IS NULL)
        """,
        (model_name, model_name),
    ).fetchone()[0]

    return CheckResult(
        owned_total=conn.execute("SELECT COUNT(*) FROM owned").fetchone()[0],
        unresolved_owned=unresolved_owned,
        matches_total=conn.execute(
            "SELECT COUNT(*) FROM matches WHERE status IN ('pending', 'accepted')"
        ).fetchone()[0],
        unresolved_matches=unresolved_matches,
        images_total=len(referenced),
        missing_files=missing_files,
        unreferenced_files=unreferenced_files,
        unindexed_images=unindexed,
    )
