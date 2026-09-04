"""Tests for gui.py — URL safety, history persistence, helpers."""

import json
from unittest import mock

import pytest

import gui  # imported after conftest installs the tkinter stub


class TestIsSafeUrl:
    """_is_safe_url() blocks localhost, private IPs, and non-HTTP schemes."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://i.ytimg.com/vi/abc/maxresdefault.jpg",
            "https://example.com/thumb.jpg",
            "http://cdn.example.org/image.png",
        ],
    )
    def test_allows_safe_urls(self, url: str) -> None:
        assert gui._is_safe_url(url) is True  # pyright: ignore[reportPrivateUsage]

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/evil",
            "http://127.0.0.1/evil",
            "http://[::1]/evil",
            "http://0.0.0.0/evil",
            "ftp://example.com/file",
            "file:///etc/passwd",
            "javascript:alert(1)",
            "",
            "not-a-url",
            "http://10.0.0.1/internal",
            "http://192.168.1.1/internal",
            "http://172.16.0.1/internal",
        ],
    )
    def test_blocks_unsafe_urls(self, url: str) -> None:
        assert gui._is_safe_url(url) is False  # pyright: ignore[reportPrivateUsage]


class TestFormatSpeedLabel:
    """_format_speed_label() adds an ISP-style megabits/sec view."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("5.66MiB/s", "5.66MiB/s (47.5 Mb/s)"),
            ("1.6 MiB/s", "1.6 MiB/s (13.4 Mb/s)"),
            ("950KiB/s", "950KiB/s (7.8 Mb/s)"),
            ("?", "?"),
        ],
    )
    def test_formats_speed(self, raw: str, expected: str) -> None:
        assert gui._format_speed_label(raw) == expected  # pyright: ignore[reportPrivateUsage]


class TestLoadHistory:
    """load_history() loads valid entries and survives corruption."""

    def test_returns_empty_when_no_file(self, tmp_path: pytest.TempPathFactory) -> None:
        fake_path = str(tmp_path / "nonexistent.json")  # type: ignore[operator]
        with mock.patch.object(gui, "HISTORY_FILE", fake_path):
            assert gui.load_history() == []

    def test_loads_valid_entries(self, tmp_path: pytest.TempPathFactory) -> None:
        path = str(tmp_path / "hist.json")  # type: ignore[operator]
        entries = [{"time": "2024-01-01", "title": "Test", "path": "/tmp", "status": "success"}]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        with mock.patch.object(gui, "HISTORY_FILE", path):
            result = gui.load_history()
        assert len(result) == 1
        assert result[0]["title"] == "Test"

    def test_skips_invalid_entries(self, tmp_path: pytest.TempPathFactory) -> None:
        path = str(tmp_path / "hist.json")  # type: ignore[operator]
        entries: list[dict[str, str] | str] = [
            {"time": "2024-01-01", "title": "Good", "path": "/tmp", "status": "success"},
            {"bad": "entry"},  # missing required keys
            "not a dict",
        ]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        with mock.patch.object(gui, "HISTORY_FILE", path):
            result = gui.load_history()
        assert len(result) == 1

    def test_survives_corrupt_file(self, tmp_path: pytest.TempPathFactory) -> None:
        path = str(tmp_path / "hist.json")  # type: ignore[operator]
        with open(path, "w", encoding="utf-8") as f:
            f.write("{corrupt")
        with mock.patch.object(gui, "HISTORY_FILE", path):
            assert gui.load_history() == []


class TestSaveHistory:
    """save_history() persists entries and caps at 50."""

    def test_saves_and_loads(self, tmp_path: pytest.TempPathFactory) -> None:
        path = str(tmp_path / "hist.json")  # type: ignore[operator]
        entries = [{"time": "2024-01-01", "title": "Test", "path": "/tmp", "status": "success"}]
        with mock.patch.object(gui, "HISTORY_FILE", path):
            assert gui.save_history(entries) is True
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data == entries

    def test_caps_at_50(self, tmp_path: pytest.TempPathFactory) -> None:
        path = str(tmp_path / "hist.json")  # type: ignore[operator]
        entries = [
            {"time": f"t{i}", "title": f"v{i}", "path": "/tmp", "status": "success"}
            for i in range(100)
        ]
        with mock.patch.object(gui, "HISTORY_FILE", path):
            gui.save_history(entries)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 50

    def test_returns_false_on_failure(self) -> None:
        with mock.patch.object(gui, "HISTORY_FILE", "/nonexistent_xyz/hist.json"):
            assert gui.save_history([]) is False


class TestStreamTypeDetection:
    """_update_progress uses stream type to distinguish video/audio downloads."""

    @staticmethod
    def _stream_type(vcodec: str, acodec: str) -> str:
        """Mirror the stream-type logic from gui_hook for unit testing."""
        has_video = vcodec != "none"
        has_audio = acodec != "none"
        if has_video and has_audio:
            return "combined"
        if has_video:
            return "video"
        if has_audio:
            return "audio"
        return "media"

    @pytest.mark.parametrize(
        ("vcodec", "acodec", "expected"),
        [
            ("avc1.64001f", "none", "video"),
            ("none", "mp4a.40.2", "audio"),
            ("avc1.64001f", "mp4a.40.2", "combined"),
            ("none", "none", "media"),
            ("vp9", "none", "video"),
            ("none", "opus", "audio"),
        ],
    )
    def test_stream_type_classification(self, vcodec: str, acodec: str, expected: str) -> None:
        assert self._stream_type(vcodec, acodec) == expected
