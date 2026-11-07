from __future__ import annotations

import importlib.util
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from tcg_scanner import results
from tcg_scanner.db import open_catalog, open_library
from tcg_scanner.db.library import get_review
from tcg_scanner.prices import latest_prices, no_prices
from tcg_scanner.recognition.report import build_report


def recognition_available() -> bool:
    return all(
        importlib.util.find_spec(module) is not None for module in ("torch", "easyocr", "timm")
    )


class JobBusy(RuntimeError):
    pass


class RetryManager:
    """One in-process retry job at a time, with pollable progress."""

    def __init__(self, data_root: Path) -> None:
        self.root = data_root
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._active: str | None = None

    def start(self, run: str, groups: list[str]) -> str:
        with self._lock:
            if self._active is not None:
                active = self._jobs.get(self._active)
                if active is not None and active["state"] in ("queued", "running"):
                    raise JobBusy("a retry job is already running")
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = {
                "id": job_id,
                "run": run,
                "state": "running",
                "total": len(groups),
                "completed": 0,
                "current": None,
                "errors": [],
                "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "finished_at": None,
            }
            self._active = job_id
        thread = threading.Thread(target=self._work, args=(job_id, run, groups), daemon=True)
        thread.start()
        return job_id

    def status(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    def _update(self, job_id: str, **changes: object) -> None:
        with self._lock:
            self._jobs[job_id].update(changes)

    def _error(self, job_id: str, group: str, message: str) -> None:
        with self._lock:
            self._jobs[job_id]["errors"].append({"group": group, "error": message})

    def _work(self, job_id: str, run: str, groups: list[str]) -> None:
        catalog = None
        try:
            from tcg_scanner.recognition.api import Recognizer, fuse

            catalog = open_catalog(self.root / "db" / "catalog.db")
            run_dir = self.root / "output" / run
            versions = results.versions(run_dir)

            recognizer: Recognizer | None = None
            for group in groups:
                self._update(job_id, current=group)
                try:
                    iteration = max(versions.get(group, {}))
                    report = results.load(versions[group][iteration])
                    language = report.get("preferences", {}).get("language", "jp")
                    if recognizer is None:
                        recognizer = Recognizer(catalog, prefer=language, top_k=5)
                    self._retry_one(
                        run,
                        run_dir,
                        group,
                        iteration,
                        report,
                        recognizer,
                        fuse,
                        catalog,
                    )
                except Exception as error:  # per-item failure, keep going
                    self._error(job_id, group, str(error))
                with self._lock:
                    self._jobs[job_id]["completed"] += 1
        except Exception as error:
            self._update(job_id, state="failed", finished_at=datetime.now(UTC).isoformat())
            self._error(job_id, "*", str(error))
        else:
            self._update(job_id, state="done", finished_at=datetime.now(UTC).isoformat())
        finally:
            self._update(job_id, current=None)
            if catalog is not None:
                catalog.close()
            with self._lock:
                self._active = None

    def _retry_one(
        self,
        run: str,
        run_dir: Path,
        group: str,
        iteration: int,
        report: dict,
        recognizer,
        fuse,
        catalog,
    ) -> None:
        library = open_library(self.root / "db" / "library.db")
        try:
            review = get_review(library, run, group, iteration)
        finally:
            library.close()

        if review is None or review["status"] != "wrong" or not review["expansion"]:
            raise ValueError("retry needs a wrong review with an expansion")

        photos = [
            Path(photo["image"]) for photo in report.get("photos", []) if not photo.get("excluded")
        ] or [Path(photo["image"]) for photo in report.get("photos", [])]
        if not photos:
            raise ValueError("result has no photos")

        recognitions = [
            recognizer.recognize(photo, expansion=review["expansion"]) for photo in photos
        ]
        fused = fuse(recognitions)
        top = fused.candidates[0] if fused.candidates else None
        prices = (
            latest_prices(catalog, top.card_code, top.print_index)
            if top is not None
            else no_prices()
        )
        new_report = build_report(
            group=group,
            fused=fused,
            prices=prices,
            preferred_language=report.get("preferences", {}).get("language", "jp"),
        )
        new_report = results.annotate(
            new_report,
            iteration=iteration + 1,
            kind="retry",
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            hint={
                "status": review["status"],
                "expansion": review["expansion"],
                "note": review["note"],
            },
            previous=results.previous_summary(report),
        )
        results.write(
            results.version_path(run_dir, group, iteration + 1),
            new_report,
        )
