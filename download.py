import argparse
import contextlib
import functools
import importlib.util
import os
import re
import shutil
import sys
from collections.abc import Mapping
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError

# ---------------------------------------------------------------------------
# Constants — single source of truth for ydl options
# ---------------------------------------------------------------------------

# Firefox first: Chrome triggers noisy DPAPI errors on Windows even when it
# ultimately falls back.  Putting Firefox first avoids those spurious ERRORs.
_BROWSERS: tuple[str, ...] = (
    "firefox",
    "chrome",
    "edge",
    "brave",
    "opera",
    "chromium",
    "vivaldi",
)

_YT_URL_RE = re.compile(
    r"^https?://"
    r"("
    r"(www\.|m\.|music\.)?youtube\.com/"
    r"(watch\?|shorts/|embed/|live/|playlist\?|clip/|v/|@[\w.-]+|channel/|c/|user/)"
    r"|youtu\.be/"
    r")",
)

_DEFAULT_BUFFER_SIZE = 256 * 1024
_DEFAULT_HTTP_CHUNK_SIZE = 10 * 1024 * 1024
_DEFAULT_CONCURRENT_FRAGMENT_DOWNLOADS = 8
_THROTTLED_RATE_LIMIT = 100_000
_DEFAULT_PLAYLIST_LIMIT = 200


@functools.lru_cache(maxsize=1)
def _find_deno() -> str | None:
    """Find the deno binary, checking PATH and common Windows install locations."""
    found = shutil.which("deno")
    if found:
        return found
    if sys.platform == "win32":
        # Winget shim may not be on PATH in all terminal contexts (e.g. VS Code bg shells)
        winget_shim = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Links\deno.EXE")
        if os.path.isfile(winget_shim):
            return winget_shim
    return None


@functools.lru_cache(maxsize=1)
def _has_bundled_ejs() -> bool:
    """Return True if the ``yt-dlp-ejs`` companion package is importable.

    yt-dlp delegates YouTube JavaScript challenge solving to scripts shipped in
    the ``yt_dlp_ejs`` package (installed via the ``yt-dlp[default]`` extra).
    When it is missing, yt-dlp can still fetch the scripts at runtime via
    ``remote_components`` — see :func:`_default_remote_components`.
    """
    return importlib.util.find_spec("yt_dlp_ejs") is not None


def _default_remote_components() -> list[str]:
    """Return the list of remote-component sources to enable as a fallback.

    - When ``yt-dlp-ejs`` is bundled locally, no remote fetch is needed.
    - Otherwise prefer ``ejs:github`` (works with any runtime, including the
      ones yt-dlp may add later); also enable ``ejs:npm`` when ``deno`` is
      available, since the npm path requires a runtime that supports on-the-fly
      npm package resolution (deno or bun).
    """
    if _has_bundled_ejs():
        return []
    components = ["ejs:github"]
    if _find_deno():
        components.append("ejs:npm")
    return components


def describe_ejs_status() -> str:
    """Return a single human-readable line describing the EJS solver setup.

    Used by the CLI startup banner and the GUI status bar so users can tell
    at a glance whether YouTube downloads are likely to succeed.
    """
    runtime = "deno" if _find_deno() else "none"
    if _has_bundled_ejs():
        return f"EJS solver: bundled (yt-dlp-ejs) | JS runtime: {runtime}"
    remote = _default_remote_components()
    if remote and runtime != "none":
        return f"EJS solver: remote ({', '.join(remote)}) | JS runtime: {runtime}"
    # No third branch: _default_remote_components() returns [] only when the
    # bundled package is present, and that case already returned above — so
    # `remote` is always non-empty here.
    return (
        f"EJS solver: remote ({', '.join(remote)}) | JS runtime: none "
        "— install deno (https://deno.com) for reliable YouTube downloads"
    )


# ---------------------------------------------------------------------------
# Public helpers — importable by gui.py
# ---------------------------------------------------------------------------


def is_valid_url(url: str) -> bool:
    """Return True if *url* looks like a YouTube video link."""
    return bool(_YT_URL_RE.match(url))


def get_cookies_browser() -> str | None:
    """Return the first browser whose cookie store is accessible, or None.

    Only positive results are cached — if no browser is found, the next call
    will probe again (the browser may have been temporarily locked or updating).
    """
    global _cookies_browser_cache, _cookies_browser_checked
    if _cookies_browser_checked:
        return _cookies_browser_cache
    for browser in _BROWSERS:
        try:
            with yt_dlp.YoutubeDL(
                {"cookiesfrombrowser": (browser,), "quiet": True, "no_warnings": True}
            ) as ydl:
                _ = ydl.cookiejar  # triggers cookie load
            _cookies_browser_cache = browser
            _cookies_browser_checked = True
            return browser
        except Exception:  # noqa: S112 — intentional: probe browsers in order
            continue
    # Don't cache negative results — allow retry on next download
    return None


