from __future__ import annotations

import csv
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tcg_scanner.recognition.match import Candidate

Predict = Callable[[Path], tuple[str | None, list[Candidate]]]


@dataclass(frozen=True)
class LabeledPhoto:
    image: Path
    card_code: str
    print_index: int | None


@dataclass(frozen=True)
class Miss:
    image: str
    expected: str
    predicted: str


@dataclass(frozen=True)
class Report:
    total: int
    missing: int
    card_top1: int
    print_total: int
    print_top1: int
    print_top5: int
    ocr_readable: int
    ocr_correct: int
    correct_scores: tuple[float, ...]
    wrong_scores: tuple[float, ...]
    misses: tuple[Miss, ...]

    @property
    def card_accuracy(self) -> float:
        return self.card_top1 / self.total if self.total else 0.0

    @property
    def print_accuracy(self) -> float:
        return self.print_top1 / self.print_total if self.print_total else 0.0

    @property
    def print_recall(self) -> float:
        return self.print_top5 / self.print_total if self.print_total else 0.0

    @property
    def ocr_readable_rate(self) -> float:
        return self.ocr_readable / self.total if self.total else 0.0

    @property
    def ocr_accuracy(self) -> float:
        return self.ocr_correct / self.ocr_readable if self.ocr_readable else 0.0


def load_labels(path: Path) -> list[LabeledPhoto]:
    labels: list[LabeledPhoto] = []
    root = path.parent
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = {"image", "card_code"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"labels file is missing columns: {', '.join(sorted(missing))}")

        for line, row in enumerate(reader, start=2):
            image = (row.get("image") or "").strip()
            card_code = (row.get("card_code") or "").strip().upper()
            if not image or not card_code:
                raise ValueError(f"line {line}: image and card_code are required")

            raw_index = (row.get("print_index") or "").strip()
            print_index = int(raw_index) if raw_index else None
            image_path = Path(image)
            labels.append(
                LabeledPhoto(
                    image=image_path if image_path.is_absolute() else root / image_path,
                    card_code=card_code,
                    print_index=print_index,
                )
            )
    return labels


def evaluate(
    labels: Sequence[LabeledPhoto],
    predict: Predict,
    *,
    top_k: int = 5,
) -> Report:
    total = missing = 0
    card_top1 = print_total = print_top1 = print_top5 = 0
    ocr_readable = ocr_correct = 0
    correct_scores: list[float] = []
    wrong_scores: list[float] = []
    misses: list[Miss] = []

    for label in labels:
        try:
            code, candidates = predict(label.image)
        except FileNotFoundError:
            missing += 1
            continue

        total += 1
        top = candidates[0] if candidates else None
        if code is not None:
            ocr_readable += 1
            if code == label.card_code:
                ocr_correct += 1

        card_ok = top is not None and top.card_code == label.card_code
        if card_ok:
            card_top1 += 1
            correct_scores.append(top.score)
        else:
            if top is not None:
                wrong_scores.append(top.score)
            misses.append(Miss(str(label.image), _expected(label), _predicted(top)))

        if label.print_index is not None:
            print_total += 1
            best = candidates[:top_k]
            if top is not None and (top.card_code, top.print_index) == (
                label.card_code,
                label.print_index,
            ):
                print_top1 += 1
            if any(
                (candidate.card_code, candidate.print_index) == (label.card_code, label.print_index)
                for candidate in best
            ):
                print_top5 += 1

    return Report(
        total=total,
        missing=missing,
        card_top1=card_top1,
        print_total=print_total,
        print_top1=print_top1,
        print_top5=print_top5,
        ocr_readable=ocr_readable,
        ocr_correct=ocr_correct,
        correct_scores=tuple(correct_scores),
        wrong_scores=tuple(wrong_scores),
        misses=tuple(misses),
    )


def score_summary(scores: Sequence[float]) -> str:
    if not scores:
        return "n/a"
    return f"median {statistics.median(scores):.3f}, min {min(scores):.3f}"


def _expected(label: LabeledPhoto) -> str:
    if label.print_index is None:
        return label.card_code
    return f"{label.card_code} #{label.print_index}"


def _predicted(candidate: Candidate | None) -> str:
    if candidate is None:
        return "no match"
    return f"{candidate.card_code} #{candidate.print_index} ({candidate.score:.3f})"
