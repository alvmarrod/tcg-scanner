import json

from tcg_scanner import results


def _report(code="OP15-001", score=0.9):
    return {
        "schema_version": 2,
        "group": "card-a",
        "detections": [{"card_code": code, "print_index": 0, "confidence": score}],
    }


def test_versions_are_discovered_and_ordered(tmp_path):
    results.write(results.version_path(tmp_path, "card-a", 0), _report())
    results.write(results.version_path(tmp_path, "card-a", 2), _report())
    results.write(results.version_path(tmp_path, "card-b", 0), _report())

    found = results.versions(tmp_path)

    assert sorted(found["card-a"]) == [0, 2]
    assert results.latest_versions(tmp_path) == {"card-a": 2, "card-b": 0}
    assert results.next_iteration(tmp_path, "card-a") == 3
    assert results.next_iteration(tmp_path, "card-z") == 0


def test_annotate_records_the_retry_hint(tmp_path):
    report = results.annotate(
        _report(),
        iteration=1,
        kind="retry",
        created_at="2026-01-01T00:00:00Z",
        hint={"status": "wrong", "expansion": "OP15", "note": None},
        previous={"card_code": "OP08-001", "print_index": 0, "score": 0.4},
    )

    assert report["version"]["iteration"] == 1
    assert report["version"]["hint"]["expansion"] == "OP15"
    assert results.previous_summary(report)["card_code"] == "OP15-001"


def test_parse_version_ignores_run_json(tmp_path):
    (tmp_path / "run.json").write_text(json.dumps({}))
    (tmp_path / "card.v0.json").write_text(json.dumps({}))

    assert results.parse_version(tmp_path / "run.json") is None
    assert results.parse_version(tmp_path / "card.v0.json") == ("card", 0)
