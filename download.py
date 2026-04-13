import functools
import os
import re
import shutil
import sys
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

    opts: dict[str, Any] = {
        "format": fmt,
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "noplaylist": not playlist,
        # Safety: cap playlist entries to avoid hanging on infinite playlists
        # (e.g. YouTube Mix/Radio with list=RD…). Process lazily so yt-dlp
        # yields entries as they arrive instead of waiting for full enumeration.
        **({
            "playlistend": _DEFAULT_PLAYLIST_LIMIT,
            "lazy_playlist": True,
        } if playlist else {}),
        "progress_hooks": progress_hooks if progress_hooks is not None else [_cli_progress_hook],
        "postprocessor_hooks": postprocessor_hooks or [],
        # Keep yt-dlp on the default "main" player JS variant, but do not
        # force YouTube into the segmented "dashy" transport. Forcing dashy
        # makes even plain HTTPS formats download via http_dash_segments,
        # which can throttle much harder than direct HTTPS on some CDNs.
        "extractor_args": {"youtube": {"player_js_variant": ["main"]}},
        # Let yt-dlp pick default clients (SABR branch handles SABR protocol
        # natively, so all clients including 'web' work properly now).
        "ignore_no_formats_error": True,
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


def download_video(url: str, output_dir: str = "downloads") -> None:
    """Download a YouTube video to *output_dir*."""
    os.makedirs(output_dir, exist_ok=True)

    ydl_opts = build_ydl_opts(output_dir)

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

        if info.get("_type") in ("playlist", "multi_video"):
            # Playlist: use download() for full entry handling
            ydl.download([url])
        else:
            # Single video: reuse the already-extracted info so yt-dlp
            # does not re-fetch the YouTube page a second time.
            ydl.process_info(info)  # type: ignore[arg-type]

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


def main() -> None:
    print("=" * 50)
    print("       YouTube Video Downloader (yt-dlp)")
    print("=" * 50)

    if len(sys.argv) > 1:
        url = sys.argv[1].strip()
    else:
        url = input("\nPaste YouTube URL: ").strip()

    if not url:
        print("No URL provided. Exiting.")
        sys.exit(1)

    if not is_valid_url(url):
        print("Error: That doesn't look like a YouTube URL.")
        sys.exit(1)

    output_dir = input("Save folder [press Enter for 'downloads']: ").strip() or "downloads"

    try:
        download_video(url, output_dir)
    except DownloadError as e:
        print(f"\nDownload error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nCancelled by user.")
        sys.exit(0)


if __name__ == "__main__":
    main()
