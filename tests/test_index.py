import numpy as np

from tcg_scanner.db import init_catalog, open_catalog
from tcg_scanner.recognition.index import build_index, from_blob, load_index, to_blob

DIM = 4


def _seed(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    conn.execute("INSERT INTO sets (code, name, kind) VALUES ('OP08', 'Two Legends', 'booster')")
    conn.execute("INSERT INTO cards (code, name, set_code) VALUES ('OP08-001', 'Chopper', 'OP08')")
    for index in (0, 1):
        conn.execute(
            "INSERT INTO printings (card_code, print_index, set_code) "
            "VALUES ('OP08-001', ?, 'OP08')",
            (index,),
        )
        conn.execute(
            "INSERT INTO card_images (card_code, print_index, path, sha256) VALUES (?, ?, ?, ?)",
            ("OP08-001", index, f"images/{index}.webp", str(index)),
        )
        path = tmp_path / "images" / f"{index}.webp"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"not really a webp")
    conn.commit()
    return conn


def _fake_embed(paths):
    vectors = np.tile(np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32), (len(paths), 1))
    patches = np.ones((len(paths), 64, DIM), dtype=np.float32)
    return vectors, patches


def test_build_index_embeds_reference_images(tmp_path):
    conn = _seed(tmp_path)
    try:
        result = build_index(conn, tmp_path, _fake_embed, "fake-model")

        assert result.embedded == 2
        assert result.missing == 0
        rows = conn.execute("SELECT * FROM embeddings ORDER BY card_image_id").fetchall()
        assert len(rows) == 4
        assert {row["model"] for row in rows} == {"fake-model"}
        assert {row["kind"] for row in rows} == {"global", "patch"}
        assert {row["dim"] for row in rows} == {DIM}
        global_row = next(row for row in rows if row["kind"] == "global")
        decoded = from_blob(global_row["vector"], DIM)
        assert decoded.dtype == np.float16
        assert np.allclose(decoded, [1.0, 0.0, 0.0, 0.0])
    finally:
        conn.close()


def test_build_index_is_incremental(tmp_path):
    conn = _seed(tmp_path)
    try:
        build_index(conn, tmp_path, _fake_embed, "fake-model")
        again = build_index(conn, tmp_path, _fake_embed, "fake-model")
        assert again.embedded == 0
        assert conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0] == 4
    finally:
        conn.close()


def test_build_index_repairs_missing_patch_embeddings(tmp_path):
    conn = _seed(tmp_path)
    try:
        build_index(conn, tmp_path, _fake_embed, "fake-model")
        conn.execute("DELETE FROM embeddings WHERE kind = 'patch'")

        result = build_index(conn, tmp_path, _fake_embed, "fake-model")

        assert result.embedded == 2
        assert (
            conn.execute("SELECT COUNT(*) FROM embeddings WHERE kind = 'patch'").fetchone()[0] == 2
        )
    finally:
        conn.close()


def test_build_index_skips_missing_files(tmp_path):
    conn = _seed(tmp_path)
    try:
        conn.execute(
            "INSERT INTO printings (card_code, print_index, set_code) "
            "VALUES ('OP08-001', 2, 'OP08')"
        )
        conn.execute(
            "INSERT INTO card_images (card_code, print_index, path, sha256) "
            "VALUES ('OP08-001', 2, 'images/gone.webp', 'x')"
        )
        result = build_index(conn, tmp_path, _fake_embed, "fake-model")
        assert result.embedded == 2
        assert result.missing == 1
    finally:
        conn.close()


def test_blob_round_trip():
    vector = np.array([0.1, -0.2, 0.3, 0.4], dtype=np.float32)
    assert np.allclose(from_blob(to_blob(vector), 4), vector, atol=1e-3)


def test_load_index_filters_origins(tmp_path):
    conn = _seed(tmp_path)
    try:
        build_index(conn, tmp_path, _fake_embed, "fake-model")
        conn.execute(
            "UPDATE card_images SET origin = 'user' WHERE id = (SELECT MIN(id) FROM card_images)"
        )
        conn.commit()

        assert len(load_index(conn, "fake-model")) == 1
        assert len(load_index(conn, "fake-model", origins=("reference", "user"))) == 2
    finally:
        conn.close()


def test_build_index_embeds_user_samples(tmp_path):
    conn = _seed(tmp_path)
    try:
        conn.execute("UPDATE card_images SET origin = 'user'")
        conn.commit()

        result = build_index(conn, tmp_path, _fake_embed, "fake-model")

        assert result.embedded == 2
        assert conn.execute("SELECT COUNT(DISTINCT origin) FROM card_images").fetchone()[0] == 1
    finally:
        conn.close()
