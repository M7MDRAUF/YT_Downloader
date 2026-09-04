"""Tests for download.py — URL validation, format presets, option building."""

# pyright: reportPrivateUsage=false
# Tests intentionally exercise module-private helpers (e.g. _has_bundled_ejs,
# _default_remote_components, _DEFAULT_PLAYLIST_LIMIT) to lock in behaviour.

import io
import pathlib

import pytest

import download
from download import DownloadError
from tests.helpers import FakeYDL


class TestIsValidUrl:
    """is_valid_url() accepts YouTube URLs and rejects everything else."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/watch?v=abc123",
            "https://m.youtube.com/watch?v=abc123",
            "https://music.youtube.com/watch?v=abc123",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/abc123",
            "https://www.youtube.com/embed/abc123",
            "https://www.youtube.com/live/abc123",
            "https://www.youtube.com/playlist?list=PLabc",
            "https://www.youtube.com/clip/abc123",
            "https://www.youtube.com/@channelname",
            "https://www.youtube.com/channel/UCabc",
            "https://www.youtube.com/c/channelname",
            "https://www.youtube.com/user/username",
            "http://www.youtube.com/watch?v=abc",
        ],
    )
    def test_accepts_youtube_urls(self, url: str) -> None:
        assert download.is_valid_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "",
            "not a url",
            "ftp://youtube.com/watch?v=abc",
            "https://vimeo.com/12345",
            "https://example.com",
            "javascript:alert(1)",
            "file:///etc/passwd",
        ],
    )
    def test_rejects_non_youtube_urls(self, url: str) -> None:
        assert download.is_valid_url(url) is False


class TestFormatPresets:
    """FORMAT_PRESETS has expected keys and non-empty values."""

    def test_has_expected_keys(self) -> None:
        expected = {"best", "1080p", "720p", "480p", "audio"}
        assert set(download.FORMAT_PRESETS.keys()) == expected

    def test_values_are_strings(self) -> None:
        for v in download.FORMAT_PRESETS.values():
            assert isinstance(v, str)
            assert len(v) > 0


class TestBuildYdlOpts:
    """build_ydl_opts() returns valid option dicts."""

    def test_returns_dict(self) -> None:
        opts = download.build_ydl_opts(output_dir="/tmp/test")
        assert isinstance(opts, dict)

    def test_output_dir_in_outtmpl(self) -> None:
        opts = download.build_ydl_opts(output_dir="/tmp/test")
        assert "/tmp/test" in opts["outtmpl"]

    def test_format_preset_best(self) -> None:
        opts = download.build_ydl_opts(format_preset="best")
        assert opts["format"] == download.FORMAT_PRESETS["best"]

    def test_format_preset_audio(self) -> None:
        opts = download.build_ydl_opts(format_preset="audio")
        assert opts["format"] == download.FORMAT_PRESETS["audio"]
        # Audio should NOT have merge_output_format
        assert "merge_output_format" not in opts
        # Audio should have FFmpegExtractAudio postprocessor
        pps = opts.get("postprocessors", [])
        assert any(pp["key"] == "FFmpegExtractAudio" for pp in pps)

    def test_subtitles_option(self) -> None:
        opts = download.build_ydl_opts(subtitles=True)
        assert opts["writesubtitles"] is True
        assert opts["writeautomaticsub"] is True

    def test_no_subtitles_by_default(self) -> None:
        opts = download.build_ydl_opts()
        assert "writesubtitles" not in opts

    def test_sponsorblock_option(self) -> None:
        opts = download.build_ydl_opts(sponsorblock=True)
        pps = opts.get("postprocessors", [])
        assert any(pp["key"] == "SponsorBlock" for pp in pps)

    def test_playlist_option(self) -> None:
        opts = download.build_ydl_opts(playlist=True)
        assert opts["noplaylist"] is False

    def test_playlist_safeguards_when_enabled(self) -> None:
        opts = download.build_ydl_opts(playlist=True)
        assert opts["playlistend"] == download._DEFAULT_PLAYLIST_LIMIT
        assert opts["lazy_playlist"] is True

    def test_playlist_safeguards_absent_when_disabled(self) -> None:
        opts = download.build_ydl_opts(playlist=False)
        assert "playlistend" not in opts
        assert "lazy_playlist" not in opts

    def test_playlist_flat_opts_for_metadata(self) -> None:
        """Verify the extract_flat technique used by gui.py for fast playlist metadata."""
        opts = download.build_ydl_opts(playlist=True, quiet=True)
        flat_opts = dict(opts)
        flat_opts["extract_flat"] = "in_playlist"
        flat_opts["playlistend"] = 1
        # flat_opts should keep all base settings but override for metadata
        assert flat_opts["extract_flat"] == "in_playlist"
        assert flat_opts["playlistend"] == 1
        # Original opts must be unchanged (200 for download phase)
        assert opts["playlistend"] == download._DEFAULT_PLAYLIST_LIMIT
        assert "extract_flat" not in opts

    def test_no_playlist_by_default(self) -> None:
        opts = download.build_ydl_opts()
        assert opts["noplaylist"] is True

    def test_quiet_option(self) -> None:
        opts = download.build_ydl_opts(quiet=True)
        assert opts["quiet"] is True

    def test_fallback_format_for_unknown_preset(self) -> None:
        opts = download.build_ydl_opts(format_preset="nonexistent")
        assert opts["format"] == download.FORMAT_PRESETS["best"]

    def test_resilience_options_present(self) -> None:
        opts = download.build_ydl_opts()
        assert opts["retries"] == 10
        assert opts["fragment_retries"] == 10
        assert opts["socket_timeout"] == 30

    def test_speed_tuning_options_present(self) -> None:
        opts = download.build_ydl_opts()
        assert opts["buffersize"] == 256 * 1024
        assert opts["http_chunk_size"] == 10 * 1024 * 1024
        assert opts["concurrent_fragment_downloads"] == 8
        assert opts["throttledratelimit"] == 100_000
        # format_sort is off by default (prefer_direct_formats=False)
        assert "format_sort" not in opts

    def test_format_sort_when_prefer_direct(self) -> None:
        opts = download.build_ydl_opts(prefer_direct_formats=True)
        assert opts["format_sort"] == ["proto"]

    def test_can_disable_direct_format_preference(self) -> None:
        opts = download.build_ydl_opts(prefer_direct_formats=False)
        assert "format_sort" not in opts

    def test_merger_args_include_faststart_and_threads(self) -> None:
        opts = download.build_ydl_opts(format_preset="best")
        pp_args = opts.get("postprocessor_args", {})
        merger = pp_args.get("merger", [])
        assert "-movflags" in merger
        assert "+faststart" in merger
        assert "-threads" in merger
        assert "0" in merger

    def test_audio_preset_has_no_merger_args(self) -> None:
        opts = download.build_ydl_opts(format_preset="audio")
        assert "postprocessor_args" not in opts or "merger" not in opts.get(
            "postprocessor_args", {}
        )

    def test_ignore_no_formats_error_not_set(self) -> None:
        """ignore_no_formats_error masks the missing-EJS-solver failure mode and was removed."""
        opts = download.build_ydl_opts()
        assert "ignore_no_formats_error" not in opts

    def test_remote_components_absent_when_ejs_bundled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(download, "_has_bundled_ejs", lambda: True)
        monkeypatch.setattr(download, "_find_deno", lambda: None)
        opts = download.build_ydl_opts()
        assert "remote_components" not in opts

    def test_remote_components_present_when_ejs_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(download, "_has_bundled_ejs", lambda: False)
        monkeypatch.setattr(download, "_find_deno", lambda: None)
        opts = download.build_ydl_opts()
        assert opts["remote_components"] == ["ejs:github"]

    def test_remote_components_includes_npm_when_deno_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(download, "_has_bundled_ejs", lambda: False)
        monkeypatch.setattr(download, "_find_deno", lambda: "/fake/deno")
        opts = download.build_ydl_opts()
        assert opts["remote_components"] == ["ejs:github", "ejs:npm"]


class TestEjsHelpers:
    """EJS solver detection helpers."""

    def test_has_bundled_ejs_returns_bool(self) -> None:
        assert isinstance(download._has_bundled_ejs(), bool)

    def test_default_remote_components_empty_when_bundled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(download, "_has_bundled_ejs", lambda: True)
        assert download._default_remote_components() == []

    def test_default_remote_components_github_only_without_deno(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(download, "_has_bundled_ejs", lambda: False)
        monkeypatch.setattr(download, "_find_deno", lambda: None)
        assert download._default_remote_components() == ["ejs:github"]

    def test_default_remote_components_includes_npm_with_deno(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(download, "_has_bundled_ejs", lambda: False)
        monkeypatch.setattr(download, "_find_deno", lambda: "/fake/deno")
        assert download._default_remote_components() == ["ejs:github", "ejs:npm"]

    def test_describe_ejs_status_bundled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(download, "_has_bundled_ejs", lambda: True)
        monkeypatch.setattr(download, "_find_deno", lambda: "/fake/deno")
        msg = download.describe_ejs_status()
        assert "bundled" in msg
        assert "deno" in msg

    def test_describe_ejs_status_remote_with_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(download, "_has_bundled_ejs", lambda: False)
        monkeypatch.setattr(download, "_find_deno", lambda: "/fake/deno")
        msg = download.describe_ejs_status()
        assert "remote" in msg
        assert "ejs:github" in msg

    def test_describe_ejs_status_remote_without_runtime(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(download, "_has_bundled_ejs", lambda: False)
        monkeypatch.setattr(download, "_find_deno", lambda: None)
        msg = download.describe_ejs_status()
        assert "deno" in msg.lower()


class TestGetYdlVersion:
    """get_ydl_version() returns a version string."""

    def test_returns_string(self) -> None:
        ver = download.get_ydl_version()
        assert isinstance(ver, str)
        assert len(ver) > 0
        assert ver != "unknown"


class TestFormatLabels:
    def test_labels_and_presets_agree(self) -> None:
        """The two dicts are the reason a preset used to silently fall back."""
        assert set(download.FORMAT_LABELS) == set(download.FORMAT_PRESETS)

    def test_best_is_first(self) -> None:
        # Insertion order drives the GUI dropdown order.
        assert next(iter(download.FORMAT_LABELS)) == "best"


class TestClassifyStreamType:
    @pytest.mark.parametrize(
        ("info", "expected"),
        [
            ({"vcodec": "avc1", "acodec": "none"}, "video"),
            ({"vcodec": "none", "acodec": "mp4a"}, "audio"),
            ({"vcodec": "vp9", "acodec": "opus"}, "combined"),
            ({"vcodec": "none", "acodec": "none"}, "media"),
            ({}, "media"),
        ],
    )
    def test_classification(self, info: dict[str, str], expected: str) -> None:
        assert download.classify_stream_type(info) == expected


class TestHasFfmpeg:
    def test_returns_bool(self) -> None:
        download.has_ffmpeg.cache_clear()
        assert isinstance(download.has_ffmpeg(), bool)

    def test_false_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        download.has_ffmpeg.cache_clear()
        monkeypatch.setattr(download.shutil, "which", lambda _n: None)
        assert download.has_ffmpeg() is False
        download.has_ffmpeg.cache_clear()

    def test_true_when_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        download.has_ffmpeg.cache_clear()
        monkeypatch.setattr(download.shutil, "which", lambda _n: "/usr/bin/ffmpeg")
        assert download.has_ffmpeg() is True
        download.has_ffmpeg.cache_clear()


class TestExtractAndDownload:
    """Playlists and single videos take different yt-dlp paths."""

    class _Ydl:
        def __init__(self) -> None:
            self.downloaded: list[list[str]] = []
            self.processed: list[dict[str, object]] = []

        def download(self, urls: list[str]) -> None:
            self.downloaded.append(urls)

        def process_info(self, info: dict[str, object]) -> None:
            self.processed.append(info)

    @pytest.mark.parametrize("kind", ["playlist", "multi_video"])
    def test_playlist_uses_download(self, kind: str) -> None:
        ydl = self._Ydl()
        download.extract_and_download(ydl, "u", {"_type": kind})
        assert ydl.downloaded == [["u"]]
        assert ydl.processed == []

    def test_single_video_reuses_info(self) -> None:
        ydl = self._Ydl()
        info = {"title": "T"}
        download.extract_and_download(ydl, "u", info)
        # process_info avoids a second page fetch
        assert ydl.processed == [info]
        assert ydl.downloaded == []


class TestGetCookiesBrowser:
    def test_returns_first_successful_browser(
        self, monkeypatch: pytest.MonkeyPatch, real_cookie_probe: object
    ) -> None:
        monkeypatch.setattr(download, "_cookies_browser_checked", False)
        monkeypatch.setattr(download, "_cookies_browser_cache", None)

        class _OK:
            def __init__(self, opts: dict[str, object]) -> None:
                self.cookiejar = object()

            def __enter__(self) -> "_OK":
                return self

            def __exit__(self, *_e: object) -> None:
                return None

        monkeypatch.setattr(download.yt_dlp, "YoutubeDL", _OK)
        assert download.get_cookies_browser() == download._BROWSERS[0]

    def test_returns_none_when_all_fail(
        self, monkeypatch: pytest.MonkeyPatch, real_cookie_probe: object
    ) -> None:
        monkeypatch.setattr(download, "_cookies_browser_checked", False)
        monkeypatch.setattr(download, "_cookies_browser_cache", None)

        def _boom(_opts: dict[str, object]) -> None:
            raise RuntimeError("locked")

        monkeypatch.setattr(download.yt_dlp, "YoutubeDL", _boom)
        assert download.get_cookies_browser() is None

    def test_positive_result_is_cached(
        self, monkeypatch: pytest.MonkeyPatch, real_cookie_probe: object
    ) -> None:
        monkeypatch.setattr(download, "_cookies_browser_checked", True)
        monkeypatch.setattr(download, "_cookies_browser_cache", "firefox")
        # Would raise if the cache were not consulted first.
        monkeypatch.setattr(download.yt_dlp, "YoutubeDL", None)
        assert download.get_cookies_browser() == "firefox"


class TestCliProgressHook:
    def test_downloading_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        download._cli_progress_hook(
            {
                "status": "downloading",
                "_percent_str": " 42%",
                "_speed_str": "1MiB/s",
                "_eta_str": "00:10",
            }
        )
        out = capsys.readouterr().out
        assert "42%" in out
        assert "1MiB/s" in out
        assert "00:10" in out

    def test_finished_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        download._cli_progress_hook({"status": "finished"})
        assert "processing" in capsys.readouterr().out

    def test_other_status_prints_nothing(self, capsys: pytest.CaptureFixture[str]) -> None:
        download._cli_progress_hook({"status": "error"})
        assert capsys.readouterr().out == ""


class TestBuildArgParser:
    def test_url_is_optional(self) -> None:
        assert download.build_arg_parser().parse_args([]).url is None

    def test_parses_all_flags(self) -> None:
        args = download.build_arg_parser().parse_args(
            [
                "https://youtu.be/x",
                "-o",
                "out",
                "-f",
                "720p",
                "--subtitles",
                "--sponsorblock",
                "--playlist",
                "--prefer-direct",
            ]
        )
        assert args.url == "https://youtu.be/x"
        assert args.output_dir == "out"
        assert args.format_preset == "720p"
        assert args.subtitles
        assert args.sponsorblock
        assert args.playlist
        assert args.prefer_direct_formats

    def test_defaults_are_off(self) -> None:
        args = download.build_arg_parser().parse_args(["u"])
        assert args.format_preset == "best"
        assert not args.subtitles
        assert not args.sponsorblock
        assert not args.playlist
        assert not args.prefer_direct_formats

    def test_rejects_unknown_preset(self) -> None:
        with pytest.raises(SystemExit):
            download.build_arg_parser().parse_args(["u", "-f", "4k"])


class TestPrompt:
    def test_returns_default_when_not_a_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Piped invocation must not die on input()."""
        monkeypatch.setattr(download.sys, "stdin", io.StringIO(""))
        assert download._prompt("q: ", "fallback") == "fallback"

    def test_returns_default_on_eof(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

        monkeypatch.setattr(download.sys, "stdin", _Tty(""))
        monkeypatch.setattr("builtins.input", lambda _p: (_ for _ in ()).throw(EOFError()))
        assert download._prompt("q: ", "fallback") == "fallback"

    def test_uses_input_on_tty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Tty(io.StringIO):
            def isatty(self) -> bool:
                return True

        monkeypatch.setattr(download.sys, "stdin", _Tty(""))
        monkeypatch.setattr("builtins.input", lambda _p: "  typed  ")
        assert download._prompt("q: ", "fallback") == "typed"


@pytest.fixture
def _ffmpeg_present(monkeypatch: pytest.MonkeyPatch) -> None:
    download.has_ffmpeg.cache_clear()
    monkeypatch.setattr(download, "has_ffmpeg", lambda: True)


class TestDownloadVideo:
    def test_playlist_uses_download(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, fake_ydl: type[FakeYDL]
    ) -> None:
        monkeypatch.setattr(download.yt_dlp, "YoutubeDL", fake_ydl)
        fake_ydl.instances.clear()
        monkeypatch.setattr(fake_ydl, "info", None, raising=False)
        ydl_holder: list[object] = []

        class _Playlist(fake_ydl):  # type: ignore[valid-type,misc]
            def __init__(self, opts: dict[str, object] | None = None) -> None:
                super().__init__(opts)
                self.info = {"title": "PL", "duration": 0, "_type": "playlist"}
                ydl_holder.append(self)

        monkeypatch.setattr(download.yt_dlp, "YoutubeDL", _Playlist)
        download.download_video("https://youtu.be/x", str(tmp_path))
        assert ydl_holder[0].download_calls == [["https://youtu.be/x"]]  # type: ignore[attr-defined]

    def test_single_video_uses_process_info(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, fake_ydl: type[FakeYDL]
    ) -> None:
        fake_ydl.instances.clear()
        monkeypatch.setattr(download.yt_dlp, "YoutubeDL", fake_ydl)
        download.download_video("https://youtu.be/x", str(tmp_path))
        ydl = fake_ydl.instances[0]
        assert ydl.process_calls
        assert not ydl.download_calls
        assert ydl.extract_calls == [("https://youtu.be/x", False)]

    def test_raises_when_info_is_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, fake_ydl: type[FakeYDL]
    ) -> None:
        class _NoInfo(fake_ydl):  # type: ignore[valid-type,misc]
            def extract_info(self, url: str, download: bool = True) -> None:
                return None

        monkeypatch.setattr(download.yt_dlp, "YoutubeDL", _NoInfo)
        with pytest.raises(DownloadError, match="Could not extract"):
            download.download_video("https://youtu.be/x", str(tmp_path))

    def test_creates_output_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, fake_ydl: type[FakeYDL]
    ) -> None:
        monkeypatch.setattr(download.yt_dlp, "YoutubeDL", fake_ydl)
        target = tmp_path / "nested" / "dir"
        download.download_video("https://youtu.be/x", str(target))
        assert target.is_dir()

    def test_passes_options_through(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, fake_ydl: type[FakeYDL]
    ) -> None:
        fake_ydl.instances.clear()
        monkeypatch.setattr(download.yt_dlp, "YoutubeDL", fake_ydl)
        download.download_video(
            "https://youtu.be/x", str(tmp_path), format_preset="audio", subtitles=True
        )
        opts = fake_ydl.instances[0].opts
        assert opts["format"] == download.FORMAT_PRESETS["audio"]
        assert opts["writesubtitles"] is True


