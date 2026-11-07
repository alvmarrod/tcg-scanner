from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from tcg_scanner import config, results
from tcg_scanner.db import init_library, open_library
from tcg_scanner.db.library import clear_review, list_reviews, set_review
from tcg_scanner.web.jobs import JobBusy, RetryManager, recognition_available

THUMBNAIL_SIZE = (520, 520)
UI_DIR = Path(__file__).parent / "ui_build"


class ReviewInput(BaseModel):
    status: Literal["right", "wrong", "unmarked"]
    expansion: str | None = None
    note: str | None = None


class RetryInput(BaseModel):
    groups: list[str]


def create_app(data_dir: Path | None = None) -> FastAPI:
    root = (data_dir or config.data_dir()).resolve()
    library_path = root / "db" / "library.db"
    init_library(library_path)
    retry_manager = RetryManager(root)
    app = FastAPI(
        title="tcg-scanner results", docs_url="/api/docs", openapi_url="/api/openapi.json"
    )

    def output_root() -> Path:
        return root / "output"

    def run_directory(name: str) -> Path:
        if Path(name).name != name or name.startswith("."):
            raise HTTPException(status_code=404, detail="unknown run")
        directory = output_root() / name
        if not directory.is_dir():
            raise HTTPException(status_code=404, detail="unknown run")
        return directory

    def chosen_report(run: str, group: str, iteration: int | None = None) -> tuple[int, int, dict]:
        if Path(group).name != group:
            raise HTTPException(status_code=404, detail="unknown result")
        versions = results.versions(run_directory(run)).get(group)
        if not versions:
            raise HTTPException(status_code=404, detail="unknown result")
        latest = max(versions)
        chosen = latest if iteration is None else iteration
        if chosen not in versions:
            raise HTTPException(status_code=404, detail="unknown iteration")
        try:
            report = results.load(versions[chosen])
        except (OSError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=500, detail=f"unreadable result: {error}") from error
        if report.get("schema_version", 0) < 2:
            raise HTTPException(status_code=404, detail="unsupported result schema")
        return chosen, latest, report

    def reviews_for(run: str) -> dict[tuple[str, int], sqlite3.Row]:
        connection = open_library(library_path)
        try:
            return {
                (row["result_group"], row["iteration"]): row
                for row in list_reviews(connection, run=run)
            }
        finally:
            connection.close()

    def data_file(raw: str) -> Path:
        candidate = Path(raw)
        options = (
            [candidate] if candidate.is_absolute() else [root.parent / candidate, root / candidate]
        )
        for option in options:
            if not option.is_file():
                continue
            try:
                option.resolve().relative_to(root)
            except ValueError:
                continue
            return option.resolve()
        raise HTTPException(status_code=404, detail="image not found")

    def reference_file(report: dict) -> Path:
        detection = (report.get("detections") or [None])[0]
        if detection is None:
            raise HTTPException(status_code=404, detail="no matched printing")
        code = detection["card_code"]
        index = detection["print_index"]
        language = detection.get("reference", {}).get("language")
        database = root / "db" / "catalog.db"
        if not database.is_file():
            raise HTTPException(status_code=404, detail="catalog not found")
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                """
                SELECT path FROM card_images
                WHERE card_code = ? AND print_index = ? AND language = ?
                ORDER BY origin = 'reference' DESC, id LIMIT 1
                """,
                (code, index, language),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    """
                    SELECT path FROM card_images
                    WHERE card_code = ? AND print_index = ?
                    ORDER BY origin = 'reference' DESC, id LIMIT 1
                    """,
                    (code, index),
                ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise HTTPException(status_code=404, detail="no reference image")
        return data_file(row["path"])

    def rendered(source: Path, *, rotate: int = 0, thumb: bool = False) -> Path:
        if rotate == 0 and not thumb:
            return source
        if rotate not in (0, 90, 180, 270):
            raise HTTPException(status_code=400, detail="rotate must be 0, 90, 180 or 270")

        stat = source.stat()
        digest = hashlib.sha1(
            f"{source}|{stat.st_mtime_ns}|{stat.st_size}|{rotate}|{thumb}".encode()
        ).hexdigest()
        cache = output_root() / ".thumbs"
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / f"{digest}.jpg"
        if not target.is_file():
            from PIL import Image, ImageOps

            with Image.open(source) as image:
                rgb = ImageOps.exif_transpose(image).convert("RGB")
                if rotate:
                    rgb = rgb.rotate(-rotate, expand=True)
                if thumb:
                    rgb.thumbnail(THUMBNAIL_SIZE)
                temporary = target.with_suffix(".tmp")
                rgb.save(temporary, "JPEG", quality=90 if not thumb else 85)
                temporary.replace(target)
        return target

    def review_payload(result: dict, row: sqlite3.Row | None) -> dict | None:
        if row is None:
            return None
        stale = (
            result.get("card_code") != row["predicted_card_code"]
            or result.get("print_index") != row["predicted_print_index"]
        )
        return {
            "iteration": row["iteration"],
            "status": row["status"],
            "expansion": row["expansion"],
            "note": row["note"],
            "updated_at": row["updated_at"],
            "stale": stale,
        }

    def summary(
        run: str,
        group: str,
        report: dict,
        iteration: int,
        latest: int,
        review: sqlite3.Row | None,
    ) -> dict:
        detection = (report.get("detections") or [None])[0]
        rotation = report.get("rectification", {}).get("rotation", 0) or 0
        base = f"/api/runs/{quote(run, safe='')}/results/{quote(group, safe='')}"
        query = f"iteration={iteration}"
        input_url = f"{base}/input?{query}"
        input_thumb = f"{base}/input?{query}&thumb=1"
        if rotation:
            input_url += f"&rotate={rotation}"
            input_thumb += f"&rotate={rotation}"

        result = {
            "run": run,
            "group": report.get("group") or group,
            "iteration": iteration,
            "latest_iteration": latest,
            "is_latest": iteration == latest,
            "version": report.get("version")
            or {"iteration": iteration, "kind": "batch", "hint": None},
            "status": report.get("status"),
            "score": None,
            "patch_score": None,
            "margin": None,
            "card_code": None,
            "print_index": None,
            "card_name": None,
            "set_code": None,
            "variant_label": None,
            "reference_language": None,
            "ocr_code": None,
            "warnings": [warning["code"] for warning in report.get("warnings", [])],
            "photos": len(report.get("photos", [])),
            "input_url": input_url,
            "input_thumb": input_thumb,
            "input_rotation": rotation,
            "reference_url": f"{base}/reference?{query}",
            "reference_thumb": f"{base}/reference?{query}&thumb=1",
            "review": None,
            "price": None,
            "price_eur": None,
            "price_usd": None,
            "expansion": None,
        }
        prices = report.get("prices") or {}
        result.update(
            {
                "price_eur": prices.get("eur"),
                "price_usd": prices.get("usd"),
                "price": prices.get("eur") if prices.get("eur") is not None else prices.get("usd"),
            }
        )
        if detection is not None:
            result.update(
                {
                    "score": detection.get("confidence"),
                    "patch_score": detection.get("patch_confidence"),
                    "margin": detection.get("margin"),
                    "card_code": detection.get("card_code"),
                    "print_index": detection.get("print_index"),
                    "card_name": detection.get("card", {}).get("name"),
                    "set_code": detection.get("card", {}).get("set_code"),
                    "variant_label": detection.get("card", {}).get("variant_label"),
                    "reference_language": detection.get("reference", {}).get("language"),
                    "ocr_code": detection.get("ocr", {}).get("code"),
                    "expansion": detection["card_code"].split("-")[0],
                }
            )
        result["review"] = review_payload(result, review)
        return result

    def load_run(name: str) -> dict:
        directory = run_directory(name)
        metadata: dict = {}
        meta_path = directory / "run.json"
        if meta_path.is_file():
            try:
                metadata = json.loads(meta_path.read_text(encoding="utf-8"))
            except OSError, json.JSONDecodeError:
                metadata = {}

        batches = metadata.get("batches") or []
        latest_batch = batches[-1] if batches else metadata
        reviews = reviews_for(name)
        version_map = results.versions(directory)
        summaries = []
        for group, iterations in sorted(version_map.items()):
            latest = max(iterations)
            report = results.load(iterations[latest])
            summaries.append(
                summary(name, group, report, latest, latest, reviews.get((group, latest)))
            )

        return {
            "name": name,
            "created_at": latest_batch.get("created_at"),
            "input": latest_batch.get("input"),
            "model": latest_batch.get("model"),
            "batches": batches,
            "photos": sum(item["photos"] for item in summaries),
            "groups": len(summaries),
            "results": summaries,
        }

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/capabilities")
    def capabilities() -> dict:
        return {"retry": recognition_available()}

    @app.get("/api/runs")
    def runs() -> dict:
        if not output_root().is_dir():
            return {"runs": []}
        entries = [
            entry
            for entry in output_root().iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        ]
        entries.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
        summaries = []
        for entry in entries:
            run = load_run(entry.name)
            summaries.append(
                {
                    "name": run["name"],
                    "created_at": run["created_at"],
                    "input": run["input"],
                    "photos": run["photos"],
                    "groups": run["groups"],
                    "batches": len(run["batches"]),
                }
            )
        return {"runs": summaries}

    @app.get("/api/runs/{run}")
    def run_detail(run: str) -> dict:
        return load_run(run)

    @app.get("/api/runs/{run}/results/{group}")
    def result_detail(run: str, group: str, iteration: int | None = Query(default=None)) -> dict:
        chosen, latest, report = chosen_report(run, group, iteration)
        reviews = reviews_for(run)
        versions = results.versions(run_directory(run))[group]
        history = [
            summary(
                run,
                group,
                results.load(versions[number]),
                number,
                latest,
                reviews.get((group, number)),
            )
            for number in sorted(versions)
        ]
        return {
            "iteration": chosen,
            "latest_iteration": latest,
            "history": history,
            "summary": history[[item["iteration"] for item in history].index(chosen)],
            "report": report,
        }

    @app.put("/api/runs/{run}/results/{group}/review")
    def put_review(
        run: str,
        group: str,
        payload: ReviewInput,
        iteration: int | None = Query(default=None),
    ) -> dict | None:
        chosen, latest, report = chosen_report(run, group, iteration)
        if chosen != latest:
            raise HTTPException(status_code=409, detail="older iterations are read-only")
        detection = (report.get("detections") or [None])[0]
        connection = open_library(library_path)
        try:
            row = set_review(
                connection,
                run=run,
                result_group=group,
                iteration=chosen,
                status=payload.status,
                expansion=payload.expansion,
                predicted_card_code=(detection["card_code"] if detection is not None else None),
                predicted_print_index=(detection["print_index"] if detection is not None else None),
                score=detection.get("confidence") if detection is not None else None,
                note=payload.note,
            )
        finally:
            connection.close()
        if row is None:
            return None
        result = summary(run, group, report, chosen, latest, row)
        return result["review"]

    @app.delete("/api/runs/{run}/results/{group}/review")
    def delete_review(run: str, group: str, iteration: int | None = Query(default=None)) -> dict:
        chosen, latest, _report = chosen_report(run, group, iteration)
        if chosen != latest:
            raise HTTPException(status_code=409, detail="older iterations are read-only")
        connection = open_library(library_path)
        try:
            removed = clear_review(connection, run, group, chosen)
        finally:
            connection.close()
        return {"removed": removed}

    @app.get("/api/runs/{run}/stats")
    def run_stats(run: str) -> dict:
        result_list = load_run(run)["results"]
        reviewed = [item for item in result_list if item["review"]]
        right = sum(1 for item in reviewed if item["review"]["status"] == "right")
        wrong = sum(1 for item in reviewed if item["review"]["status"] == "wrong")
        by_expansion: dict[str, dict[str, int]] = {}
        claimed: dict[str, int] = {}
        for item in reviewed:
            status = item["review"]["status"]
            if status == "unmarked":
                continue
            expansion = (item["card_code"] or "unknown").split("-")[0]
            bucket = by_expansion.setdefault(expansion, {"right": 0, "wrong": 0})
            bucket[status] += 1
            if status == "wrong" and item["review"]["expansion"]:
                claimed[item["review"]["expansion"]] = (
                    claimed.get(item["review"]["expansion"], 0) + 1
                )
        return {
            "total": len(result_list),
            "reviewed": right + wrong,
            "unmarked": len(result_list) - (right + wrong),
            "right": right,
            "wrong": wrong,
            "accuracy": right / (right + wrong) if (right + wrong) else None,
            "by_expansion": dict(sorted(by_expansion.items())),
            "claimed_expansion": dict(sorted(claimed.items())),
        }

    @app.get("/api/expansions")
    def expansions() -> dict:
        database = root / "db" / "catalog.db"
        if not database.is_file():
            return {"expansions": []}
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT DISTINCT substr(code, 1, instr(code, '-') - 1) AS expansion "
                "FROM cards WHERE instr(code, '-') > 0 ORDER BY expansion"
            ).fetchall()
        finally:
            connection.close()
        return {"expansions": [row[0] for row in rows if row[0]]}

    @app.post("/api/runs/{run}/retry")
    def start_retry(run: str, payload: RetryInput) -> dict:
        if not recognition_available():
            raise HTTPException(
                status_code=503,
                detail="retry needs the recognition extra: uv sync --extra recognition",
            )
        run_directory(run)
        eligible = []
        problems = []
        for group in payload.groups:
            try:
                iteration, _latest, _report = chosen_report(run, group)
            except HTTPException:
                problems.append({"group": group, "error": "unknown result"})
                continue
            reviews = reviews_for(run)
            review = reviews.get((group, iteration))
            if review is None or review["status"] != "wrong" or not review["expansion"]:
                problems.append({"group": group, "error": "needs a wrong review with an expansion"})
                continue
            eligible.append(group)
        if not eligible:
            raise HTTPException(
                status_code=400,
                detail={"message": "no eligible results", "problems": problems},
            )
        try:
            job_id = retry_manager.start(run, eligible)
        except JobBusy as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"job_id": job_id, "groups": eligible, "problems": problems}

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        job = retry_manager.status(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return job

    @app.get("/api/runs/{run}/results/{group}/input")
    def input_image(
        run: str,
        group: str,
        thumb: bool = Query(default=False),
        rotate: int = Query(default=0),
        iteration: int | None = Query(default=None),
    ) -> FileResponse:
        _chosen, _latest, report = chosen_report(run, group, iteration)
        image_path = report.get("image", {}).get("path")
        if not image_path:
            raise HTTPException(status_code=404, detail="no input image")
        source = data_file(image_path)
        return _file_response(rendered(source, rotate=rotate, thumb=thumb))

    @app.get("/api/runs/{run}/results/{group}/reference")
    def reference_image(
        run: str,
        group: str,
        thumb: bool = Query(default=False),
        iteration: int | None = Query(default=None),
    ) -> FileResponse:
        _chosen, _latest, report = chosen_report(run, group, iteration)
        source = reference_file(report)
        return _file_response(rendered(source, thumb=thumb))

    if UI_DIR.is_dir():
        app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="ui")
    else:

        @app.get("/")
        def missing_ui() -> HTMLResponse:
            return HTMLResponse(
                "<h1>UI not built</h1>"
                "<p>Run <code>npm install &amp;&amp; npm run build</code> in "
                "<code>src/tcg_scanner/web/ui</code>.</p>",
                status_code=503,
            )

    return app


def _file_response(path: Path) -> FileResponse:
    return FileResponse(path)
