"""Persistent configuration for the YouTube Downloader GUI."""

import contextlib
import json
import os
import sys
import tempfile
from typing import Any


def _data_dir() -> str:
    """Return the platform-appropriate user data directory for the app.

    Falls back to the script directory if the platform dir cannot be created.
    """
    if sys.platform == "win32":
        base = os.environ.get("APPDATA", "")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))

    if base:
        app_dir = os.path.join(base, "YT_Downloader")
        try:
            os.makedirs(app_dir, exist_ok=True)
            return app_dir
        except OSError:
            pass

    return _SCRIPT_DIR


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = _data_dir()
CONFIG_FILE = os.path.join(DATA_DIR, ".yt_config.json")

# Migrate from legacy location (next to source) if the new location is different
_LEGACY_CONFIG = os.path.join(_SCRIPT_DIR, ".yt_config.json")
if _SCRIPT_DIR != DATA_DIR and os.path.exists(_LEGACY_CONFIG) and not os.path.exists(CONFIG_FILE):
    try:
        import shutil

        shutil.copy2(_LEGACY_CONFIG, CONFIG_FILE)
    except OSError:
        pass

_DEFAULTS: dict[str, Any] = {
    "output_dir": os.path.join(os.path.expanduser("~"), "Downloads", "YouTube"),
    "format": "best",
    "subtitles": False,
    "sponsorblock": False,
    "playlist": False,
    "prefer_direct_formats": False,
}


def atomic_write_json(path: str, data: Any) -> None:
    """Write JSON to *path* atomically via temp file + os.replace()."""
    dir_name = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    fd_closed = False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            fd_closed = True  # os.fdopen took ownership; with-block will close
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        if not fd_closed:
            with contextlib.suppress(OSError):
                os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


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
        except Exception:  # noqa: S110 — fail-soft config load by design
            pass
    return cfg


def save_config(cfg: dict[str, Any]) -> bool:
    """Save config; return True on success, False on failure."""
    try:
        atomic_write_json(CONFIG_FILE, cfg)
        return True
    except Exception:
        return False
