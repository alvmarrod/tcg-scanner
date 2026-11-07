import tcg_scanner.config as config


def test_data_dir_uses_the_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("TCG_SCANNER_DATA", str(tmp_path / "library"))

    assert config.data_dir() == tmp_path / "library"


def test_data_dir_defaults_to_the_checkout(monkeypatch):
    monkeypatch.delenv("TCG_SCANNER_DATA", raising=False)

    assert config.data_dir() == config.PROJECT_ROOT / "data"


def test_installed_tool_uses_the_working_directory(monkeypatch, tmp_path):
    monkeypatch.delenv("TCG_SCANNER_DATA", raising=False)
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path / "install")
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    assert config.data_dir() == work / "data"
