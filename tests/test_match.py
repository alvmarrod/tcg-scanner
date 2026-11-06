import numpy as np
import pytest

from tcg_scanner.db import init_catalog, open_catalog
from tcg_scanner.recognition.index import ReferenceIndex
from tcg_scanner.recognition.match import identify, rank


def _index() -> ReferenceIndex:
    return ReferenceIndex(
        vectors=np.array([[1.0, 0.0, 0.0], [0.8, 0.6, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
        printing_ids=np.array([10, 10, 20]),
        card_codes=["OP08-001", "OP08-001", "OP08-002"],
    )


def test_rank_aggregates_a_printing_by_its_best_image():
    query = np.array([0.6, 0.8, 0.0], dtype=np.float32)

    ranked = rank(_index(), query)

    assert ranked[0][0] == 10
    assert ranked[0][1] == pytest.approx(0.96)
    assert ranked[1] == (20, pytest.approx(0.8))


def test_rank_returns_one_entry_per_printing():
    ranked = rank(_index(), np.array([1.0, 0.0, 0.0], dtype=np.float32))

    assert [printing_id for printing_id, _ in ranked] == [10, 20]
    assert ranked[0][1] == 1.0


def test_rank_filters_by_card_code():
    ranked = rank(_index(), np.array([1.0, 0.0, 0.0], dtype=np.float32), code="OP08-002")

    assert [printing_id for printing_id, _ in ranked] == [20]


def test_rank_returns_nothing_for_an_unknown_code():
    assert rank(_index(), np.zeros(3, dtype=np.float32), code="ZZ99-999") == []


def test_rank_returns_nothing_for_an_empty_index():
    empty = ReferenceIndex(
        vectors=np.zeros((0, 0), dtype=np.float32),
        printing_ids=np.zeros(0, dtype=np.int64),
        card_codes=[],
    )
    assert rank(empty, np.zeros(3, dtype=np.float32)) == []


def test_identify_returns_card_details(tmp_path):
    db_path = tmp_path / "catalog.db"
    init_catalog(db_path)
    conn = open_catalog(db_path)
    try:
        conn.execute(
            "INSERT INTO sets (code, name, kind) VALUES ('OP08', 'Two Legends', 'booster')"
        )
        conn.execute(
            "INSERT INTO cards (code, name, set_code) VALUES ('OP08-001', 'Chopper', 'OP08')"
        )
        conn.execute(
            "INSERT INTO cards (code, name, set_code) VALUES ('OP08-002', 'Marco', 'OP08')"
        )
        conn.execute(
            "INSERT INTO printings (id, card_code, set_code, variant_label) "
            "VALUES (10, 'OP08-001', 'OP08', 'base')"
        )
        conn.execute(
            "INSERT INTO printings (id, card_code, set_code, variant_label) "
            "VALUES (20, 'OP08-002', 'OP08', 'aa')"
        )
        conn.commit()

        candidates = identify(conn, _index(), np.array([1.0, 0.0, 0.0], dtype=np.float32))

        assert candidates[0].printing_id == 10
        assert candidates[0].card_name == "Chopper"
        assert candidates[0].set_code == "OP08"
        assert candidates[0].variant_label == "base"
    finally:
        conn.close()
