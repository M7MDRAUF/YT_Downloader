"""Tests for config.py — data dir, atomic writes, load/save config."""

import json
import os
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

    def test_writes_valid_json(self, tmp_path: pytest.TempPathFactory) -> None:
        path = str(tmp_path / "test.json")  # type: ignore[operator]
        config.atomic_write_json(path, {"key": "value"})
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"key": "value"}

    def test_overwrites_existing(self, tmp_path: pytest.TempPathFactory) -> None:
        path = str(tmp_path / "test.json")  # type: ignore[operator]
        config.atomic_write_json(path, {"old": True})
        config.atomic_write_json(path, {"new": True})
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"new": True}

    def test_writes_list(self, tmp_path: pytest.TempPathFactory) -> None:
        path = str(tmp_path / "test.json")  # type: ignore[operator]
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

    def test_merges_stored_values(self, tmp_path: pytest.TempPathFactory) -> None:
        path = str(tmp_path / "cfg.json")  # type: ignore[operator]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"format": "720p", "subtitles": True}, f)
        with mock.patch.object(config, "CONFIG_FILE", path):
            cfg = config.load_config()
        assert cfg["format"] == "720p"
        assert cfg["subtitles"] is True
        # Defaults still present for keys not in stored
        assert "output_dir" in cfg

    def test_ignores_wrong_type(self, tmp_path: pytest.TempPathFactory) -> None:
        path = str(tmp_path / "cfg.json")  # type: ignore[operator]
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"format": 123}, f)  # wrong type (int, not str)
        with mock.patch.object(config, "CONFIG_FILE", path):
            cfg = config.load_config()
        assert cfg["format"] == config._DEFAULTS["format"]  # pyright: ignore[reportPrivateUsage]

    def test_survives_corrupt_file(self, tmp_path: pytest.TempPathFactory) -> None:
        path = str(tmp_path / "cfg.json")  # type: ignore[operator]
        with open(path, "w", encoding="utf-8") as f:
            f.write("{invalid json")
        with mock.patch.object(config, "CONFIG_FILE", path):
            cfg = config.load_config()
        assert cfg == config._DEFAULTS  # pyright: ignore[reportPrivateUsage]


class TestSaveConfig:
    """save_config() writes config and returns success bool."""

    def test_returns_true_on_success(self, tmp_path: pytest.TempPathFactory) -> None:
        path = str(tmp_path / "cfg.json")  # type: ignore[operator]
        with mock.patch.object(config, "CONFIG_FILE", path):
            assert config.save_config({"format": "best"}) is True
        with open(path, encoding="utf-8") as f:
            assert json.load(f) == {"format": "best"}

    def test_returns_false_on_failure(self) -> None:
        with mock.patch.object(config, "CONFIG_FILE", "/nonexistent_xyz/cfg.json"):
            assert config.save_config({"format": "best"}) is False
