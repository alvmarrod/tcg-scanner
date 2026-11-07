import numpy as np

from tcg_scanner.db import attach_catalog, init_catalog, init_library, open_catalog, open_library
from tcg_scanner.db.check import check
from tcg_scanner.db.library import add_match, add_owned, add_photo
from tcg_scanner.recognition.index import to_blob

IMAGE_URL = "http://img/OP08-001_EN.webp"
IMAGE_PATH = "images/aa/bb/card.webp"
MODEL = "m"


def _setup(tmp_path):
    catalog_path = tmp_path / "catalog.db"
    init_catalog(catalog_path)
    catalog = open_catalog(catalog_path)
    catalog.execute("INSERT INTO sets (code, name, kind) VALUES ('OP08', 'Two Legends', 'booster')")
    catalog.execute(
        "INSERT INTO cards (code, name, set_code) VALUES ('OP08-001', 'Chopper', 'OP08')"
    )
    catalog.execute(
        "INSERT INTO printings (card_code, print_index, set_code, variant_label, image_url) "
        "VALUES ('OP08-001', 0, 'OP08', 'base', ?)",
        (IMAGE_URL,),
    )
    catalog.execute(
        "INSERT INTO card_images (card_code, print_index, path, sha256) "
        "VALUES ('OP08-001', 0, ?, 'sha')",
        (IMAGE_PATH,),
    )
    image_id = catalog.execute("SELECT id FROM card_images").fetchone()[0]
    catalog.execute(
        "INSERT INTO embeddings (card_image_id, model, dim, kind, vector) "
        "VALUES (?, ?, 4, 'global', ?)",
        (image_id, MODEL, to_blob(np.ones(4, dtype=np.float32))),
    )
    catalog.execute(
        "INSERT INTO embeddings (card_image_id, model, dim, kind, vector) "
        "VALUES (?, ?, 4, 'patch', ?)",
        (image_id, MODEL, to_blob(np.ones((2, 4), dtype=np.float32))),
    )
    catalog.commit()
    catalog.close()

    image_file = tmp_path / IMAGE_PATH
    image_file.parent.mkdir(parents=True)
    image_file.write_bytes(b"image")

    library_path = tmp_path / "library.db"
    init_library(library_path)
    conn = open_library(library_path)
    attach_catalog(conn, catalog_path)
    add_owned(conn, card_code="OP08-001", print_index=0, quantity=1)
    photo_id = add_photo(conn, path="photo.jpg", sha256="photo")
    add_match(
        conn,
        photo_id=photo_id,
        card_code="OP08-001",
        print_index=0,
        card_name="Chopper",
        set_code="OP08",
        variant_label="base",
        image_url=IMAGE_URL,
        confidence=0.9,
        method="dinov2",
        created_at="2026-01-01T00:00:00Z",
    )
    conn.commit()
    return conn, tmp_path


def test_clean_database_reports_nothing(tmp_path):
    conn, data_root = _setup(tmp_path)
    try:
        result = check(conn, data_root, MODEL)

        assert result.ok
        assert result.owned_total == 1
        assert result.matches_total == 1
        assert result.images_total == 1
        assert result.unindexed_images == 0
        assert result.user_samples == 0
    finally:
        conn.close()


def test_check_reports_drift(tmp_path):
    conn, data_root = _setup(tmp_path)
    try:
        (data_root / IMAGE_PATH).unlink()
        orphan = data_root / "images" / "zz" / "orphan.webp"
        orphan.parent.mkdir(parents=True)
        orphan.write_bytes(b"orphan")
        conn.execute("DELETE FROM embeddings")
        conn.execute("UPDATE catalog.printings SET image_url = 'http://img/changed.webp'")
        photo_id = add_photo(conn, path="other.jpg", sha256="other")
        add_match(
            conn,
            photo_id=photo_id,
            card_code="ZZ99-999",
            print_index=0,
            card_name=None,
            set_code=None,
            variant_label=None,
            image_url=None,
            confidence=0.1,
            method="dinov2",
            created_at="2026-01-02T00:00:00Z",
        )

        result = check(conn, data_root, MODEL)

        assert not result.ok
        assert result.unresolved_owned == (1,)
        assert result.unresolved_matches == (1, 2)
        assert result.missing_files == (IMAGE_PATH,)
        assert result.unreferenced_files == ("images/zz/orphan.webp",)
        assert result.unindexed_images == 1
    finally:
        conn.close()
