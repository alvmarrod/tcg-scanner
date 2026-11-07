from tcg_scanner.batch import discover_groups, find_images, result_path


def test_find_images_keeps_supported_files_sorted(tmp_path):
    (tmp_path / "b.webp").write_bytes(b"x")
    (tmp_path / "a.JPG").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("skip me")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "c.png").write_bytes(b"x")

    assert [path.name for path in find_images(tmp_path)] == ["a.JPG", "b.webp"]


def test_find_images_returns_empty_for_a_missing_directory(tmp_path):
    assert find_images(tmp_path / "missing") == []


def test_result_path_uses_the_group_name(tmp_path):
    assert result_path(tmp_path, "card.01") == tmp_path / "card.01.json"


def test_discover_groups_treats_folders_as_cards(tmp_path):
    (tmp_path / "loose.jpg").write_bytes(b"x")
    folder = tmp_path / "card-001"
    folder.mkdir()
    (folder / "front.jpg").write_bytes(b"x")
    (folder / "back.jpg").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("skip")

    groups = discover_groups(tmp_path)

    assert [group.name for group in groups] == ["card-001", "loose"]
    assert [image.name for image in groups[0].images] == ["back.jpg", "front.jpg"]


def test_discover_groups_returns_empty_for_a_missing_directory(tmp_path):
    assert discover_groups(tmp_path / "missing") == []
