import sqlite3

import pytest

from tcg_scanner import cli
from tcg_scanner.db import init_catalog, init_library, open_catalog, open_library


def tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {row[0] for row in rows}


def test_init_is_idempotent(tmp_path):
    catalog = tmp_path / "catalog.db"
    library = tmp_path / "library.db"

    init_catalog(catalog)
    init_catalog(catalog)
    init_library(library)
    init_library(library)

    with open_catalog(catalog) as conn:
        assert {"sets", "cards", "printings", "card_images", "prices", "embeddings"} <= tables(conn)
    with open_library(library) as conn:
        assert {"photos", "matches", "owned", "settings"} <= tables(conn)


def test_foreign_keys_are_enforced(tmp_path):
    catalog = tmp_path / "catalog.db"
    init_catalog(catalog)
    conn = open_catalog(catalog)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO printings (card_code, set_code) VALUES ('OP08-001', 'OP08')")
    finally:
        conn.close()


def test_printing_uniqueness_is_per_card_and_print_index(tmp_path):
    catalog = tmp_path / "catalog.db"
    init_catalog(catalog)
    conn = open_catalog(catalog)
    try:
        conn.execute(
            "INSERT INTO sets (code, name, kind) VALUES ('OP08', 'Two Legends', 'booster')"
        )
        conn.execute(
            "INSERT INTO cards (code, name, set_code) VALUES ('OP08-001', 'Luffy', 'OP08')"
        )
        row = (
            "INSERT INTO printings (card_code, set_code, print_index) "
            "VALUES ('OP08-001', 'OP08', 0)"
        )
        conn.execute(row)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(row)
        conn.execute(
            "INSERT INTO printings (card_code, set_code, print_index, variant_label) "
            "VALUES ('OP08-001', 'OP08', 1, 'aa')"
        )
        assert conn.execute("SELECT COUNT(*) FROM printings").fetchone()[0] == 2
    finally:
        conn.close()


def test_match_status_defaults_to_pending(tmp_path):
    library = tmp_path / "library.db"
    init_library(library)
    conn = open_library(library)
    try:
        conn.execute("INSERT INTO photos (path, sha256) VALUES ('a.jpg', 'deadbeef')")
        conn.execute(
            "INSERT INTO matches (photo_id, created_at) VALUES (1, '2026-01-01T00:00:00Z')"
        )
        assert conn.execute("SELECT status FROM matches").fetchone()[0] == "pending"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO matches (photo_id, status, created_at) "
                "VALUES (1, 'maybe', '2026-01-01T00:00:00Z')"
            )
    finally:
        conn.close()


def test_cli_db_init_uses_the_data_dir_override(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TCG_SCANNER_DATA", str(tmp_path))

    assert cli.main(["db", "init"]) == 0

    assert (tmp_path / "db" / "catalog.db").exists()
    assert (tmp_path / "db" / "library.db").exists()
    assert "initialized" in capsys.readouterr().out
