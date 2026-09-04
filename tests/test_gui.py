"""Tests for gui.py — URL safety, history persistence, helpers."""

import json
import pathlib
import subprocess
import sys
import threading
from unittest import mock

import pytest

import download
import gui  # imported after conftest installs the tkinter stub
from gui import history_csv_rows


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

    def test_returns_empty_when_no_file(self, tmp_path: pathlib.Path) -> None:
        fake_path = str(tmp_path / "nonexistent.json")
        with mock.patch.object(gui, "HISTORY_FILE", fake_path):
            assert gui.load_history() == []

    def test_loads_valid_entries(self, tmp_path: pathlib.Path) -> None:
        path = str(tmp_path / "hist.json")
        entries = [{"time": "2024-01-01", "title": "Test", "path": "/tmp", "status": "success"}]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        with mock.patch.object(gui, "HISTORY_FILE", path):
            result = gui.load_history()
        assert len(result) == 1
        assert result[0]["title"] == "Test"

    def test_skips_invalid_entries(self, tmp_path: pathlib.Path) -> None:
        path = str(tmp_path / "hist.json")
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

    def test_survives_corrupt_file(self, tmp_path: pathlib.Path) -> None:
        path = str(tmp_path / "hist.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{corrupt")
        with mock.patch.object(gui, "HISTORY_FILE", path):
            assert gui.load_history() == []


class TestSaveHistory:
    """save_history() persists entries and caps at 50."""

    def test_saves_and_loads(self, tmp_path: pathlib.Path) -> None:
        path = str(tmp_path / "hist.json")
        entries = [{"time": "2024-01-01", "title": "Test", "path": "/tmp", "status": "success"}]
        with mock.patch.object(gui, "HISTORY_FILE", path):
            assert gui.save_history(entries) is True
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data == entries

    def test_caps_at_50(self, tmp_path: pathlib.Path) -> None:
        path = str(tmp_path / "hist.json")
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
    """gui_hook tags progress updates with the stream type.

    These used to test a copy of the logic pasted into this file, which could
    never catch a regression in the real code.  They now call the shared
    implementation in download.py.
    """

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
        assert download.classify_stream_type({"vcodec": vcodec, "acodec": acodec}) == expected

    def test_missing_codec_keys_default_to_media(self) -> None:
        assert download.classify_stream_type({}) == "media"


class TestHistoryCsvRows:
    def test_header_comes_first(self) -> None:
        assert history_csv_rows([])[0] == ["time", "title", "path", "status"]

    def test_row_order_matches_header(self) -> None:
        rows = history_csv_rows([{"time": "T", "title": "Vid", "path": "/d", "status": "success"}])
        assert rows[1] == ["T", "Vid", "/d", "success"]

    def test_missing_status_defaults_to_success(self) -> None:
        rows = history_csv_rows([{"time": "T", "title": "V", "path": "/d"}])
        assert rows[1][3] == "success"


class TestTrackChildProcesses:
    """The context manager that replaced the UnboundLocalError-prone try/finally."""

    def test_restores_popen_on_normal_exit(self) -> None:
        original = subprocess.Popen.__init__
        with gui._track_child_processes(set()):
            assert subprocess.Popen.__init__ is not original
        assert subprocess.Popen.__init__ is original

    def test_restores_popen_when_body_raises(self) -> None:
        # This is the regression: an exception inside the block must still
        # restore the patch.  The old code raised UnboundLocalError here and
        # left the app permanently disabled.
        original = subprocess.Popen.__init__
        with pytest.raises(ValueError, match="boom"), gui._track_child_processes(set()):
            raise ValueError("boom")
        assert subprocess.Popen.__init__ is original

    def test_registers_spawned_process(self) -> None:
        sink: set[object] = set()
        with gui._track_child_processes(sink):
            proc = subprocess.Popen([sys.executable, "-c", "pass"])
            proc.wait()
        assert proc in sink

    def test_uses_lock_when_supplied(self) -> None:
        sink: set[object] = set()
        lock = threading.Lock()
        with gui._track_child_processes(sink, lock):
            proc = subprocess.Popen([sys.executable, "-c", "pass"])
            proc.wait()
        assert proc in sink
        assert not lock.locked()
