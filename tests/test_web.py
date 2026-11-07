import json
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from tcg_scanner.db import init_catalog, open_catalog
from tcg_scanner.web.app import create_app


def _write_image(path: Path, color=(200, 180, 160)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 560), color).save(path)


def _report(input_path: Path, *, code="OP15-001", print_index=0, rotation=0) -> dict:
    return {
        "schema_version": 2,
        "group": "card-a",
        "status": "matched",
        "image": {"path": str(input_path), "width": 400, "height": 560},
        "rectification": {
            "found": True,
            "corners": [[0, 0], [1, 0], [1, 1], [0, 1]],
            "size": [600, 838],
            "rotated": rotation in (90, 270),
            "flipped": False,
            "rotation": rotation,
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


def _client(tmp_path, *, code="OP15-001", print_index=0, rotation=0):
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
    (run / "card-a.v0.json").write_text(
        json.dumps(_report(input_path, code=code, print_index=print_index, rotation=rotation)),
        encoding="utf-8",
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
    assert "/input?iteration=0" in summary["input_url"]
    assert summary["expansion"] == "OP15"
    assert summary["price_eur"] == 0.1
    assert summary["price_usd"] == 0.2
    assert summary["price"] == 0.1

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


def test_input_url_carries_the_display_rotation(tmp_path):
    client = _client(tmp_path, rotation=90)

    summary = client.get("/api/runs/run-a").json()["results"][0]

    assert summary["input_rotation"] == 90
    assert "rotate=90" in summary["input_thumb"]


def test_rotates_the_input_image_on_request(tmp_path):
    import io

    from PIL import Image

    client = _client(tmp_path)
    response = client.get("/api/runs/run-a/results/card-a/input?rotate=90")

    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as image:
        assert image.size == (560, 400)

    assert client.get("/api/runs/run-a/results/card-a/input?rotate=45").status_code == 400


def test_review_round_trip_and_stats(tmp_path):
    client = _client(tmp_path)

    created = client.put("/api/runs/run-a/results/card-a/review", json={"status": "right"}).json()
    assert created["status"] == "right"
    assert created["stale"] is False

    summary = client.get("/api/runs/run-a").json()["results"][0]
    assert summary["review"]["status"] == "right"

    stats = client.get("/api/runs/run-a/stats").json()
    assert stats["reviewed"] == 1
    assert stats["right"] == 1
    assert stats["unmarked"] == 0
    assert stats["accuracy"] == 1.0

    updated = client.put(
        "/api/runs/run-a/results/card-a/review",
        json={"status": "wrong", "expansion": "op15", "note": "wrong art"},
    ).json()
    assert updated["status"] == "wrong"
    assert updated["expansion"] == "OP15"

    stats = client.get("/api/runs/run-a/stats").json()
    assert stats["wrong"] == 1
    assert stats["accuracy"] == 0.0
    assert stats["claimed_expansion"] == {"OP15": 1}
    assert stats["by_expansion"] == {"OP15": {"right": 0, "wrong": 1}}

    assert client.delete("/api/runs/run-a/results/card-a/review").json()["removed"] is True
    assert client.get("/api/runs/run-a").json()["results"][0]["review"] is None


def test_review_is_marked_stale_after_the_result_changes(tmp_path):
    client = _client(tmp_path)
    client.put("/api/runs/run-a/results/card-a/review", json={"status": "right"})

    path = tmp_path / "data" / "output" / "run-a" / "card-a.v0.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["detections"][0]["card_code"] = "OP15-099"
    path.write_text(json.dumps(report), encoding="utf-8")

    review = client.get("/api/runs/run-a").json()["results"][0]["review"]

    assert review["stale"] is True


def test_review_rejects_an_invalid_status(tmp_path):
    client = _client(tmp_path)

    response = client.put("/api/runs/run-a/results/card-a/review", json={"status": "maybe"})

    assert response.status_code == 422


def test_lists_catalog_expansions(tmp_path):
    client = _client(tmp_path)

    assert client.get("/api/expansions").json()["expansions"] == ["OP15"]


def test_result_history_and_latest_selection(tmp_path):
    client = _client(tmp_path)
    path = tmp_path / "data" / "output" / "run-a" / "card-a.v0.json"
    first = json.loads(path.read_text(encoding="utf-8"))
    second = json.loads(json.dumps(first))
    second["detections"][0]["card_code"] = "OP15-099"
    second["detections"][0]["confidence"] = 0.8
    second["version"] = {
        "iteration": 1,
        "kind": "retry",
        "created_at": "2026-01-02",
        "hint": {"status": "wrong", "expansion": "OP15", "note": None},
        "previous": {"card_code": "OP15-001", "print_index": 0, "score": 0.9},
    }
    (path.parent / "card-a.v1.json").write_text(json.dumps(second), encoding="utf-8")

    run = client.get("/api/runs/run-a").json()
    assert run["results"][0]["iteration"] == 1
    assert run["results"][0]["is_latest"] is True
    assert run["results"][0]["card_code"] == "OP15-099"

    detail = client.get("/api/runs/run-a/results/card-a?iteration=0").json()
    assert detail["iteration"] == 0
    assert detail["latest_iteration"] == 1
    assert len(detail["history"]) == 2
    assert detail["history"][1]["version"]["hint"]["expansion"] == "OP15"

    assert (
        client.put(
            "/api/runs/run-a/results/card-a/review?iteration=0",
            json={"status": "wrong"},
        ).status_code
        == 409
    )


def test_stats_use_the_latest_review_per_result(tmp_path):
    client = _client(tmp_path)
    client.put("/api/runs/run-a/results/card-a/review", json={"status": "wrong"})
    path = tmp_path / "data" / "output" / "run-a" / "card-a.v0.json"
    second = json.loads(path.read_text(encoding="utf-8"))
    second["version"] = {"iteration": 1, "kind": "retry", "hint": None}
    (path.parent / "card-a.v1.json").write_text(json.dumps(second), encoding="utf-8")
    client.put("/api/runs/run-a/results/card-a/review", json={"status": "right"})

    stats = client.get("/api/runs/run-a/stats").json()

    assert stats["reviewed"] == 1
    assert stats["right"] == 1
    assert stats["wrong"] == 0


def test_retry_is_rejected_without_the_recognition_stack(tmp_path, monkeypatch):
    import tcg_scanner.web.app as web_app

    client = _client(tmp_path)
    monkeypatch.setattr(web_app, "recognition_available", lambda: False)

    response = client.post(
        "/api/runs/run-a/retry",
        json={"groups": ["card-a"]},
    )

    assert response.status_code == 503