class TestMain:
    def test_exits_1_on_empty_url(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.setattr(download, "_prompt", lambda *_a: "")
        with pytest.raises(SystemExit) as exc:
            download.main([])
        assert exc.value.code == 1
        assert "No URL provided" in capsys.readouterr().out

    def test_exits_1_on_non_youtube_url(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            download.main(["https://example.com/video"])
        assert exc.value.code == 1
        assert "doesn't look like a YouTube URL" in capsys.readouterr().out

    def test_exits_1_when_ffmpeg_missing(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Previously this failed only after downloading both streams."""
        monkeypatch.setattr(download, "has_ffmpeg", lambda: False)
        with pytest.raises(SystemExit) as exc:
            download.main(["https://youtu.be/abc"])
        assert exc.value.code == 1
        assert "ffmpeg was not found" in capsys.readouterr().out

    @pytest.mark.usefixtures("_ffmpeg_present")
    def test_happy_path_forwards_every_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: dict[str, object] = {}

        def _fake_dl(url: str, output_dir: str, **kwargs: object) -> None:
            seen.update({"url": url, "output_dir": output_dir, **kwargs})

        monkeypatch.setattr(download, "download_video", _fake_dl)
        download.main(
            ["https://youtu.be/abc", "-o", "out", "-f", "720p", "--subtitles", "--playlist"]
        )
        assert seen["url"] == "https://youtu.be/abc"
        assert seen["output_dir"] == "out"
        assert seen["format_preset"] == "720p"
        assert seen["subtitles"] is True
        assert seen["playlist"] is True

    @pytest.mark.usefixtures("_ffmpeg_present")
    def test_does_not_prompt_when_piped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression: main() used to call input() even with a URL in argv,
        so piped invocation died with an uncaught EOFError."""
        monkeypatch.setattr(download.sys, "stdin", io.StringIO(""))
        monkeypatch.setattr("builtins.input", lambda _p: pytest.fail("input() called"))
        captured: dict[str, object] = {}
        monkeypatch.setattr(download, "download_video", lambda u, o, **k: captured.update(dir=o))
        download.main(["https://youtu.be/abc"])
        assert captured["dir"] == "downloads"

    @pytest.mark.usefixtures("_ffmpeg_present")
    def test_exits_1_on_download_error(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def _boom(*_a: object, **_k: object) -> None:
            raise DownloadError("nope")

        monkeypatch.setattr(download, "download_video", _boom)
        with pytest.raises(SystemExit) as exc:
            download.main(["https://youtu.be/abc", "-o", "d"])
        assert exc.value.code == 1
        assert "Download error: nope" in capsys.readouterr().out

    @pytest.mark.usefixtures("_ffmpeg_present")
    def test_exits_1_on_oserror(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def _boom(*_a: object, **_k: object) -> None:
            raise PermissionError("read-only")

        monkeypatch.setattr(download, "download_video", _boom)
        with pytest.raises(SystemExit) as exc:
            download.main(["https://youtu.be/abc", "-o", "d"])
        assert exc.value.code == 1
        assert "System error: read-only" in capsys.readouterr().out

    @pytest.mark.usefixtures("_ffmpeg_present")
    def test_exits_130_on_keyboard_interrupt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Was exit 0 — an aborted download reported success to scripts."""

        def _boom(*_a: object, **_k: object) -> None:
            raise KeyboardInterrupt

        monkeypatch.setattr(download, "download_video", _boom)
        with pytest.raises(SystemExit) as exc:
            download.main(["https://youtu.be/abc", "-o", "d"])
        assert exc.value.code == 130


class TestStdoutEncoding:
    """A non-ASCII video title must not kill a redirected CLI run."""

    def test_unencodable_title_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Emulate Windows redirecting stdout to a pipe: locale encoding, strict.
        buf = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
        monkeypatch.setattr(download.sys, "stdout", buf)
        download._make_stdout_lenient()
        print("Title    : \u4f60\u597d caf\u00e9 \U0001f600")  # must not raise
        buf.flush()

    def test_survives_a_stream_without_reconfigure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(download.sys, "stdout", io.StringIO())
        download._make_stdout_lenient()  # StringIO has no .reconfigure


class TestPromptRobustness:
    """_prompt must never raise, whatever state stdin is in."""

    def test_closed_stdin_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # A closed file object is still truthy, so a bare falsy check does not
        # cover it and isatty() raises ValueError.
        stream = io.StringIO()
        stream.close()
        monkeypatch.setattr(download.sys, "stdin", stream)
        assert download._prompt("q: ", "fallback") == "fallback"

    def test_none_stdin_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(download.sys, "stdin", None)
        assert download._prompt("q: ", "fallback") == "fallback"

    def test_isatty_raising_oserror_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Hostile(io.StringIO):
            def isatty(self) -> bool:
                raise OSError("detached")

        monkeypatch.setattr(download.sys, "stdin", _Hostile())
        assert download._prompt("q: ", "fallback") == "fallback"

    def test_main_survives_closed_stdin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression: an embedding host that closed stdin got a traceback."""
        monkeypatch.setattr(download, "has_ffmpeg", lambda: True)
        stream = io.StringIO()
        stream.close()
        monkeypatch.setattr(download.sys, "stdin", stream)
        seen: dict[str, object] = {}
        monkeypatch.setattr(download, "download_video", lambda u, o, **k: seen.update(out=o))
        download.main(["https://youtu.be/abc"])  # must not raise
        assert seen["out"] == "downloads"


class TestErrorAttribution:
    """A network failure must not be reported as a disk failure."""

    def test_makedirs_failure_is_a_download_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*_a: object, **_k: object) -> None:
            raise PermissionError("read-only")

        monkeypatch.setattr(download.os, "makedirs", _boom)
        with pytest.raises(DownloadError, match="Cannot create folder"):
            download.download_video("https://youtu.be/x", "/nope")

    def test_network_oserror_is_not_blamed_on_the_folder(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from urllib.error import URLError

        monkeypatch.setattr(download, "has_ffmpeg", lambda: True)

        def _boom(*_a: object, **_k: object) -> None:
            raise URLError("Connection reset by peer")

        monkeypatch.setattr(download, "download_video", _boom)
        with pytest.raises(SystemExit) as exc:
            download.main(["https://youtu.be/abc", "-o", "downloads"])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        # URLError is an OSError subclass; the message must not point at the dir.
        assert "Cannot write to" not in out
        assert "Connection reset" in out
