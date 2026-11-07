import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from tcg_scanner.db import init_catalog, open_catalog
from tcg_scanner.web.app import create_app


def _write_image(path: Path, color=(200, 180, 160)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 560), color).save(path)


def _report(input_path: Path, *, code="OP15-001", print_index=0) -> dict:
    return {
        "schema_version": 2,
        "group": "card-a",
        "status": "matched",
        "image": {"path": str(input_path), "width": 400, "height": 560},
        "rectification": {
            "found": True,
            "corners": [[0, 0], [1, 0], [1, 1], [0, 1]],
            "size": [600, 838],
            "rotated": False,
            "flipped": False,
        },
        "preferences": {"language": "jp", "currency": "EUR"},
        "detections": [
            {
                "card_code": code,
                "print_index": print_index,
                "confidence": 0.9,
                "patch_confidence": 0.8,
                "card": {
                    "name": "Krieg",
                    "set_code": "OP15",
                    "variant_label": "base",
                    "metadata_language": "en",
                },
                "reference": {"language": "jp", "preferred": "jp", "fallback": False},
                "ocr": {"code": code, "confidence": 0.8, "bbox": None},
                "prices": {"eur": 0.1, "usd": 0.2, "currency": "EUR"},
            }
        ],
        "photos": [
            {
                "image": str(input_path),
                "ocr": {"code": code, "confidence": 0.8},
                "top": None,
                "excluded": False,
                "rotated": False,
                "flipped": False,
                "warnings": [],
            }
        ],
        "candidates": [
            {
                "card_code": code,
                "print_index": print_index,
                "score": 0.9,
                "patch_score": 0.8,
                "reference_language": "jp",
            }
        ],
        "prices": {"eur": 0.1, "usd": 0.2, "currency": "EUR"},
        "warnings": [],
    }


def _client(tmp_path, *, code="OP15-001", print_index=0):
    root = tmp_path / "data"
    init_catalog(root / "db" / "catalog.db")
    conn = open_catalog(root / "db" / "catalog.db")
    conn.execute("INSERT INTO sets (code, name, kind) VALUES ('OP15', 'Kamis', 'booster')")
    conn.execute("INSERT INTO cards (code, name, set_code) VALUES ('OP15-001', 'Krieg', 'OP15')")
    conn.execute(
        "INSERT INTO printings (card_code, print_index, set_code, image_url) "
        "VALUES ('OP15-001', 0, 'OP15', 'https://cdn/ref.webp')"
    )
    conn.execute(
        "INSERT INTO card_images (card_code, print_index, language, path, sha256, origin) "
        "VALUES ('OP15-001', 0, 'jp', 'images/ref.webp', 'sha', 'reference')"
    )
    conn.commit()
    conn.close()

    _write_image(root / "images" / "ref.webp")
    input_path = root / "input" / "card-a.jpg"
    _write_image(input_path)

    run = root / "output" / "run-a"
    run.mkdir(parents=True)
    (run / "card-a.json").write_text(
        json.dumps(_report(input_path, code=code, print_index=print_index)), encoding="utf-8"
    )
    (run / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "run-a",
                "created_at": "2026-01-01",
                "photos": 1,
                "groups": 1,
            }
        ),
        encoding="utf-8",
    )
    return TestClient(create_app(root))


def test_lists_runs_and_results(tmp_path):
    client = _client(tmp_path)

    runs = client.get("/api/runs").json()["runs"]
    assert [run["name"] for run in runs] == ["run-a"]
    assert runs[0]["photos"] == 1

    detail = client.get("/api/runs/run-a").json()
    assert detail["groups"] == 1
    summary = detail["results"][0]
    assert summary["card_code"] == "OP15-001"
    assert summary["score"] == 0.9
    assert summary["input_url"].endswith("/input")

    result = client.get("/api/runs/run-a/results/card-a").json()
    assert result["report"]["schema_version"] == 2
    assert result["summary"]["group"] == "card-a"


def test_serves_input_and_thumbnail_images(tmp_path):
    client = _client(tmp_path)

    image = client.get("/api/runs/run-a/results/card-a/input")
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/")

    thumbnail = client.get("/api/runs/run-a/results/card-a/input?thumb=1")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"] == "image/jpeg"


def test_serves_the_catalog_reference_image(tmp_path):
    client = _client(tmp_path)

    image = client.get("/api/runs/run-a/results/card-a/reference")
    assert image.status_code == 200

    thumbnail = client.get("/api/runs/run-a/results/card-a/reference?thumb=1")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"] == "image/jpeg"


def test_missing_reference_returns_404(tmp_path):
    client = _client(tmp_path, code="OP99-999", print_index=0)

    assert client.get("/api/runs/run-a/results/card-a/reference").status_code == 404


def test_rejects_unknown_runs_and_results(tmp_path):
    client = _client(tmp_path)

    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/run-a/results/nope").status_code == 404
    assert client.get("/api/runs/run-a/results/..%2F..%2Frun").status_code == 404
