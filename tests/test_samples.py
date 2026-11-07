import cv2
import numpy as np
import pytest

from tcg_scanner.db import init_catalog, open_catalog
from tcg_scanner.samples import add_sample, list_samples, remove_sample


def _catalog(tmp_path):
    path = tmp_path / "catalog.db"
    init_catalog(path)
    conn = open_catalog(path)
    conn.execute("INSERT INTO sets (code, name, kind) VALUES ('OP15', 'Kamis', 'booster')")
    conn.execute("INSERT INTO cards (code, name, set_code) VALUES ('OP15-001', 'Krieg', 'OP15')")
    conn.execute(
        "INSERT INTO printings (card_code, print_index, set_code, image_url) "
        "VALUES ('OP15-001', 0, 'OP15', 'https://cdn/OP15-001_EN.webp')"
    )
    conn.commit()
    return conn


def _image(tmp_path):
    image = np.full((400, 300, 3), 200, dtype=np.uint8)
    path = tmp_path / "photo.jpg"
    cv2.imwrite(str(path), image)
    return path


def test_add_sample_stores_a_user_image(tmp_path):
    conn = _catalog(tmp_path)
    data_root = tmp_path / "data"
    try:
        sample = add_sample(
            conn,
            data_root,
            image=_image(tmp_path),
            card_code="OP15-001",
            print_index=0,
        )

        assert (data_root / sample.path).is_file()
        row = conn.execute("SELECT * FROM card_images").fetchone()
        assert row["origin"] == "user"
        assert row["language"] == "jp"
        assert row["path"] == sample.path
    finally:
        conn.close()


def test_add_sample_dedupes_the_same_image(tmp_path):
    conn = _catalog(tmp_path)
    data_root = tmp_path / "data"
    try:
        first = add_sample(
            conn, data_root, image=_image(tmp_path), card_code="OP15-001", print_index=0
        )
        second = add_sample(
            conn, data_root, image=_image(tmp_path), card_code="OP15-001", print_index=0
        )

        assert first.id == second.id
        assert conn.execute("SELECT COUNT(*) FROM card_images").fetchone()[0] == 1
    finally:
        conn.close()


def test_add_sample_rejects_an_unknown_printing(tmp_path):
    conn = _catalog(tmp_path)
    try:
        with pytest.raises(ValueError, match="unknown printing"):
            add_sample(
                conn,
                tmp_path / "data",
                image=_image(tmp_path),
                card_code="OP15-001",
                print_index=9,
            )
    finally:
        conn.close()


def test_list_samples_filters_by_card_code(tmp_path):
    conn = _catalog(tmp_path)
    data_root = tmp_path / "data"
    try:
        add_sample(conn, data_root, image=_image(tmp_path), card_code="OP15-001", print_index=0)

        assert len(list_samples(conn)) == 1
        assert len(list_samples(conn, card_code="OP15-001")) == 1
        assert list_samples(conn, card_code="OP01-001") == []
    finally:
        conn.close()


def test_remove_sample_deletes_the_row_and_file(tmp_path):
    conn = _catalog(tmp_path)
    data_root = tmp_path / "data"
    try:
        sample = add_sample(
            conn, data_root, image=_image(tmp_path), card_code="OP15-001", print_index=0
        )

        remove_sample(conn, data_root, sample.id)

        assert conn.execute("SELECT COUNT(*) FROM card_images").fetchone()[0] == 0
        assert not (data_root / sample.path).exists()
    finally:
        conn.close()


def test_remove_sample_rejects_an_unknown_id(tmp_path):
    conn = _catalog(tmp_path)
    try:
        with pytest.raises(ValueError, match="unknown sample"):
            remove_sample(conn, tmp_path / "data", 999)
    finally:
        conn.close()
