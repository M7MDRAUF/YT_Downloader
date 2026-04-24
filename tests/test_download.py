"""Tests for download.py — URL validation, format presets, option building."""

# pyright: reportPrivateUsage=false
# Tests intentionally exercise module-private helpers (e.g. _has_bundled_ejs,
# _default_remote_components, _DEFAULT_PLAYLIST_LIMIT) to lock in behaviour.

import pytest

import download


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
