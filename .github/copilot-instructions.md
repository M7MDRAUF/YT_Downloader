# Project Guidelines

## Architecture
- This workspace is a small Python 3.11+ desktop app with two entry points: [gui.py](../gui.py) for the tkinter app and [download.py](../download.py) for CLI downloads.
- Keep module responsibilities stable: [download.py](../download.py) owns URL validation, browser cookie detection, format presets, and the canonical `build_ydl_opts()` implementation; [gui.py](../gui.py) owns UI state, worker-thread orchestration, history UI, and single-instance behavior; [config.py](../config.py) owns platform-aware data locations and atomic JSON writes.
- When adding download features, extend `build_ydl_opts()` instead of building a second yt-dlp options dict in the GUI.

## Build And Run
- Use Python 3.11+.
- Follow setup and usage in [README.md](../README.md).
- Run the GUI with `python gui.py`.
- Run the CLI with `python download.py <url>`.
- Quality toolchain (all configured in `pyproject.toml`, all must stay green):
  - `pytest tests/` — unit tests; `pytest tests/ --cov=. --cov-report=term-missing` for coverage.
  - `ruff check .` and `ruff format --check .` — lint and formatting.
  - `mypy config.py download.py gui.py` — type checking.
  - `bandit -c pyproject.toml -r .`, `vulture`, `pip-audit` — security and dead code.
- CI runs these on every push and PR to `main` (`.github/workflows/ci.yml`).
- Real downloads require `ffmpeg` on `PATH`. `Pillow` and `deno` are optional and must remain optional.

## Conventions
- Match the existing typing style: built-in generics, `|` unions, and explicit return types.
- Keep platform-specific filesystem and OS behavior in helper functions instead of scattering conditionals through call sites.
- Persist settings and history through the existing helpers. Current code stores user data under `config.DATA_DIR` and `HISTORY_FILE`, with legacy migration from the repo directory. Prefer the code over the README for persistence-path details.
- Keep optional integrations fail-soft: missing browser cookies, missing Pillow, and config/history write failures should not crash the app.

## Tkinter And Threading
- Treat tkinter as main-thread only. Read widget state on the main thread before starting worker threads, and route background-thread UI updates through `_safe_after()` in [gui.py](../gui.py).
- Preserve cancellation behavior based on `_cancel_event`, progress hooks, and postprocessor hooks so cancel works during both download and ffmpeg post-processing.
- Do not remove the `subprocess.Popen` tracking and restore logic in `_download_thread()` without an equivalent cleanup path; it prevents orphan ffmpeg processes when cancelling or closing the app.

## Safety Checks
- Keep `_is_safe_url()` protections around thumbnail fetching in [gui.py](../gui.py); do not relax the localhost/private-address guard.
- Keep the Firefox-first browser probing order in [download.py](../download.py); it avoids noisy Chrome/DPAPI issues on Windows.
- Keep the single-instance lock in [gui.py](../gui.py) unless the task explicitly changes the process model.