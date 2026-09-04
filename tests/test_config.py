"""Tests for config.py — data dir, atomic writes, load/save config."""

import json
import os
import pathlib
from unittest import mock

import pytest

import config


class TestDataDir:
    """_data_dir() returns a platform-appropriate directory."""

    def test_returns_string(self) -> None:
        assert isinstance(config.DATA_DIR, str)

    def test_directory_exists(self) -> None:
        assert os.path.isdir(config.DATA_DIR)


class TestAtomicWriteJson:
    """atomic_write_json() writes JSON atomically via temp + replace."""

    def test_writes_valid_json(self, tmp_path: pathlib.Path) -> None:
        path = str(tmp_path / "test.json")
        config.atomic_write_json(path, {"key": "value"})
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"key": "value"}

    def test_overwrites_existing(self, tmp_path: pathlib.Path) -> None:
        path = str(tmp_path / "test.json")
        config.atomic_write_json(path, {"old": True})
        config.atomic_write_json(path, {"new": True})
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"new": True}

    def test_writes_list(self, tmp_path: pathlib.Path) -> None:
        path = str(tmp_path / "test.json")
        config.atomic_write_json(path, [1, 2, 3])
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == [1, 2, 3]

    def test_raises_on_bad_dir(self) -> None:
        with pytest.raises(OSError):
            config.atomic_write_json("/nonexistent_dir_xyz/file.json", {})


class TestLoadConfig:
    """load_config() returns defaults or merges stored values."""

    def test_returns_defaults_when_no_file(self) -> None:
        with mock.patch.object(config, "CONFIG_FILE", "/tmp/_nonexistent_config.json"):
            cfg = config.load_config()
        assert cfg == config._DEFAULTS  # pyright: ignore[reportPrivateUsage]

    def test_merges_stored_values(self, tmp_path: pathlib.Path) -> None:
        path = str(tmp_path / "cfg.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"format": "720p", "subtitles": True}, f)
        with mock.patch.object(config, "CONFIG_FILE", path):
            cfg = config.load_config()
        assert cfg["format"] == "720p"
        assert cfg["subtitles"] is True
        # Defaults still present for keys not in stored
        assert "output_dir" in cfg

    def test_ignores_wrong_type(self, tmp_path: pathlib.Path) -> None:
        path = str(tmp_path / "cfg.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"format": 123}, f)  # wrong type (int, not str)
        with mock.patch.object(config, "CONFIG_FILE", path):
            cfg = config.load_config()
        assert cfg["format"] == config._DEFAULTS["format"]  # pyright: ignore[reportPrivateUsage]

    def test_survives_corrupt_file(self, tmp_path: pathlib.Path) -> None:
        path = str(tmp_path / "cfg.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{invalid json")
        with mock.patch.object(config, "CONFIG_FILE", path):
            cfg = config.load_config()
        assert cfg == config._DEFAULTS  # pyright: ignore[reportPrivateUsage]


class TestSaveConfig:
    """save_config() writes config and returns success bool."""

    def test_returns_true_on_success(self, tmp_path: pathlib.Path) -> None:
        path = str(tmp_path / "cfg.json")
        with mock.patch.object(config, "CONFIG_FILE", path):
            assert config.save_config({"format": "best"}) is True
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"format": "best"}

    def test_returns_false_on_failure(self) -> None:
        with mock.patch.object(config, "CONFIG_FILE", "/nonexistent_xyz/cfg.json"):
            assert config.save_config({"format": "best"}) is False


class TestDataDirPlatforms:
    """_data_dir() picks a per-platform location and degrades gracefully."""

    def test_windows_uses_appdata(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        monkeypatch.setattr(config.sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path))
        result = config._data_dir()
        assert result == str(tmp_path / "YT_Downloader")
        assert os.path.isdir(result)

    def test_macos_uses_application_support(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        monkeypatch.setattr(config.sys, "platform", "darwin")
        monkeypatch.setattr(config.os.path, "expanduser", lambda _p: str(tmp_path))
        result = config._data_dir()
        assert result == str(tmp_path / "Library" / "Application Support" / "YT_Downloader")

    def test_linux_prefers_xdg_config_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        monkeypatch.setattr(config.sys, "platform", "linux")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert config._data_dir() == str(tmp_path / "YT_Downloader")

    def test_linux_falls_back_to_dot_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        monkeypatch.setattr(config.sys, "platform", "linux")
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.setattr(config.os.path, "expanduser", lambda _p: str(tmp_path))
        assert config._data_dir() == str(tmp_path / ".config" / "YT_Downloader")

    def test_empty_base_falls_back_to_script_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config.sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", "")
        assert config._data_dir() == config._SCRIPT_DIR

    def test_unwritable_dir_falls_back_to_script_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
    ) -> None:
        monkeypatch.setattr(config.sys, "platform", "win32")
        monkeypatch.setenv("APPDATA", str(tmp_path))

        def _boom(*_a: object, **_k: object) -> None:
            raise OSError("read-only filesystem")

        monkeypatch.setattr(config.os, "makedirs", _boom)
        assert config._data_dir() == config._SCRIPT_DIR


class TestAtomicWriteJsonEdgeCases:
    def test_leaves_no_temp_file_behind_on_failure(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "cfg.json"

        class _Unserialisable:
            pass

        with pytest.raises(TypeError):
            config.atomic_write_json(str(target), {"bad": _Unserialisable()})
        assert not target.exists()
        assert list(tmp_path.iterdir()) == []

    def test_replaces_existing_file_atomically(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "cfg.json"
        config.atomic_write_json(str(target), {"a": 1})
        config.atomic_write_json(str(target), {"a": 2})
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 2}
        assert list(tmp_path.iterdir()) == [target]