_cookies_browser_cache: str | None = None
_cookies_browser_checked: bool = False


# ---------------------------------------------------------------------------
# Format presets — maps user-friendly names to yt-dlp format strings
# ---------------------------------------------------------------------------
FORMAT_PRESETS: dict[str, str] = {
    "best": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    "1080p": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
    "720p": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
    "480p": "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best",
    "audio": "bestaudio[ext=m4a]/bestaudio",
}

# Display names for the presets above.  Kept here rather than in gui.py so the
# keys have a single source of truth — see test_labels_and_presets_agree.
# Insertion order drives the order of the GUI's quality dropdown.
FORMAT_LABELS: dict[str, str] = {
    "best": "Best Quality",
    "1080p": "1080p",
    "720p": "720p",
    "480p": "480p",
    "audio": "Audio Only (MP3)",
}


@functools.lru_cache(maxsize=1)
def has_ffmpeg() -> bool:
    """Return True if ffmpeg is on PATH.

    Every non-trivial path needs it: DASH video+audio merging, the +faststart
    remux, SponsorBlock chapter removal, and MP3 extraction.  Checking up front
    turns a failure that used to happen *after* a full download into an
    immediate, actionable message.
    """
    return shutil.which("ffmpeg") is not None


def classify_stream_type(info: Mapping[str, Any]) -> str:
    """Classify a yt-dlp info dict as video / audio / combined / media.

    yt-dlp reports absent codecs as the literal string ``"none"``, not ``None``.
    Used to tell the two halves of a DASH video+audio pair apart in progress
    reporting.
    """
    has_video = str(info.get("vcodec", "none")) != "none"
    has_audio = str(info.get("acodec", "none")) != "none"
    if has_video and has_audio:
        return "combined"
    if has_video:
        return "video"
    if has_audio:
        return "audio"
    return "media"


def extract_and_download(ydl: Any, url: str, info: dict[str, Any]) -> None:
    """Download *url* from already-extracted *info*.

    Playlists go through ``download()`` for full entry handling; a single video
    reuses the info we already have via ``process_info()`` so yt-dlp does not
    fetch the page a second time.

    Shared by the CLI and the GUI: the two previously carried separate copies of
    this branch and had already drifted apart.
    """
    if info.get("_type") in ("playlist", "multi_video"):
        ydl.download([url])
    else:
        ydl.process_info(info)


