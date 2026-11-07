from pathlib import Path

from tcg_scanner.batch import find_images, result_path


def test_find_images_keeps_supported_files_sorted(tmp_path):
    (tmp_path / "b.webp").write_bytes(b"x")
    (tmp_path / "a.JPG").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("skip me")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.png").write_bytes(b"x")

    assert [path.name for path in find_images(tmp_path)] == ["a.JPG", "b.webp"]


def test_find_images_returns_empty_for_a_missing_directory(tmp_path):
    assert find_images(tmp_path / "missing") == []


def test_result_path_uses_the_image_stem(tmp_path):
    assert result_path(tmp_path, Path("pics/card.01.webp")) == tmp_path / "card.01.json"
