from tcg_scanner.db import init_library, open_library
from tcg_scanner.db.library import add_match, add_photo


def test_add_photo_dedupes_by_sha(tmp_path):
    db_path = tmp_path / "library.db"
    init_library(db_path)
    conn = open_library(db_path)
    try:
        first = add_photo(conn, path="a.jpg", sha256="abc")
        second = add_photo(conn, path="b.jpg", sha256="abc")
        assert first == second
        assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 1
    finally:
        conn.close()


def test_add_match_starts_pending_and_accepts_no_match(tmp_path):
    db_path = tmp_path / "library.db"
    init_library(db_path)
    conn = open_library(db_path)
    try:
        photo_id = add_photo(conn, path="a.jpg", sha256="abc")
        match_id = add_match(
            conn,
            photo_id=photo_id,
            printing_id=None,
            confidence=None,
            method="dinov2",
            created_at="2026-01-01T00:00:00Z",
        )
        row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        assert row["status"] == "pending"
        assert row["printing_id"] is None
    finally:
        conn.close()
