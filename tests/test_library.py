import pytest

from tcg_scanner.db import attach_catalog, init_catalog, init_library, open_catalog, open_library
from tcg_scanner.db.library import (
    accept_match,
    add_match,
    add_owned,
    add_photo,
    collection_total,
    list_owned,
    reject_match,
    remove_owned,
    update_owned,
)

IMAGE_URL = "http://img/OP08-001_EN.webp"


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
            "INSERT INTO printings (card_code, print_index, set_code, variant_label, image_url) "
            "VALUES ('OP08-001', 0, 'OP08', 'base', ?)",
            (IMAGE_URL,),
        )
        conn.execute(
            "INSERT INTO prices (card_code, print_index, source, currency, amount, fetched_at) "
            "VALUES ('OP08-001', 0, 'tcgplayer', 'USD', 1.5, '2026-01-01')"
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


def _match(conn, **overrides):
    photo_id = add_photo(conn, path="a.jpg", sha256=f"sha-{len(overrides)}-{id(overrides)}")
    values = {
        "photo_id": photo_id,
        "card_code": "OP08-001",
        "print_index": 0,
        "card_name": "Chopper",
        "set_code": "OP08",
        "variant_label": "base",
        "image_url": IMAGE_URL,
        "confidence": 0.8,
        "method": "dinov2",
        "created_at": "2026-01-01T00:00:00Z",
    }
    values.update(overrides)
    return add_match(conn, **values)


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
        match_id = _match(
            conn,
            card_code=None,
            print_index=None,
            card_name=None,
            set_code=None,
            variant_label=None,
            image_url=None,
            confidence=None,
        )
        row = conn.execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
        assert row["status"] == "pending"
        assert row["card_code"] is None
    finally:
        conn.close()


def test_accept_match_adds_the_printing_to_owned(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        match_id = _match(conn)

        key = accept_match(conn, match_id, quantity=2, acquired_at="2026-01-02")

        assert key == ("OP08-001", 0)
        status = conn.execute("SELECT status FROM matches WHERE id = ?", (match_id,)).fetchone()[0]
        assert status == "accepted"
        owned = conn.execute("SELECT * FROM owned").fetchall()
        assert len(owned) == 1
        assert (owned[0]["card_code"], owned[0]["print_index"]) == ("OP08-001", 0)
        assert owned[0]["card_name"] == "Chopper"
        assert owned[0]["image_url"] == IMAGE_URL
        assert owned[0]["quantity"] == 2
        assert owned[0]["acquired_at"] == "2026-01-02"
    finally:
        conn.close()


def test_accept_match_twice_raises(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        match_id = _match(conn)
        accept_match(conn, match_id)
        with pytest.raises(ValueError, match="already accepted"):
            accept_match(conn, match_id)
    finally:
        conn.close()


def test_accept_match_without_printing_raises(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        match_id = _match(conn, card_code=None, print_index=None, image_url=None, confidence=None)
        with pytest.raises(ValueError, match="no printing"):
            accept_match(conn, match_id)
    finally:
        conn.close()


def test_reject_match_blocks_a_later_accept(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        match_id = _match(conn)
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
        add_owned(conn, card_code="OP08-001", print_index=0, quantity=2, acquired_at="2026-01-02")

        rows = list_owned(conn)

        assert len(rows) == 1
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
            add_owned(conn, card_code="OP08-001", print_index=9)
    finally:
        conn.close()


def test_accept_match_refuses_a_renumbered_printing(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        match_id = _match(conn, image_url="http://img/other-art.webp")
        with pytest.raises(ValueError, match="changed in the catalog"):
            accept_match(conn, match_id)
    finally:
        conn.close()


def test_owned_list_hides_prices_when_the_printing_changed(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        add_owned(conn, card_code="OP08-001", print_index=0, quantity=1)
        conn.execute(
            "UPDATE catalog.printings SET image_url = 'http://img/renumbered.webp' "
            "WHERE card_code = 'OP08-001' AND print_index = 0"
        )

        row = list_owned(conn)[0]

        assert row["card_name"] == "Chopper"
        assert row["price"] is None
    finally:
        conn.close()


def test_add_owned_merges_quantity_for_the_same_condition(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        add_owned(conn, card_code="OP08-001", print_index=0, quantity=1, acquired_at="2026-01-02")
        add_owned(conn, card_code="OP08-001", print_index=0, quantity=2, acquired_at="2026-01-03")

        rows = conn.execute("SELECT * FROM owned").fetchall()
        assert len(rows) == 1
        assert rows[0]["quantity"] == 3
    finally:
        conn.close()


def test_add_owned_keeps_different_conditions_separate(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        add_owned(conn, card_code="OP08-001", print_index=0, condition="near-mint")
        add_owned(conn, card_code="OP08-001", print_index=0, condition="played")

        assert conn.execute("SELECT COUNT(*) FROM owned").fetchone()[0] == 2
    finally:
        conn.close()


def test_update_and_remove_owned(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        owned_id = add_owned(conn, card_code="OP08-001", print_index=0, quantity=1)

        update_owned(conn, owned_id, quantity=4, condition="played", note="binder")
        row = conn.execute("SELECT * FROM owned WHERE id = ?", (owned_id,)).fetchone()
        assert row["quantity"] == 4
        assert row["condition"] == "played"
        assert row["note"] == "binder"

        remove_owned(conn, owned_id)
        assert conn.execute("SELECT COUNT(*) FROM owned").fetchone()[0] == 0

        with pytest.raises(ValueError, match="unknown owned row"):
            remove_owned(conn, owned_id)
        with pytest.raises(ValueError, match="unknown owned row"):
            update_owned(conn, 999, quantity=1)
    finally:
        conn.close()


def test_accept_match_records_condition_and_language(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        match_id = _match(conn)

        accept_match(conn, match_id, condition="near-mint", language="en")

        owned = conn.execute("SELECT * FROM owned").fetchone()
        assert owned["condition"] == "near-mint"
        assert owned["language"] == "en"
    finally:
        conn.close()


def test_collection_total_sums_prices_and_counts_unpriced(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        add_owned(conn, card_code="OP08-001", print_index=0, quantity=2)

        total, unpriced = collection_total(list_owned(conn))
        assert total == 3.0
        assert unpriced == 0

        conn.execute(
            "UPDATE catalog.printings SET image_url = 'http://img/renumbered.webp' "
            "WHERE card_code = 'OP08-001' AND print_index = 0"
        )
        total, unpriced = collection_total(list_owned(conn))
        assert total == 0.0
        assert unpriced == 1
    finally:
        conn.close()


def test_add_owned_defaults_to_japanese(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        add_owned(conn, card_code="OP08-001", print_index=0)
        row = conn.execute("SELECT language FROM owned").fetchone()
        assert row["language"] == "jp"
    finally:
        conn.close()


def test_owned_list_prefers_euro_prices(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        add_owned(conn, card_code="OP08-001", print_index=0)
        conn.execute(
            "INSERT INTO prices (card_code, print_index, source, currency, amount, fetched_at) "
            "VALUES ('OP08-001', 0, 'cardmarket', 'EUR', 1.1, '2026-01-01')"
        )

        auto = list_owned(conn)[0]
        assert auto["price"] == 1.1
        assert auto["currency"] == "EUR"

        usd = list_owned(conn, source="usd")[0]
        assert (usd["price"], usd["currency"]) == (1.5, "USD")
    finally:
        conn.close()


def test_owned_list_eur_source_does_not_fall_back(tmp_path):
    conn = _library(tmp_path, _catalog(tmp_path))
    try:
        add_owned(conn, card_code="OP08-001", print_index=0)
        row = list_owned(conn, source="eur")[0]
        assert row["price"] is None
    finally:
        conn.close()
