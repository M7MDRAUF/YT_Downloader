# YT Downloader

A clean, dark-themed desktop GUI for downloading YouTube videos and playlists — powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp).

[![CI](https://github.com/M7MDRAUF/YT_Downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/M7MDRAUF/YT_Downloader/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![License](https://img.shields.io/badge/License-MIT-green)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)

## Features

- **Multiple quality presets** — Best, 1080p, 720p, 480p, or Audio-only (MP3)
- **Playlist support** — Download full playlists or single videos
- **SponsorBlock integration** — Auto-remove sponsor segments, self-promos, and interaction reminders
- **Subtitles** — Download English and Arabic subtitles (SRT format)
- **Cookie-based auth** — Automatically reads cookies from your browser (Firefox, Chrome, Edge, etc.)
- **Download history** — Tracks your last 50 downloads with status
- **Persistent settings** — Remembers your last output folder and options
- **Progress tracking** — Real-time progress bar, speed, and ETA
- **Cancel support** — Stop any download mid-way cleanly

## Requirements

- Python 3.11+
- [ffmpeg](https://ffmpeg.org/download.html) — required for video/audio merging and MP3 conversion
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) **with the `[default]` extra** — installs `yt-dlp-ejs`, the EJS challenge solver scripts required by modern YouTube extractors. Without it, downloads fail with *"No video formats found"*.

Optional:
- [Deno](https://deno.land/) — JavaScript runtime that runs the EJS solver scripts. Auto-detected on `PATH` (and the WinGet shim on Windows). If `deno` is missing, the app falls back to enabling `--remote-components ejs:github` so yt-dlp can still solve the challenges using GitHub-hosted scripts.

## Installation

```bash
git clone https://github.com/M7MDRAUF/YT_Downloader.git
cd YT_Downloader
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### Development Setup

```bash
pip install -r requirements-dev.txt
```

### Quality Tools

```bash
ruff check .              # Lint
ruff format .             # Format
mypy config.py download.py gui.py  # Type check
pytest tests/             # Tests
pytest tests/ --cov=.     # Tests with coverage
bandit -r . --exclude ./.venv -c pyproject.toml  # Security scan
pip-audit                 # Dependency vulnerabilities
vulture config.py download.py gui.py  # Dead code
```

## Usage

### GUI

```bash
python gui.py
```

### CLI

```bash
python download.py "https://youtu.be/VIDEO_ID"
```

Fully scriptable — it prompts only for values you omit, and only when attached
to a terminal, so piped and non-interactive use works:

```bash
python download.py "https://youtu.be/VIDEO_ID" -o ~/Videos -f 1080p --subtitles
```

| Flag | Description |
|------|-------------|
| `-o`, `--output-dir` | Save folder (default: `./downloads`) |
| `-f`, `--format` | `best`, `1080p`, `720p`, `480p`, `audio` (default: `best`) |
| `--subtitles` | Download EN/AR subtitles |
| `--sponsorblock` | Strip sponsor segments |
| `--playlist` | Download the whole playlist |
| `--prefer-direct` | Prefer direct HTTP formats over segmented transports |

Exit codes: `0` success, `1` error, `130` cancelled with Ctrl-C.

### Installed commands

```bash
pip install .
```

This provides `yt-downloader` (CLI) and `yt-downloader-gui` (GUI).

## Project Structure

```
YT_Downloader/
├── gui.py              # tkinter GUI — main application window
├── download.py         # yt-dlp wrapper, URL validation, CLI entry point
├── config.py           # Persistent JSON config (saves output dir, format, etc.)
├── tests/              # Pytest test suite
│   ├── conftest.py     # Shared fixtures; keeps the suite offline and hermetic
│   ├── test_config.py
│   ├── test_download.py
│   └── test_gui.py
├── .github/
│   ├── workflows/ci.yml    # Lint, types, tests, coverage, packaging
│   ├── dependabot.yml
│   └── copilot-instructions.md
├── pyproject.toml      # Project metadata + tool configs (ruff, mypy, pytest, etc.)
├── requirements.txt    # Core runtime dependencies
├── requirements-dev.txt# Dev/QA tool dependencies
├── .pre-commit-config.yaml
├── .gitignore
├── CHANGELOG.md
├── CONTRIBUTING.md
├── SECURITY.md
├── LICENSE
└── README.md
```

## Configuration

Settings are auto-saved to `.yt_config.json` under the app's platform-specific data directory on each download. On Windows this is typically `%APPDATA%\YT_Downloader`. The following options are persisted:

| Key           | Default                        | Description                        |
|---------------|--------------------------------|------------------------------------|
| `output_dir`  | `~/Downloads/YouTube`          | Where files are saved              |
| `format`      | `best`                         | Quality preset                     |
| `subtitles`   | `false`                        | Download subtitles                 |
| `sponsorblock`| `false`                        | Remove sponsor segments            |
| `playlist`    | `false`                        | Download full playlist             |
| `prefer_direct_formats` | `false`              | Prefer direct HTTP formats when available |

Download history is kept separately in `.yt_history.json` in the same directory,
capped at the 50 most recent entries. Both files are migrated automatically from
the older location beside the source files, if one exists.

## Security notes

This app reads your browser cookie stores to authenticate downloads, and — when
the bundled `yt-dlp-ejs` solver is missing — yt-dlp will fetch and execute
challenge-solving JavaScript from the network at download time. Neither is
unusual for a yt-dlp front end, but both are worth understanding. See
[SECURITY.md](SECURITY.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). All checks in
[the CI workflow](.github/workflows/ci.yml) must pass, and coverage must not
regress.

## License

[MIT](LICENSE)
