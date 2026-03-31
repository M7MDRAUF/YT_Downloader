"""Persistent configuration for the YouTube Downloader GUI."""

import json
import os
from typing import Any

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".yt_config.json")

_DEFAULTS: dict[str, Any] = {
    "output_dir": os.path.join(os.path.expanduser("~"), "Downloads", "YouTube"),
    "format": "best",
    "subtitles": False,
    "sponsorblock": False,
    "playlist": False,
}


def load_config() -> dict[str, Any]:
    cfg = dict(_DEFAULTS)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored, dict):
                for key, default in _DEFAULTS.items():
                    if key in stored and isinstance(stored[key], type(default)):
                        cfg[key] = stored[key]
        except Exception:
            pass
    return cfg


def save_config(cfg: dict[str, Any]) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass
