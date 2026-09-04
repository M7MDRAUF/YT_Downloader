# Contributing

Thanks for helping out. This is a small project, so the process is light.

## Setup

```bash
git clone https://github.com/M7MDRAUF/YT_Downloader.git
cd YT_Downloader
python -m venv .venv
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install
```

Activate the venv with `.venv\Scripts\activate` on Windows, or
`source .venv/bin/activate` elsewhere.

You also need `ffmpeg` on `PATH` for real downloads. `Pillow` (thumbnails) and
`deno` (JS runtime) are optional and **must stay optional** — code that assumes
either is present will be rejected.

## Before you open a PR

Everything CI runs, you can run locally.

```bash
python -m pytest tests/
```

```bash
python -m ruff check . && python -m ruff format --check .
```

```bash
python -m mypy config.py download.py gui.py tests
```

```bash
python -m bandit -c pyproject.toml -r . && python -m vulture
```

Coverage must not regress. The gate is 45% overall, with a separate 85% floor on
`download.py` and `config.py`.

Read the headline number with one caveat: `_build_ui` and `_apply_styles` are
marked `# pragma: no cover`, hiding ~92 statements of pure `pack()` wiring that
cannot run under the headless tkinter stub. Unexcluded, coverage is ~44% rather
than ~49%. Do not add new pragmas to make a number look better — extract the
logic and test it instead.

```bash
python -m pytest tests/ --cov=. --cov-report=term-missing --cov-fail-under=45
```

```bash
python -m coverage report --include="download.py,config.py" --fail-under=85
```

## Architecture rules

Module ownership is deliberate — please keep it.

- **`download.py`** owns everything yt-dlp: URL validation, cookie detection,
  format presets and labels, tool detection (`has_ffmpeg`), stream
  classification, and the canonical `build_ydl_opts()`. **When adding a download
  feature, extend `build_ydl_opts()`** rather than assembling a second options
  dict in the GUI.
- **`gui.py`** owns UI state, worker threads, and the history UI.
- **`config.py`** owns platform-specific data locations and atomic JSON writes.

## Threading

tkinter is main-thread only. Read widget state on the main thread *before*
starting a worker, and route every background-to-UI update through
`_safe_after()`. Preserve the `_cancel_event` checks and the progress and
postprocessor hooks so Cancel keeps working during ffmpeg post-processing.

Do not remove the `_track_child_processes()` context manager without an
equivalent cleanup path. It is what stops orphaned ffmpeg processes, and the
try/finally it replaced caused a bug that permanently disabled the app.

## Testing

The suite is offline and fast (~0.4s) and must stay that way. No network, and no
reading the developer's real browser cookie stores — `tests/conftest.py`
enforces the latter with an autouse fixture. If you need the genuine cookie
probe, use the `real_cookie_probe` fixture and supply your own fake `YoutubeDL`.

Do not test a copy of the logic. If something is hard to test because it is
buried in a widget-bound method, extract it to module scope and test the real
function. There was a class of tests here that asserted against a hand-pasted
duplicate of the implementation; it could never have caught a regression.

## Style

Built-in generics (`list[str]`), `|` unions, and explicit return types on every
function. Optional integrations must fail soft: a missing cookie store, a
missing Pillow, or a failed config write must never crash the app.
