import pytest

from tcg_scanner.db import attach_catalog, init_catalog, init_library, open_catalog, open_library
from tcg_scanner.db.library import (
    accept_match,
    add_match,
    add_owned,
    add_photo,
    list_owned,
    reject_match,
)


def _catalog(tmp_path):
    path = tmp_path / "catalog.db"
    init_catalog(path)
    conn = open_catalog(path)
    try:
        conn.execute(
            "INSERT INTO sets (code, name, kind) VALUES ('OP08', 'Two Legends', 'booster')"
        )
        conn.execute(
            "INSERT INTO cards (code, name, set_code) VALUES ('OP08-001', 'Chopper', 'OP08')"
        )
        conn.execute(
            "INSERT INTO printings (id, card_code, set_code, variant_label) "
            "VALUES (5, 'OP08-001', 'OP08', 'base')"
        )
        conn.execute(
            "INSERT INTO prices (printing_id, source, currency, amount, fetched_at) "
            "VALUES (5, 'tcgplayer', 'USD', 1.5, '2026-01-01')"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _library(tmp_path, catalog_path):
    path = tmp_path / "library.db"
    init_library(path)
    conn = open_library(path)
    attach_catalog(conn, catalog_path)
    return conn


def test_add_photo_dedupes_by_sha(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        first = add_photo(conn, path="a.jpg", sha256="abc")
        second = add_photo(conn, path="b.jpg", sha256="abc")
        assert first == second
        assert conn.execute("SELECT COUNT(*) FROM photos").fetchone()[0] == 1
    finally:
        conn.close()


def test_add_match_starts_pending_and_accepts_no_match(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
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


def test_accept_match_adds_the_printing_to_owned(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        photo_id = add_photo(conn, path="a.jpg", sha256="abc")
        match_id = add_match(
            conn,
            photo_id=photo_id,
            printing_id=5,
            confidence=0.8,
            method="ocr+dinov2",
            created_at="2026-01-01T00:00:00Z",
        )

        printing_id = accept_match(conn, match_id, quantity=2, acquired_at="2026-01-02")

        assert printing_id == 5
        status = conn.execute("SELECT status FROM matches WHERE id = ?", (match_id,)).fetchone()[0]
        assert status == "accepted"
        owned = conn.execute("SELECT * FROM owned").fetchall()
        assert len(owned) == 1
        assert owned[0]["printing_id"] == 5
        assert owned[0]["quantity"] == 2
        assert owned[0]["acquired_at"] == "2026-01-02"
    finally:
        conn.close()


def test_accept_match_twice_raises(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        photo_id = add_photo(conn, path="a.jpg", sha256="abc")
        match_id = add_match(
            conn,
            photo_id=photo_id,
            printing_id=5,
            confidence=0.8,
            method="dinov2",
            created_at="2026-01-01T00:00:00Z",
        )
        accept_match(conn, match_id)
        with pytest.raises(ValueError, match="already accepted"):
            accept_match(conn, match_id)
    finally:
        conn.close()


def test_accept_match_without_printing_raises(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
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
        with pytest.raises(ValueError, match="no printing"):
            accept_match(conn, match_id)
    finally:
        conn.close()


def test_reject_match_blocks_a_later_accept(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        photo_id = add_photo(conn, path="a.jpg", sha256="abc")
        match_id = add_match(
            conn,
            photo_id=photo_id,
            printing_id=5,
            confidence=0.8,
            method="dinov2",
            created_at="2026-01-01T00:00:00Z",
        )
        reject_match(conn, match_id)
        status = conn.execute("SELECT status FROM matches WHERE id = ?", (match_id,)).fetchone()[0]
        assert status == "rejected"
        with pytest.raises(ValueError, match="already rejected"):
            accept_match(conn, match_id)
    finally:
        conn.close()


def test_owned_list_joins_the_latest_price(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        add_owned(conn, printing_id=5, quantity=2, acquired_at="2026-01-02")

        rows = list_owned(conn)

        assert len(rows) == 1
        assert rows[0]["card_code"] == "OP08-001"
        assert rows[0]["card_name"] == "Chopper"
        assert rows[0]["quantity"] == 2
        assert rows[0]["price"] == 1.5
        assert rows[0]["currency"] == "USD"
    finally:
        conn.close()


def test_add_owned_rejects_an_unknown_printing(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        with pytest.raises(ValueError, match="unknown printing"):
            add_owned(conn, printing_id=999)
    finally:
        conn.close()
