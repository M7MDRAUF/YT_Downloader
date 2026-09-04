# Security Policy

## Supported versions

Only the latest release on `main` receives security fixes.

## Reporting a vulnerability

Please report security issues privately via
[GitHub Security Advisories](https://github.com/M7MDRAUF/YT_Downloader/security/advisories/new)
rather than opening a public issue. You should get an initial response within
seven days.

## Security-relevant behaviour you should know about

This app touches a few things worth understanding before you run it.

### It reads your browser cookie stores

To download age-restricted or region-limited videos, `get_cookies_browser()`
(`download.py`) asks yt-dlp to load cookies from your installed browsers, in
this order: Firefox, Chrome, Edge, Brave, Opera, Chromium, Vivaldi. The first
one that opens successfully is used.

Cookies are passed to yt-dlp in-process. This app never writes them to disk,
logs them, or transmits them anywhere except to YouTube as part of the download
request. If you would rather not use cookies at all, close your browsers or run
under a profile with no cookie database — the app degrades to unauthenticated
downloads and prints a warning.

The browser probe is skipped entirely under test: `tests/conftest.py` stubs it
out with an autouse fixture, so running the suite never opens your real cookie
stores.

### It can execute JavaScript fetched at runtime

Modern yt-dlp solves YouTube's n-signature and JSC challenges with JavaScript.
Normally those scripts come from the bundled `yt-dlp-ejs` package, installed via
the `yt-dlp[default]` extra in `requirements.txt`.

If that package is missing, `_default_remote_components()` (`download.py`) falls
back to `remote_components = ["ejs:github"]`, which makes yt-dlp **download and
execute solver JavaScript from the network at download time**. This is upstream
yt-dlp's documented design rather than something this project adds, but it is a
remote code execution surface and you should know it exists.

To avoid it, keep `yt-dlp[default]` installed. `describe_ejs_status()` reports
which mode you are in, and both the CLI banner and the GUI status bar show it at
startup.

### Thumbnail fetching is SSRF-guarded

Video thumbnails are fetched over HTTP from URLs supplied by yt-dlp metadata.
`_is_safe_url()` (`gui.py`) rejects non-HTTP(S) schemes, `localhost`, and
loopback, private, reserved and link-local IP literals. The response is capped
at 5 MB and the request times out after 5 seconds.

Known limitation: the check inspects the URL host literal and does **not**
resolve DNS, so a hostname resolving to a private address would pass. The
fetched bytes are only ever handed to Pillow for display; they are never
executed or written to disk.

### Downloaded filenames

Output filenames come from the video title via yt-dlp's `%(title)s` template and
rely on yt-dlp's own sanitisation. The output directory is taken verbatim from
the user and is never derived from remote content.