def build_ydl_opts(
    output_dir: str = "downloads",
    progress_hooks: list[Any] | None = None,
    postprocessor_hooks: list[Any] | None = None,
    quiet: bool = False,
    format_preset: str = "best",
    subtitles: bool = False,
    sponsorblock: bool = False,
    playlist: bool = False,
    prefer_direct_formats: bool = False,
) -> dict[str, Any]:
    """Build the canonical yt-dlp option dict.

    This is the **single source of truth** — both the CLI and GUI must
    use this instead of hand-rolling their own option dicts.
    """
    fmt = FORMAT_PRESETS.get(format_preset, FORMAT_PRESETS["best"])
    is_audio = format_preset == "audio"
    deno_path = _find_deno()
    remote_components = _default_remote_components()

    opts: dict[str, Any] = {
        "format": fmt,
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "noplaylist": not playlist,
        # Safety: cap playlist entries to avoid hanging on infinite playlists
        # (e.g. YouTube Mix/Radio with list=RD…). Process lazily so yt-dlp
        # yields entries as they arrive instead of waiting for full enumeration.
        **(
            {
                "playlistend": _DEFAULT_PLAYLIST_LIMIT,
                "lazy_playlist": True,
            }
            if playlist
            else {}
        ),
        "progress_hooks": progress_hooks if progress_hooks is not None else [_cli_progress_hook],
        "postprocessor_hooks": postprocessor_hooks or [],
        # Keep yt-dlp on the default "main" player JS variant, but do not
        # force YouTube into the segmented "dashy" transport. Forcing dashy
        # makes even plain HTTPS formats download via http_dash_segments,
        # which can throttle much harder than direct HTTPS on some CDNs.
        "extractor_args": {"youtube": {"player_js_variant": ["main"]}},
        # Note: previously we passed ignore_no_formats_error=True here, which
        # silently swallowed the exact failure caused by a missing EJS solver
        # ("No video formats found"). The remote_components fallback below
        # plus a clear startup diagnostic make that error message useful again.
        # Network resilience
        "retries": 10,
        "fragment_retries": 10,
        "socket_timeout": 30,
        # Use a larger initial buffer on fast connections while still letting
        # yt-dlp resize dynamically as needed.
        "buffersize": _DEFAULT_BUFFER_SIZE,
        # Use chunked HTTP requests for plain HTTPS formats. This helps yt-dlp
        # recover from long-lived connection throttling without forcing every
        # YouTube download onto the slower segmented transport path.
        "http_chunk_size": _DEFAULT_HTTP_CHUNK_SIZE,
        # Note: concurrent fragment workers only apply to native dash/hls
        # transports and don't check for cancellation between fragments.
        # Cancellation takes effect after the current batch finishes.
        "concurrent_fragment_downloads": _DEFAULT_CONCURRENT_FRAGMENT_DOWNLOADS,
        # Auto-detect throttling: if speed drops below 100 KB/s for 3s,
        # re-extract fresh CDN URLs to bypass YouTube rate limits.
        "throttledratelimit": _THROTTLED_RATE_LIMIT,
    }
    # Only configure Deno JS runtime when the binary is present (SABR-fork feature)
    if deno_path:
        opts["js_runtimes"] = {"deno": {"path": deno_path}}
    # Allow yt-dlp to fetch EJS challenge-solver scripts at runtime when the
    # bundled ``yt-dlp-ejs`` package is not installed. Unsupported entries are
    # ignored by yt-dlp with a warning, so this is safe across versions.
    if remote_components:
        opts["remote_components"] = remote_components
    if prefer_direct_formats:
        # Prefer direct HTTP(S) delivery when yt-dlp sees equally suitable
        # formats. This preserves the user's quality choice while nudging
        # selection away from slower segmented transports when possible.
        opts["format_sort"] = ["proto"]
    if not is_audio:
        opts["merge_output_format"] = "mp4"
        # Move the MOOV atom (seek index) to the start of the MP4 file.
        # Without this, DASH fragment downloads place it at the end,
        # making seeking impossible in long videos — the player restarts
        # from the beginning instead of jumping to the requested time.
        # -threads 0: let ffmpeg auto-detect CPU cores (no effect for
        # remux with -c copy, but speeds up any re-encoding fallback).
        opts["postprocessor_args"] = {
            "merger": ["-movflags", "+faststart", "-threads", "0"],
        }

    # Subtitles
    if subtitles:
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = ["en", "ar"]
        opts["subtitlesformat"] = "srt/best"

    # SponsorBlock must run BEFORE FFmpegExtractAudio so chapters exist in the video stream
    if sponsorblock:
        pps = opts.setdefault("postprocessors", [])
        pps.append({"key": "SponsorBlock"})
        pps.append(
            {
                "key": "ModifyChapters",
                "remove_sponsor_segments": ["sponsor", "selfpromo", "interaction"],
            }
        )

    # Audio-only: FFmpegExtractAudio must be LAST postprocessor
    if is_audio:
        opts.setdefault("postprocessors", []).append(
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        )

    if quiet:
        opts["quiet"] = True
    browser = get_cookies_browser()
    if browser:
        opts["cookiesfrombrowser"] = (browser,)
    return opts


# ---------------------------------------------------------------------------
# Core download logic
# ---------------------------------------------------------------------------


def get_ydl_version() -> str:
    """Return the installed yt-dlp version string."""
    # yt-dlp ≥2026 moved the attribute to yt_dlp.version.__version__
    ver = getattr(yt_dlp, "__version__", None) or getattr(
        getattr(yt_dlp, "version", None), "__version__", "unknown"
    )
    return str(ver)


def download_video(
    url: str,
    output_dir: str = "downloads",
    format_preset: str = "best",
    subtitles: bool = False,
    sponsorblock: bool = False,
    playlist: bool = False,
    prefer_direct_formats: bool = False,
) -> None:
    """Download a YouTube video to *output_dir*."""
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as exc:
        # Reported as a DownloadError so the caller can distinguish "cannot
        # write here" from a network OSError, which is also an OSError.
        raise DownloadError(f"Cannot create folder '{output_dir}': {exc}") from exc

    ydl_opts = build_ydl_opts(
        output_dir,
        format_preset=format_preset,
        subtitles=subtitles,
        sponsorblock=sponsorblock,
        playlist=playlist,
        prefer_direct_formats=prefer_direct_formats,
    )

    if not ydl_opts.get("cookiesfrombrowser"):
        print("Warning: No browser cookies found. Download may be blocked by YouTube.")

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:  # type: ignore[arg-type]
        print(f"\nFetching info for: {url}")
        raw_info = ydl.extract_info(url, download=False)
        if not raw_info:
            raise DownloadError("Could not extract video information.")
        info: dict[str, Any] = dict(raw_info)
        title: str = str(info.get("title", "Unknown"))
        duration: int = int(info.get("duration") or 0)
        mins, secs = divmod(duration, 60)
        print(f"Title    : {title}")
        print(f"Duration : {mins}m {secs}s")
        print(f"Saving to: {os.path.abspath(output_dir)}\n")

        extract_and_download(ydl, url, info)

    print("\nDownload complete!")


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------


