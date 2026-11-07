import numpy as np

from tcg_scanner.db import init_catalog, open_catalog
from tcg_scanner.recognition.index import load_index, to_blob
from tcg_scanner.recognition.match import rank

COUNT = 10_000
DIM = 384


def test_index_and_rank_at_full_catalog_size(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        rng = np.random.default_rng(0)
        vectors = rng.normal(size=(COUNT, DIM)).astype(np.float32)
        vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

        conn.execute("INSERT INTO sets (code, name, kind) VALUES ('SCALE', 'Scale', 'booster')")
        conn.executemany(
            "INSERT INTO cards (code, name, set_code) VALUES (?, ?, 'SCALE')",
            [(f"SCALE{i:05d}", f"Card {i}") for i in range(COUNT)],
        )
        conn.executemany(
            "INSERT INTO printings (card_code, print_index, set_code) VALUES (?, 0, 'SCALE')",
            [(f"SCALE{i:05d}",) for i in range(COUNT)],
        )
        conn.executemany(
            "INSERT INTO card_images (card_code, print_index, path, sha256) VALUES (?, 0, ?, ?)",
            [(f"SCALE{i:05d}", f"images/{i}.webp", str(i)) for i in range(COUNT)],
        )
        image_ids = [row[0] for row in conn.execute("SELECT id FROM card_images ORDER BY id")]
        conn.executemany(
            "INSERT INTO embeddings (card_image_id, model, dim, kind, vector) "
            "VALUES (?, 'scale-model', ?, 'global', ?)",
            [
                (image_id, DIM, to_blob(vector))
                for image_id, vector in zip(image_ids, vectors, strict=True)
            ],
        )
        conn.commit()

        index = load_index(conn, "scale-model")
        assert len(index) == COUNT

        ranked = rank(index, vectors[5000], top_k=3)
        assert ranked[0][0] == ("SCALE05000", 0)
    finally:
        conn.close()
