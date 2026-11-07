from pathlib import Path

import pytest

from tcg_scanner.eval.run import LabeledPhoto, evaluate, load_labels
from tcg_scanner.recognition.match import Candidate


def _candidate(code: str, print_index: int, score: float) -> Candidate:
    return Candidate(
        card_code=code,
        print_index=print_index,
        card_name="Card",
        set_code="OP08",
        variant_label="base",
        image_url=None,
        score=score,
        reference_language="jp",
    )


def test_evaluate_counts_metrics_and_misses():
    labels = [
        LabeledPhoto(Path("a.jpg"), "OP08-001", 0),
        LabeledPhoto(Path("b.jpg"), "OP08-002", 1),
        LabeledPhoto(Path("c.jpg"), "OP08-003", None),
        LabeledPhoto(Path("gone.jpg"), "OP08-004", 0),
    ]

    def predict(path):
        if path.name == "gone.jpg":
            raise FileNotFoundError(path)
        if path.name == "a.jpg":
            return "OP08-001", [_candidate("OP08-001", 0, 0.9), _candidate("OP08-002", 0, 0.3)]
        if path.name == "b.jpg":
            return None, [_candidate("OP08-002", 1, 0.5)]
        return "OP08-001", [_candidate("OP08-002", 0, 0.6)]

    report = evaluate(labels, predict)

    assert report.total == 3
    assert report.missing == 1
    assert report.card_top1 == 2
    assert report.print_total == 2
    assert report.print_top1 == 2
    assert report.print_top5 == 2
    assert report.ocr_readable == 2
    assert report.ocr_correct == 1
    assert report.correct_scores == (0.9, 0.5)
    assert report.wrong_scores == (0.6,)
    assert len(report.misses) == 1
    assert report.misses[0].expected == "OP08-003"
    assert report.misses[0].predicted.startswith("OP08-002 #0")


def test_evaluate_handles_an_empty_label_set():
    report = evaluate([], lambda path: (None, []))

    assert report.total == 0
    assert report.missing == 0
    assert report.card_accuracy == 0.0
    assert report.print_accuracy == 0.0


def test_load_labels_resolves_paths_and_optional_print_index(tmp_path):
    labels_path = tmp_path / "labels.csv"
    labels_path.write_text(
        "image,card_code,print_index\npics/a.jpg,op08-001,0\npics/b.jpg,OP08-002,\n"
    )

    labels = load_labels(labels_path)

    assert labels[0].image == tmp_path / "pics" / "a.jpg"
    assert labels[0].card_code == "OP08-001"
    assert labels[0].print_index == 0
    assert labels[1].print_index is None


def test_load_labels_rejects_a_missing_column(tmp_path):
    labels_path = tmp_path / "labels.csv"
    labels_path.write_text("image\npics/a.jpg\n")

    with pytest.raises(ValueError, match="card_code"):
        load_labels(labels_path)


def test_load_labels_rejects_an_empty_row(tmp_path):
    labels_path = tmp_path / "labels.csv"
    labels_path.write_text("image,card_code\n,OP08-001\n")

    with pytest.raises(ValueError, match="line 2"):
        load_labels(labels_path)
