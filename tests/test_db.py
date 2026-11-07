import sqlite3
from pathlib import Path

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


def test_init_sets_the_schema_version(tmp_path):
    from tcg_scanner.db import conn as conn_module

    for init, name in ((init_catalog, "catalog"), (init_library, "library")):
        path = tmp_path / f"{name}.db"
        init(path)
        conn = open_catalog(path) if name == "catalog" else open_library(path)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            assert version == conn_module.SCHEMA_VERSIONS[name]
        finally:
            conn.close()


def test_refuses_a_database_from_a_newer_version(tmp_path):
    path = tmp_path / "catalog.db"
    init_catalog(path)
    conn = open_catalog(path)
    try:
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(RuntimeError, match="newer than supported"):
        init_catalog(path)


def test_applies_pending_migrations(tmp_path, monkeypatch):
    from tcg_scanner.db import conn as conn_module

    path = tmp_path / "catalog.db"
    init_catalog(path)
    monkeypatch.setitem(
        conn_module.MIGRATIONS["catalog"],
        4,
        "ALTER TABLE sets ADD COLUMN extra TEXT;",
    )
    monkeypatch.setitem(conn_module.SCHEMA_VERSIONS, "catalog", 4)

    init_catalog(path)

    conn = open_catalog(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 4
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(sets)")}
        assert "extra" in columns
    finally:
        conn.close()


def test_v1_catalog_backfills_image_language(tmp_path):
    from tcg_scanner.db import conn as conn_module

    path = tmp_path / "catalog.db"
    conn = conn_module.connect(path)
    schema = (Path(conn_module.__file__).parent / "schema_catalog.sql").read_text()
    conn.executescript(schema)
    conn.execute("PRAGMA user_version = 1")
    conn.execute("INSERT INTO sets (code, name, kind) VALUES ('OP08', 'Two Legends', 'booster')")
    conn.execute("INSERT INTO cards (code, name, set_code) VALUES ('OP08-001', 'Chopper', 'OP08')")
    for index, suffix in ((0, "EN"), (1, "JP")):
        conn.execute(
            "INSERT INTO printings (card_code, print_index, set_code, image_url) "
            "VALUES ('OP08-001', ?, 'OP08', ?)",
            (index, f"https://cdn/OP08-001_p{index}_{suffix}.webp"),
        )
        conn.execute(
            "INSERT INTO card_images (card_code, print_index, path, sha256) "
            "VALUES ('OP08-001', ?, ?, ?)",
            (index, f"images/{index}.webp", str(index)),
        )
    conn.commit()
    conn.close()

    init_catalog(path)

    conn = open_catalog(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        languages = dict(conn.execute("SELECT print_index, language FROM card_images").fetchall())
        assert languages == {0: "en", 1: "jp"}
    finally:
        conn.close()


def test_v2_migration_moves_duplicate_english_art_to_a_miss(tmp_path):
    from tcg_scanner.db import conn as conn_module

    path = tmp_path / "catalog.db"
    conn = conn_module.connect(path)
    schema = (Path(conn_module.__file__).parent / "schema_catalog.sql").read_text()
    conn.executescript(schema)
    conn.executescript(conn_module.MIGRATIONS["catalog"][2])
    conn.execute("PRAGMA user_version = 2")
    conn.execute("INSERT INTO sets (code, name, kind) VALUES ('OP15', 'Kamis', 'booster')")
    conn.execute("INSERT INTO cards (code, name, set_code) VALUES ('OP15-002', 'Lucy', 'OP15')")
    conn.execute(
        "INSERT INTO printings (card_code, print_index, set_code, image_url) "
        "VALUES ('OP15-002', 2, 'OP15', 'https://cdn/OP15/OP15-002_p2_EN.webp')"
    )
    for language in ("en", "jp"):
        conn.execute(
            "INSERT INTO card_images (card_code, print_index, language, path, sha256) "
            "VALUES ('OP15-002', 2, ?, 'images/shared.webp', 'sha')",
            (language,),
        )
    conn.commit()
    conn.close()

    init_catalog(path)

    conn = open_catalog(path)
    try:
        rows = conn.execute("SELECT language FROM card_images").fetchall()
        assert [row[0] for row in rows] == ["en"]
        misses = conn.execute("SELECT language FROM image_misses").fetchall()
        assert [row[0] for row in misses] == ["jp"]
    finally:
        conn.close()


def test_library_schema_has_reviews_and_version_two(tmp_path):
    path = tmp_path / "library.db"
    init_library(path)
    conn = open_library(path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
        assert "reviews" in names
    finally:
        conn.close()
