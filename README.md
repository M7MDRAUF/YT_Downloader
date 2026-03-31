# YT Downloader

A clean, dark-themed desktop GUI for downloading YouTube videos and playlists — powered by [yt-dlp](https://github.com/yt-dlp/yt-dlp).

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
- [yt-dlp](https://github.com/yt-dlp/yt-dlp)

Optional:
- [Deno](https://deno.land/) — enables SABR protocol support for yt-dlp (auto-detected)

## Installation

```bash
git clone https://github.com/M7MDRAUF/YT_Downloader.git
cd YT_Downloader
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install yt-dlp
```

## Usage

### GUI

```bash
python gui.py
```

### CLI

```bash
python download.py [URL]
```

## Project Structure

```
YT_Downloader/
├── gui.py          # tkinter GUI — main application window
├── download.py     # yt-dlp wrapper, URL validation, CLI entry point
├── config.py       # Persistent JSON config (saves output dir, format, etc.)
├── .gitignore
├── LICENSE
└── README.md
```

## Configuration

Settings are auto-saved to `.yt_config.json` in the project directory on each download. The following options are persisted:

| Key           | Default                        | Description                        |
|---------------|--------------------------------|------------------------------------|
| `output_dir`  | `~/Downloads/YouTube`          | Where files are saved              |
| `format`      | `best`                         | Quality preset                     |
| `subtitles`   | `false`                        | Download subtitles                 |
| `sponsorblock`| `false`                        | Remove sponsor segments            |
| `playlist`    | `false`                        | Download full playlist             |

## License

[MIT](LICENSE)
