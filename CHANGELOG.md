# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **The app could become permanently unusable.** `_download_thread` bound the
  original `subprocess.Popen.__init__` *inside* the `try` block whose `finally`
  restored it, after `os.makedirs` had already run. Any invalid output path
  raised before the binding, so the `finally` itself raised `UnboundLocalError`
  and the worker died before re-enabling the UI. The Download button stayed
  greyed out, every later click returned early, and closing the window took five
  seconds. Replaced with a `_track_child_processes()` context manager that makes
  bind and restore structurally inseparable.
- Exporting history to a read-only location raised out of the Tk callback with
  no visible error, and no stderr at all under `pythonw`.
- Orphaned ffmpeg processes: `_child_procs` was mutated from yt-dlp's worker
  thread while the main thread did `list()` then `clear()`, losing anything
  registered between the two statements. Now lock-guarded and drained
  atomically.
- `_safe_after` suppressed bare `Exception`, hiding genuine Tcl threading
  errors. It now suppresses only `RuntimeError` and `TclError`.
- The CLI could not be used non-interactively: it prompted for a save folder via
  `input()` even when the URL came from `argv`, dying with `EOFError` when piped.
- The CLI exited `0` on Ctrl-C, reporting success for an aborted download. It now
  exits `130`.
- Neither `pip install .` nor either console script worked. `pyproject.toml` had
  no `[build-system]`, setuptools could not auto-discover the flat layout, and
  `yt-downloader-gui` pointed at a `gui:main` that did not exist.
- Removed an unreachable `describe_ejs_status()` branch — the one carrying the
  actionable "run `pip install -U yt-dlp[default]`" advice.
- README documented `prefer_direct_formats` as defaulting to `true`; it is
  `false`.
- The thumbnail fetch timeout of 10s blocked Cancel for that whole window; now
  5s.
- `_prompt` raised `ValueError` on a closed stdin: a closed file object is still
  truthy, so the falsy guard missed it and `isatty()` blew up. An embedding host
  that closed stdin before calling `main()` got a traceback rather than a clean
  fallback.
- A network failure was reported as a disk failure. `URLError`, `TimeoutError`
  and `ConnectionResetError` are all `OSError` subclasses, so the CLI's handler
  printed "Cannot write to '<dir>'" for a dropped connection, sending users
  after the wrong problem. Disk failures now surface as `DownloadError` from
  `download_video`'s own guard, and the `OSError` message is generic.
- A video title containing non-Latin-1 characters (CJK, Arabic, emoji) crashed
  the CLI with `UnicodeEncodeError` whenever stdout was redirected, aborting a
  download that had already succeeded. Output streams are now reconfigured with
  `errors="replace"`. This matters more now that the CLI is scriptable.

### Added

- **CLI flags**: `-o/--output-dir`, `-f/--format`, `--subtitles`,
  `--sponsorblock`, `--playlist`, `--prefer-direct`. The CLI was previously
  hardwired to defaults and none of these features were reachable from it.
- `has_ffmpeg()` preflight in both front ends. The CLI previously downloaded both
  streams in full before failing in postprocessing.
- `CONTRIBUTING.md`, `SECURITY.md`, this changelog, a Dependabot config, and a
  pre-commit config.
- A CI `packaging` job that runs `pip install .` and `yt-downloader --help`.

### Changed

- **CI now actually runs.** `.gitignore` excluded `.github/` entirely, so the
  workflow had never been committed and had never executed once. Only
  `.github/instructions/` (vendor boilerplate) remains ignored.
- `.github/copilot-instructions.md` claimed the repo defined no tests, lint,
  format or CI commands and told agents not to invent any. That was false, and it
  is why the toolchain was invisible to automated contributors.
- CI split into `quality` / `test` / `packaging` / `audit` jobs. The suite no
  longer runs twice, pip is cached, `ruff format`, `bandit` and `vulture` now
  actually run, and `pip-audit` moved to a weekly schedule so an unrelated PR
  cannot be reddened by a fresh yt-dlp CVE.
- Test matrix now includes Python 3.14, the version the project is developed on.
- **Tests no longer read your browser cookie databases.** `build_ydl_opts()`
  reaches `get_cookies_browser()`, and 25 tests called it with nothing mocking it.
  Suite runtime dropped from 0.59s to ~0.35s as a side effect.
- Coverage 32% to 47%; `download.py` 62% to 97%; `config.py` 73% to 89%. Gate
  raised from 35 to 45, with a new 85% floor on `download.py` and `config.py` so
  the blended number cannot let the core hide behind untestable GUI code.
- Format labels, stream classification, and the extract-then-download flow are
  now single-sourced in `download.py`. The GUI and CLI copies had already drifted
  apart.
- `tests/test_gui.py` tested a hand-copied duplicate of the stream-type logic
  rather than the real function. It now tests the real one.
- `yt-downloader-gui` is a `gui-script`, so Windows no longer opens a console
  window behind the app. The instance lock file is released and removed on exit
  instead of being left behind in `%APPDATA%`.

## [1.0.0]

Initial release: dark-themed tkinter GUI over yt-dlp, quality presets, playlist
support, SponsorBlock, EN/AR subtitles, browser-cookie auth, download history,
and a minimal CLI.
