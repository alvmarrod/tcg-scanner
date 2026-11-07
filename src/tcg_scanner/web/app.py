from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from tcg_scanner import config

THUMBNAIL_SIZE = (520, 520)
UI_DIR = Path(__file__).parent / "ui_build"


def create_app(data_dir: Path | None = None) -> FastAPI:
    root = (data_dir or config.data_dir()).resolve()
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

    def report_path(run: str, group: str) -> Path:
        if Path(group).name != group:
            raise HTTPException(status_code=404, detail="unknown result")
        path = run_directory(run) / f"{group}.json"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="unknown result")
        return path

    def load_report(run: str, group: str) -> dict:
        try:
            report = json.loads(report_path(run, group).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=500, detail=f"unreadable result: {error}") from error
        if report.get("schema_version", 0) < 2:
            raise HTTPException(status_code=404, detail="unsupported result schema")
        return report

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

    def thumbnail(source: Path) -> Path:
        stat = source.stat()
        digest = hashlib.sha1(f"{source}|{stat.st_mtime_ns}|{stat.st_size}".encode()).hexdigest()
        cache = output_root() / ".thumbs"
        cache.mkdir(parents=True, exist_ok=True)
        target = cache / f"{digest}.jpg"
        if not target.is_file():
            from PIL import Image, ImageOps

            with Image.open(source) as image:
                rgb = ImageOps.exif_transpose(image).convert("RGB")
                rgb.thumbnail(THUMBNAIL_SIZE)
                temporary = target.with_suffix(".tmp")
                rgb.save(temporary, "JPEG", quality=85)
                temporary.replace(target)
        return target

    def summary(run: str, group: str, report: dict) -> dict:
        detection = (report.get("detections") or [None])[0]
        base = f"/api/runs/{quote(run, safe='')}/results/{quote(group, safe='')}"
        result = {
            "run": run,
            "group": report.get("group") or group,
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
            "input_url": f"{base}/input",
            "input_thumb": f"{base}/input?thumb=1",
            "reference_url": None,
            "reference_thumb": None,
        }
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
                    "reference_url": f"{base}/reference",
                    "reference_thumb": f"{base}/reference?thumb=1",
                }
            )
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

        results = []
        for path in sorted(directory.glob("*.json")):
            if path.name == "run.json":
                continue
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except OSError, json.JSONDecodeError:
                continue
            if report.get("schema_version", 0) < 2:
                continue
            results.append(summary(name, path.stem, report))

        return {
            "name": name,
            "created_at": metadata.get("created_at"),
            "input": metadata.get("input"),
            "model": metadata.get("model"),
            "photos": metadata.get("photos", sum(result["photos"] for result in results)),
            "groups": len(results),
            "results": results,
        }

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

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
                }
            )
        return {"runs": summaries}

    @app.get("/api/runs/{run}")
    def run_detail(run: str) -> dict:
        return load_run(run)

    @app.get("/api/runs/{run}/results/{group}")
    def result_detail(run: str, group: str) -> dict:
        report = load_report(run, group)
        return {"summary": summary(run, group, report), "report": report}

    @app.get("/api/runs/{run}/results/{group}/input")
    def input_image(run: str, group: str, thumb: bool = Query(default=False)) -> FileResponse:
        report = load_report(run, group)
        image_path = report.get("image", {}).get("path")
        if not image_path:
            raise HTTPException(status_code=404, detail="no input image")
        source = data_file(image_path)
        return _file_response(thumbnail(source) if thumb else source)

    @app.get("/api/runs/{run}/results/{group}/reference")
    def reference_image(run: str, group: str, thumb: bool = Query(default=False)) -> FileResponse:
        report = load_report(run, group)
        source = reference_file(report)
        return _file_response(thumbnail(source) if thumb else source)

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
