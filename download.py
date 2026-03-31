import re
import shutil
import sys
import os
from typing import Any

import yt_dlp
from yt_dlp.utils import DownloadError

# ---------------------------------------------------------------------------
# Constants — single source of truth for ydl options
# ---------------------------------------------------------------------------

# Firefox first: Chrome triggers noisy DPAPI errors on Windows even when it
# ultimately falls back.  Putting Firefox first avoids those spurious ERRORs.
_BROWSERS: list[str] = ["firefox", "chrome", "edge", "brave", "opera", "chromium", "vivaldi"]

_YT_URL_RE = re.compile(
    r"^https?://((www\.|music\.)?youtube\.com/(watch\?|shorts/|embed/|live/|playlist\?)|youtu\.be/)",
)


def _find_deno() -> str | None:
    """Find the deno binary, checking PATH and common Windows install locations."""
    found = shutil.which("deno")
    if found:
        return found
    if sys.platform == "win32":
        # Winget shim may not be on PATH in all terminal contexts (e.g. VS Code bg shells)
        winget_shim = os.path.expandvars(
            r"%LOCALAPPDATA%\Microsoft\WinGet\Links\deno.EXE"
        )
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
    """Return the first browser whose cookie store is accessible, or None."""
    for browser in _BROWSERS:
        try:
            with yt_dlp.YoutubeDL({"cookiesfrombrowser": (browser,), "quiet": True, "no_warnings": True}) as ydl:
                ydl.cookiejar  # triggers cookie load
            return browser
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Format presets — maps user-friendly names to yt-dlp format strings
# ---------------------------------------------------------------------------
FORMAT_PRESETS: dict[str, str] = {
    "best":    "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    "1080p":   "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best",
    "720p":    "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best",
    "480p":    "bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best",
    "audio":   "bestaudio[ext=m4a]/bestaudio",
}


def build_ydl_opts(
    output_dir: str = "downloads",
    progress_hooks: list[Any] | None = None,
    quiet: bool = False,
    format_preset: str = "best",
    subtitles: bool = False,
    sponsorblock: bool = False,
    playlist: bool = False,
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
        "progress_hooks": progress_hooks if progress_hooks is not None else [_cli_progress_hook],
        # Force the "main" player JS variant so the challenge solver can parse it.
        # The "tv" variant (tv-player-ias.js) currently breaks the solver.
        "extractor_args": {"youtube": {"player_js_variant": ["main"]}},
        # Let yt-dlp pick default clients (SABR branch handles SABR protocol
        # natively, so all clients including 'web' work properly now).
        "ignore_no_formats_error": True,
    }
    # Only configure Deno JS runtime when the binary is present (SABR-fork feature)
    if deno_path:
        opts["js_runtimes"] = {"deno": {"path": deno_path}}
    if not is_audio:
        opts["merge_output_format"] = "mp4"

    # Subtitles
    if subtitles:
        opts["writesubtitles"] = True
        opts["writeautomaticsub"] = True
        opts["subtitleslangs"] = ["en", "ar"]
        opts["subtitlesformat"] = "srt/best"

    # SponsorBlock must run BEFORE FFmpegExtractAudio so chapters exist in the video stream
    if sponsorblock:
        opts.setdefault("postprocessors", []).append({"key": "SponsorBlock"})
        opts.setdefault("postprocessors", []).append({
            "key": "ModifyChapters",
            "remove_sponsor_segments": ["sponsor", "selfpromo", "interaction"],
        })

    # Audio-only: FFmpegExtractAudio must be LAST postprocessor
    if is_audio:
        opts.setdefault("postprocessors", []).append({
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        })

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
    return str(getattr(yt_dlp, "__version__", "unknown"))


def extract_info_only(url: str, **ydl_kwargs: Any) -> dict[str, Any]:
    """Fetch video/playlist metadata without downloading.

    Accepts the same keyword arguments as build_ydl_opts.
    """
    opts = build_ydl_opts(quiet=True, **ydl_kwargs)
    with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
        raw = ydl.extract_info(url, download=False)
        return dict(raw) if raw else {}


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

        ydl.process_ie_result(raw_info, download=True)  # reuse extracted info, skip 2nd fetch

    print("\nDownload complete!")


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def _cli_progress_hook(d: dict[str, Any]) -> None:
    if d["status"] == "downloading":
        percent: str = str(d.get("_percent_str", "?%")).strip()
        speed: str   = str(d.get("_speed_str",   "?")).strip()
        eta: str     = str(d.get("_eta_str",      "?")).strip()
        print(f"\r  {percent}  |  Speed: {speed}  |  ETA: {eta}   ", end="", flush=True)
    elif d["status"] == "finished":
        print(f"\r  Merging / post-processing...                        ", end="", flush=True)


# Keep legacy name so existing gui.py references don't break during transition
progress_hook = _cli_progress_hook


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
