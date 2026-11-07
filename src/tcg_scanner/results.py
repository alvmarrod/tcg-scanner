from __future__ import annotations

import json
import re
from pathlib import Path

_VERSION = re.compile(r"^(?P<group>.+)\.v(?P<iteration>\d+)\.json$")


def version_path(run_dir: Path, group: str, iteration: int) -> Path:
    return run_dir / f"{group}.v{iteration}.json"


def parse_version(path: Path) -> tuple[str, int] | None:
    match = _VERSION.match(path.name)
    if match is None:
        return None
    return match.group("group"), int(match.group("iteration"))


def versions(run_dir: Path) -> dict[str, dict[int, Path]]:
    found: dict[str, dict[int, Path]] = {}
    if not run_dir.is_dir():
        return found
    for path in sorted(run_dir.glob("*.json")):
        parsed = parse_version(path)
        if parsed is None:
            continue
        group, iteration = parsed
        found.setdefault(group, {})[iteration] = path
    return found


def latest_versions(run_dir: Path) -> dict[str, int]:
    return {group: max(iterations) for group, iterations in versions(run_dir).items()}


def next_iteration(run_dir: Path, group: str) -> int:
    iterations = versions(run_dir).get(group, {})
    return max(iterations) + 1 if iterations else 0


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, report: dict) -> None:
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def previous_summary(report: dict) -> dict | None:
    detection = (report.get("detections") or [None])[0]
    if detection is None:
        return None
    return {
        "card_code": detection.get("card_code"),
        "print_index": detection.get("print_index"),
        "score": detection.get("confidence"),
    }


def annotate(
    report: dict,
    *,
    iteration: int,
    kind: str,
    created_at: str,
    hint: dict | None,
    previous: dict | None,
) -> dict:
    report["version"] = {
        "iteration": iteration,
        "kind": kind,
        "created_at": created_at,
        "hint": hint,
        "previous": previous,
    }
    return report
