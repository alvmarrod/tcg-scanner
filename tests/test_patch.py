import numpy as np

from tcg_scanner.db import init_catalog, open_catalog
from tcg_scanner.recognition.index import to_blob
from tcg_scanner.recognition.match import Candidate, verify

GRID = 64
DIM = 8


def _catalog(tmp_path):
    path = tmp_path / "catalog.db"
    init_catalog(path)
    conn = open_catalog(path)
    conn.execute("INSERT INTO sets (code, name, kind) VALUES ('OP08', 'Two Legends', 'booster')")
    image_ids = {}
    for code in ("OP08-001", "OP08-002", "OP08-003"):
        conn.execute("INSERT INTO cards (code, name, set_code) VALUES (?, ?, 'OP08')", (code, code))
        conn.execute(
            "INSERT INTO printings (card_code, print_index, set_code, variant_label) "
            "VALUES (?, 0, 'OP08', 'base')",
            (code,),
        )
        conn.execute(
            "INSERT INTO card_images (card_code, print_index, path, sha256) VALUES (?, 0, ?, ?)",
            (code, f"{code}.webp", code),
        )
        image_ids[code] = conn.execute(
            "SELECT id FROM card_images WHERE card_code = ? AND print_index = 0", (code,)
        ).fetchone()[0]
    conn.commit()
    return conn, image_ids


def _patches(seed):
    rng = np.random.default_rng(seed)
    patches = rng.normal(size=(GRID, DIM)).astype(np.float32)
    return patches / np.linalg.norm(patches, axis=1, keepdims=True)


def _store(conn, image_id, patches):
    conn.execute(
        "INSERT INTO embeddings (card_image_id, model, dim, kind, vector) "
        "VALUES (?, 'm', ?, 'patch', ?)",
        (image_id, DIM, to_blob(patches)),
    )


def _candidate(code, score):
    return Candidate(
        card_code=code,
        print_index=0,
        card_name=code,
        set_code="OP08",
        variant_label="base",
        image_url=None,
        score=score,
    )


def test_verify_reorders_close_candidates_by_patch_similarity(tmp_path):
    conn, image_ids = _catalog(tmp_path)
    try:
        query = _patches(1)
        _store(conn, image_ids["OP08-001"], query)
        _store(conn, image_ids["OP08-002"], _patches(2))
        candidates = [_candidate("OP08-001", 0.80), _candidate("OP08-002", 0.78)]

        verified = verify(conn, candidates, query, "m")

        assert [candidate.card_code for candidate in verified] == ["OP08-001", "OP08-002"]
        assert verified[0].patch_score > 0.99
        assert verified[1].patch_score < 0.5
    finally:
        conn.close()


def test_verify_can_promote_the_second_candidate(tmp_path):
    conn, image_ids = _catalog(tmp_path)
    try:
        query = _patches(1)
        _store(conn, image_ids["OP08-001"], _patches(2))
        _store(conn, image_ids["OP08-002"], query)
        candidates = [_candidate("OP08-001", 0.80), _candidate("OP08-002", 0.79)]

        verified = verify(conn, candidates, query, "m")

        assert [candidate.card_code for candidate in verified] == ["OP08-002", "OP08-001"]
    finally:
        conn.close()


def test_verify_leaves_candidates_outside_the_margin_alone(tmp_path):
    conn, image_ids = _catalog(tmp_path)
    try:
        query = _patches(1)
        _store(conn, image_ids["OP08-001"], query)
        _store(conn, image_ids["OP08-002"], _patches(2))
        _store(conn, image_ids["OP08-003"], query)
        candidates = [
            _candidate("OP08-001", 0.80),
            _candidate("OP08-002", 0.78),
            _candidate("OP08-003", 0.50),
        ]

        verified = verify(conn, candidates, query, "m")

        assert verified[-1] == _candidate("OP08-003", 0.50)
        assert verified[-1].patch_score is None
    finally:
        conn.close()


def test_verify_skips_when_the_margin_group_has_no_patch_embedding(tmp_path):
    conn, image_ids = _catalog(tmp_path)
    try:
        query = _patches(1)
        _store(conn, image_ids["OP08-001"], query)
        candidates = [_candidate("OP08-001", 0.80), _candidate("OP08-002", 0.78)]

        verified = verify(conn, candidates, query, "m")

        assert verified == candidates
    finally:
        conn.close()