def _cli_progress_hook(d: dict[str, Any]) -> None:
    if d["status"] == "downloading":
        percent: str = str(d.get("_percent_str", "?%")).strip()
        speed: str = str(d.get("_speed_str", "?")).strip()
        eta: str = str(d.get("_eta_str", "?")).strip()
        print(f"\r  {percent}  |  Speed: {speed}  |  ETA: {eta}   ", end="", flush=True)
    elif d["status"] == "finished":
        print(
            "\r  Download complete \u2014 processing\u2026                  ",
            end="",
            flush=True,
        )


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the CLI parser.

    Separate from main() so tests can exercise parsing without running a
    download.
    """
    parser = argparse.ArgumentParser(
        prog="yt-downloader",
        description="Download YouTube videos and playlists via yt-dlp.",
    )
    parser.add_argument("url", nargs="?", help="YouTube URL (prompted for if omitted)")
    parser.add_argument(
        "-o",
        "--output-dir",
        default=None,
        help="Save folder (default: ./downloads)",
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="format_preset",
        default="best",
        choices=sorted(FORMAT_PRESETS),
        help="Quality preset (default: best)",
    )
    parser.add_argument("--subtitles", action="store_true", help="Download EN/AR subtitles")
    parser.add_argument("--sponsorblock", action="store_true", help="Strip sponsor segments")
    parser.add_argument("--playlist", action="store_true", help="Download the whole playlist")
    parser.add_argument(
        "--prefer-direct",
        dest="prefer_direct_formats",
        action="store_true",
        help="Prefer direct HTTP formats over segmented transports",
    )
    return parser


def _prompt(message: str, default: str = "") -> str:
    """Prompt on an interactive terminal; fall back to *default* otherwise.

    Guarding on isatty keeps piped and scripted invocations from dying with an
    uncaught EOFError.

    The isatty() call is inside the try because a *closed* stdin is still
    truthy, so the falsy check does not cover it and isatty() then raises
    ValueError. An embedding host that closes stdin before calling main()
    would otherwise get a traceback.
    """
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return default
        return input(message).strip() or default
    except (EOFError, ValueError, OSError):
        return default


def _make_stdout_lenient() -> None:
    """Stop an unencodable video title from killing the download.

    When stdout is redirected on Windows it falls back to the locale encoding
    (typically cp1252), so printing a CJK or emoji title raises
    UnicodeEncodeError and aborts a download that had otherwise succeeded.
    Degrading those characters to '?' is strictly better than crashing, and
    changing the encoding outright would produce mojibake in a real console.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):
                reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    _make_stdout_lenient()

    print("=" * 50)
    print("       YouTube Video Downloader (yt-dlp)")
    print("=" * 50)
    print(describe_ejs_status())

    url = (args.url or _prompt("\nPaste YouTube URL: ")).strip()
    if not url:
        print("No URL provided. Exiting.")
        sys.exit(1)

    if not is_valid_url(url):
        print("Error: That doesn't look like a YouTube URL.")
        sys.exit(1)

    if not has_ffmpeg():
        print(
            "Error: ffmpeg was not found on PATH.\n"
            "It is required to merge video+audio, extract MP3, and strip sponsor\n"
            "segments. Install it from https://ffmpeg.org/download.html and retry."
        )
        sys.exit(1)

    output_dir = args.output_dir or _prompt(
        "Save folder [press Enter for 'downloads']: ", "downloads"
    )

    try:
        download_video(
            url,
            output_dir,
            format_preset=args.format_preset,
            subtitles=args.subtitles,
            sponsorblock=args.sponsorblock,
            playlist=args.playlist,
            prefer_direct_formats=args.prefer_direct_formats,
        )
    except DownloadError as e:
        print(f"\nDownload error: {e}")
        sys.exit(1)
    except OSError as e:
        # Deliberately generic: URLError, TimeoutError and ConnectionResetError
        # are all OSError subclasses, so naming the output directory here would
        # send the user after the wrong problem. Disk failures arrive as
        # DownloadError from download_video's own makedirs guard.
        print(f"\nSystem error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        # 130 = terminated by SIGINT.  Exiting 0 here reported success for an
        # aborted download, which broke any script checking the status.
        print("\nCancelled by user.")
        sys.exit(130)


if __name__ == "__main__":
    main()
