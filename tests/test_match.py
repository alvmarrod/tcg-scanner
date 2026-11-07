import numpy as np
import pytest

from tcg_scanner.db import init_catalog, open_catalog
from tcg_scanner.recognition.index import ReferenceIndex
from tcg_scanner.recognition.match import identify, rank


def _index() -> ReferenceIndex:
    return ReferenceIndex(
        vectors=np.array([[1.0, 0.0, 0.0], [0.8, 0.6, 0.0], [0.0, 1.0, 0.0]], dtype=np.float32),
        key_ids=np.array([0, 0, 1]),
        keys=[("OP08-001", 0), ("OP08-002", 0)],
        card_codes=["OP08-001", "OP08-001", "OP08-002"],
        languages=["jp", "jp", "en"],
    )


def _empty_index() -> ReferenceIndex:
    return ReferenceIndex(
        vectors=np.zeros((0, 0), dtype=np.float32),
        key_ids=np.zeros(0, dtype=np.int64),
        keys=[],
        card_codes=[],
        languages=[],
    )


def test_rank_aggregates_a_printing_by_its_best_image():
    query = np.array([0.6, 0.8, 0.0], dtype=np.float32)

    ranked = rank(_index(), query)

    assert ranked[0][0] == ("OP08-001", 0)
    assert ranked[0][1] == pytest.approx(0.96)
    assert ranked[0][2] == "jp"
    assert ranked[1][0] == ("OP08-002", 0)
    assert ranked[1][1] == pytest.approx(0.8)
    assert ranked[1][2] == "en"


def test_rank_returns_one_entry_per_printing():
    ranked = rank(_index(), np.array([1.0, 0.0, 0.0], dtype=np.float32))

    assert [key for key, _score, _language in ranked] == [("OP08-001", 0), ("OP08-002", 0)]
    assert ranked[0][1] == 1.0


def test_rank_filters_by_card_code():
    ranked = rank(_index(), np.array([1.0, 0.0, 0.0], dtype=np.float32), code="OP08-002")

    assert [key for key, _score, _language in ranked] == [("OP08-002", 0)]


def test_rank_returns_nothing_for_an_unknown_code():
    assert rank(_index(), np.zeros(3, dtype=np.float32), code="ZZ99-999") == []


def test_rank_returns_nothing_for_an_empty_index():
    assert rank(_empty_index(), np.zeros(3, dtype=np.float32)) == []


def test_rank_prefers_the_preferred_language_even_with_a_lower_score():
    index = ReferenceIndex(
        vectors=np.array(
            [[1.0, 0.0, 0.0], [0.9, 0.43588989, 0.0], [0.5, 0.8660254, 0.0]],
            dtype=np.float32,
        ),
        key_ids=np.array([0, 0, 1]),
        keys=[("OP08-001", 0), ("OP08-002", 0)],
        card_codes=["OP08-001", "OP08-001", "OP08-002"],
        languages=["en", "jp", "en"],
    )

    ranked = rank(index, np.array([1.0, 0.0, 0.0], dtype=np.float32))

    assert ranked[0][0] == ("OP08-001", 0)
    assert ranked[0][2] == "jp"
    assert ranked[0][1] == pytest.approx(0.9)


def test_rank_falls_back_to_the_other_language():
    index = ReferenceIndex(
        vectors=np.array([[1.0, 0.0, 0.0]], dtype=np.float32),
        key_ids=np.array([0]),
        keys=[("OP08-001", 0)],
        card_codes=["OP08-001"],
        languages=["en"],
    )

    ranked = rank(index, np.array([1.0, 0.0, 0.0], dtype=np.float32))

    assert ranked[0][2] == "en"


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
            "INSERT INTO printings (card_code, print_index, set_code, variant_label, image_url) "
            "VALUES ('OP08-001', 0, 'OP08', 'base', 'http://img/001.webp')"
        )
        conn.execute(
            "INSERT INTO printings (card_code, print_index, set_code, variant_label, image_url) "
            "VALUES ('OP08-002', 0, 'OP08', 'aa', 'http://img/002.webp')"
        )
        conn.commit()

        result = identify(conn, _index(), np.array([1.0, 0.0, 0.0], dtype=np.float32))

        assert result.code_used is False
        candidate = result.candidates[0]
        assert (candidate.card_code, candidate.print_index) == ("OP08-001", 0)
        assert candidate.card_name == "Chopper"
        assert candidate.set_code == "OP08"
        assert candidate.variant_label == "base"
        assert candidate.reference_language == "jp"
    finally:
        conn.close()


def test_identify_retries_without_a_misread_code(tmp_path):
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
            "INSERT INTO printings (card_code, print_index, set_code, variant_label, image_url) "
            "VALUES ('OP08-001', 0, 'OP08', 'base', 'http://img/001.webp')"
        )
        conn.execute(
            "INSERT INTO printings (card_code, print_index, set_code, variant_label, image_url) "
            "VALUES ('OP08-002', 0, 'OP08', 'aa', 'http://img/002.webp')"
        )
        conn.commit()

        result = identify(
            conn, _index(), np.array([1.0, 0.0, 0.0], dtype=np.float32), code="DFO92-850"
        )

        assert result.code_used is False
        assert result.candidates[0].card_code == "OP08-001"
    finally:
        conn.close()


def test_identify_reports_the_used_code(tmp_path):
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
            "INSERT INTO printings (card_code, print_index, set_code, variant_label, image_url) "
            "VALUES ('OP08-001', 0, 'OP08', 'base', 'http://img/001.webp')"
        )
        conn.execute(
            "INSERT INTO printings (card_code, print_index, set_code, variant_label, image_url) "
            "VALUES ('OP08-002', 0, 'OP08', 'aa', 'http://img/002.webp')"
        )
        conn.commit()

        result = identify(
            conn, _index(), np.array([1.0, 0.0, 0.0], dtype=np.float32), code="OP08-001"
        )

        assert result.code_used is True
        assert result.candidates[0].card_code == "OP08-001"
    finally:
        conn.close()
