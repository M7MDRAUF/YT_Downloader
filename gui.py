import re
import sys
import os
import csv
import io
import ipaddress
import shutil
import json
import time
import threading
import subprocess
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen, Request

import yt_dlp

from download import (
    DownloadError,
    build_ydl_opts,
    is_valid_url,
    get_ydl_version,
)
from config import load_config, save_config, DATA_DIR, atomic_write_json

_has_pil = False
try:
    from PIL import Image, ImageTk  # type: ignore[import-untyped]

    _has_pil = True
except ImportError:
    pass

# yt-dlp embeds ANSI color codes in _percent_str, _speed_str, _eta_str.
# Tkinter cannot render them — they show as squares.  Strip them.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BG = "#0d1117"
BG_CARD = "#161b22"
BG_INPUT = "#21262d"
ACCENT = "#e94560"
ACCENT_DARK = "#c73652"
ACCENT_GLOW = "#ff6b84"
TXT_PRIMARY = "#f0f6fc"
TXT_MUTED = "#8b949e"
TXT_SUCCESS = "#3fb950"
TXT_ERROR = "#f85149"
TXT_WARN = "#d29922"
BORDER = "#30363d"


def _ui_font() -> str:
    """Return a platform-appropriate sans-serif font family."""
    if sys.platform == "win32":
        return "Segoe UI"
    if sys.platform == "darwin":
        return "Helvetica Neue"
    return "Helvetica"


_FONT = _ui_font()
FONT_TITLE = (_FONT, 20, "bold")
FONT_SUB = (_FONT, 11)
FONT_LABEL = (_FONT, 11, "bold")
FONT_INPUT = (_FONT, 12)
FONT_BTN = (_FONT, 12, "bold")
FONT_SMALL = (_FONT, 10)
FONT_HIST = (_FONT, 10)

HISTORY_FILE = os.path.join(DATA_DIR, ".yt_history.json")

# Migrate from legacy location (next to source) if different
_LEGACY_HISTORY = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), ".yt_history.json"
)
if DATA_DIR != os.path.dirname(os.path.abspath(__file__)):
    if os.path.exists(_LEGACY_HISTORY) and not os.path.exists(HISTORY_FILE):
        try:
            shutil.copy2(_LEGACY_HISTORY, HISTORY_FILE)
        except OSError:
            pass

FORMAT_LABELS: dict[str, str] = {
    "Best Quality": "best",
    "1080p": "1080p",
    "720p": "720p",
    "480p": "480p",
    "Audio Only (MP3)": "audio",
}
_LABEL_BY_KEY: dict[str, str] = {v: k for k, v in FORMAT_LABELS.items()}

_MAX_THUMB_BYTES = 5 * 1024 * 1024  # 5 MB safety limit for thumbnail downloads

_UNSAFE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def _is_safe_url(url: str) -> bool:
    """Return True if *url* uses http(s) and does not target localhost/private."""
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname or ""
        if hostname in _UNSAFE_HOSTS:
            return False
        # Check for private/reserved IP ranges (SSRF protection)
        try:
            addr = ipaddress.ip_address(hostname)
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_reserved
                or addr.is_link_local
            ):
                return False
        except ValueError:
            pass  # Not an IP literal — hostname is fine
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_HISTORY_KEYS = {"time", "title", "path", "status"}


def load_history() -> list[dict[str, str]]:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                data: Any = json.load(f)
            if isinstance(data, list):
                result: list[dict[str, str]] = []
                for entry in data:  # pyright: ignore[reportUnknownVariableType]
                    if (
                        isinstance(entry, dict)  # pyright: ignore[reportUnnecessaryIsInstance]
                        and _HISTORY_KEYS.issubset(entry.keys())  # pyright: ignore[reportUnknownArgumentType]
                        and all(isinstance(entry[k], str) for k in _HISTORY_KEYS)
                    ):
                        result.append(entry)  # pyright: ignore[reportUnknownArgumentType]
                return result
        except Exception:
            pass
    return []


def save_history(history: list[dict[str, str]]) -> bool:
    """Save history; return True on success, False on failure."""
    try:
        atomic_write_json(HISTORY_FILE, history[-50:])
        return True
    except Exception:
        return False


def _make_card(parent: tk.Misc) -> tuple[tk.Frame, tk.Frame]:
    """Bordered card: returns (outer_border_frame, inner_content_frame)."""
    outer = tk.Frame(parent, bg=BORDER, bd=0)
    inner = tk.Frame(outer, bg=BG_CARD, bd=0)
    inner.pack(padx=1, pady=1, fill="both", expand=True)
    return outer, inner


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------
class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("YouTube Downloader")
        self.configure(bg=BG)
        self.resizable(True, True)
        self.minsize(600, 500)
        self._download_active = False
        self._cancel_event = threading.Event()
        self._history: list[dict[str, str]] = load_history()
        self._last_title: str = ""
        self._thumb_photo: Any = None  # prevent GC of PhotoImage

        self._queue_total: int = 0
        self._progress_determinate: bool = False
        self._close_retries: int = 0
        self._child_procs: set[subprocess.Popen[bytes]] = set()

        self._cfg = load_config()
        self._apply_styles()
        self._build_ui()
        self._populate_from_config()
        self._center()

        self.bind(
            "<Return>",
            lambda e: (
                None
                if isinstance(e.widget, (tk.Text, tk.Entry, ttk.Entry, ttk.Combobox))
                else self._start_download()
            ),
        )
        self.protocol("WM_DELETE_WINDOW", self._on_closing)
        threading.Thread(target=self._fetch_version, daemon=True).start()

    # ------------------------------------------------------------------
    # TTK styles
    # ------------------------------------------------------------------
    def _apply_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=BG_INPUT,
            background=ACCENT,
            bordercolor=BG_INPUT,
            lightcolor=ACCENT,
            darkcolor=ACCENT_DARK,
            thickness=6,
        )
        style.configure(
            "Dark.TCombobox",
            fieldbackground=BG_INPUT,
            background=BG_INPUT,
            foreground=TXT_PRIMARY,
            arrowcolor=TXT_MUTED,
            selectbackground=BG_INPUT,
            selectforeground=TXT_PRIMARY,
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", BG_INPUT)],
            selectbackground=[("readonly", BG_INPUT)],
            selectforeground=[("readonly", TXT_PRIMARY)],
        )

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        PAD = 20

        # ── Header ────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=PAD, pady=(PAD, 6))

        tk.Frame(hdr, bg=ACCENT, width=4).pack(side="left", fill="y", padx=(0, 10))

        title_col = tk.Frame(hdr, bg=BG)
        title_col.pack(side="left")
        tk.Label(
            title_col, text="YouTube Downloader", bg=BG, fg=TXT_PRIMARY, font=FONT_TITLE
        ).pack(anchor="w")
        self.subtitle_var = tk.StringVar(
            value="Paste a URL, press Enter or click Download"
        )
        tk.Label(
            title_col,
            textvariable=self.subtitle_var,
            bg=BG,
            fg=TXT_MUTED,
            font=FONT_SUB,
        ).pack(anchor="w")

        # ── URL card (multi-line Text) ────────────────────────────────
        outer, card = _make_card(self)
        outer.pack(fill="x", padx=PAD, pady=(10, 0))

        tk.Label(
            card,
            text="YouTube URL(s) \u2014 one per line",
            bg=BG_CARD,
            fg=TXT_MUTED,
            font=FONT_LABEL,
        ).pack(anchor="w", padx=14, pady=(12, 2))

        url_row = tk.Frame(card, bg=BG_CARD)
        url_row.pack(fill="x", padx=14, pady=(0, 12))

        self.url_text = tk.Text(
            url_row,
            bg=BG_INPUT,
            fg=TXT_PRIMARY,
            insertbackground=TXT_PRIMARY,
            relief="flat",
            font=FONT_INPUT,
            bd=0,
            height=3,
            wrap="word",
            undo=True,
        )
        self.url_text.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))
        self.url_text.bind("<FocusIn>", self._auto_paste)

        tk.Button(
            url_row,
            text="Paste",
            bg=BG_INPUT,
            fg=TXT_MUTED,
            activebackground=BORDER,
            activeforeground=TXT_PRIMARY,
            relief="flat",
            font=FONT_SMALL,
            cursor="hand2",
            command=self._paste_url,
            padx=10,
        ).pack(side="left", ipady=8, anchor="n")

        # ── Save folder card ──────────────────────────────────────────
        outer2, card2 = _make_card(self)
        outer2.pack(fill="x", padx=PAD, pady=(10, 0))

        tk.Label(
            card2, text="Save Folder", bg=BG_CARD, fg=TXT_MUTED, font=FONT_LABEL
        ).pack(anchor="w", padx=14, pady=(12, 2))

        dir_row = tk.Frame(card2, bg=BG_CARD)
        dir_row.pack(fill="x", padx=14, pady=(0, 12))

        self.dir_var = tk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "Downloads", "YouTube")
        )
        tk.Entry(
            dir_row,
            textvariable=self.dir_var,
            bg=BG_INPUT,
            fg=TXT_PRIMARY,
            insertbackground=TXT_PRIMARY,
            relief="flat",
            font=FONT_INPUT,
            bd=0,
        ).pack(side="left", fill="x", expand=True, ipady=7, padx=(0, 8))

        tk.Button(
            dir_row,
            text="Browse",
            bg=BG_INPUT,
            fg=TXT_MUTED,
            activebackground=BORDER,
            activeforeground=TXT_PRIMARY,
            relief="flat",
            font=FONT_SMALL,
            cursor="hand2",
            command=self._browse_folder,
            padx=10,
        ).pack(side="left", ipady=7)

        # ── Options card ──────────────────────────────────────────────
        outer_opt, card_opt = _make_card(self)
        outer_opt.pack(fill="x", padx=PAD, pady=(10, 0))

        tk.Label(
            card_opt, text="Options", bg=BG_CARD, fg=TXT_MUTED, font=FONT_LABEL
        ).pack(anchor="w", padx=14, pady=(12, 2))

        opts_inner = tk.Frame(card_opt, bg=BG_CARD)
        opts_inner.pack(fill="x", padx=14, pady=(0, 12))

        # Format selector
        fmt_row = tk.Frame(opts_inner, bg=BG_CARD)
        fmt_row.pack(fill="x", pady=(0, 6))

        tk.Label(
            fmt_row, text="Format:", bg=BG_CARD, fg=TXT_MUTED, font=FONT_SMALL
        ).pack(side="left", padx=(0, 8))

        self.format_var = tk.StringVar(value="Best Quality")
        self.format_combo = ttk.Combobox(
            fmt_row,
            textvariable=self.format_var,
            values=list(FORMAT_LABELS.keys()),
            state="readonly",
            width=20,
            style="Dark.TCombobox",
        )
        self.format_combo.pack(side="left")

        # Checkboxes
        chk_row = tk.Frame(opts_inner, bg=BG_CARD)
        chk_row.pack(fill="x")

        self.sub_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            chk_row,
            text="Download Subtitles (en, ar)",
            variable=self.sub_var,
            bg=BG_CARD,
            fg=TXT_MUTED,
            selectcolor=BG_INPUT,
            activebackground=BG_CARD,
            activeforeground=TXT_PRIMARY,
            font=FONT_SMALL,
        ).pack(side="left", padx=(0, 16))

        self.sponsor_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            chk_row,
            text="Remove Sponsors (SponsorBlock)",
            variable=self.sponsor_var,
            bg=BG_CARD,
            fg=TXT_MUTED,
            selectcolor=BG_INPUT,
            activebackground=BG_CARD,
            activeforeground=TXT_PRIMARY,
            font=FONT_SMALL,
        ).pack(side="left", padx=(0, 16))

        self.playlist_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            chk_row,
            text="Download Playlist",
            variable=self.playlist_var,
            bg=BG_CARD,
            fg=TXT_MUTED,
            selectcolor=BG_INPUT,
            activebackground=BG_CARD,
            activeforeground=TXT_PRIMARY,
            font=FONT_SMALL,
        ).pack(side="left")

        # ── Thumbnail preview (hidden initially) ──────────────────────
        self.thumb_frame = tk.Frame(self, bg=BG)
        self.thumb_label = tk.Label(self.thumb_frame, bg=BG)
        self.thumb_label.pack(side="left", padx=(0, 12))
        self.thumb_title_lbl = tk.Label(
            self.thumb_frame,
            bg=BG,
            fg=TXT_PRIMARY,
            font=FONT_SMALL,
            wraplength=350,
            anchor="w",
            justify="left",
        )
        self.thumb_title_lbl.pack(side="left", fill="x", expand=True, anchor="w")

        # ── Progress bar ──────────────────────────────────────────────
        self.progress = ttk.Progressbar(
            self,
            style="Accent.Horizontal.TProgressbar",
            mode="indeterminate",
        )
        self.progress.pack(fill="x", padx=PAD, pady=(14, 0))

        # ── Speed / ETA row (hidden initially) ────────────────────────
        self.speed_eta_frame = tk.Frame(self, bg=BG)
        self.speed_lbl = tk.Label(
            self.speed_eta_frame,
            text="",
            bg=BG,
            fg=TXT_MUTED,
            font=FONT_SMALL,
            anchor="w",
        )
        self.speed_lbl.pack(side="left")
        self.eta_lbl = tk.Label(
            self.speed_eta_frame,
            text="",
            bg=BG,
            fg=TXT_MUTED,
            font=FONT_SMALL,
            anchor="e",
        )
        self.eta_lbl.pack(side="right")

        # ── Status label ──────────────────────────────────────────────
        self.status_var = tk.StringVar(value="Ready \u2014 paste a URL above")
        self.status_lbl = tk.Label(
            self,
            textvariable=self.status_var,
            bg=BG,
            fg=TXT_MUTED,
            font=FONT_SMALL,
            wraplength=580,
            anchor="w",
            justify="left",
        )
        self.status_lbl.pack(fill="x", padx=PAD, pady=(6, 0))

        # ── Buttons row ───────────────────────────────────────────────
        btn_row = tk.Frame(self, bg=BG)
        btn_row.pack(fill="x", padx=PAD, pady=(12, 0))

        self.btn = tk.Button(
            btn_row,
            text="Download",
            bg=ACCENT,
            fg="white",
            activebackground=ACCENT_DARK,
            activeforeground="white",
            relief="flat",
            font=FONT_BTN,
            cursor="hand2",
            bd=0,
            command=self._start_download,
        )
        self.btn.pack(side="left", ipadx=24, ipady=10)
        self.btn.bind(
            "<Enter>",
            lambda e: (
                self.btn.config(bg=ACCENT_GLOW)
                if str(self.btn["state"]) != "disabled"
                else None
            ),
        )
        self.btn.bind(
            "<Leave>",
            lambda e: (
                self.btn.config(bg=ACCENT)
                if str(self.btn["state"]) != "disabled"
                else None
            ),
        )

        self.open_btn = tk.Button(
            btn_row,
            text="Open Folder",
            bg=BG_CARD,
            fg=TXT_MUTED,
            activebackground=BORDER,
            activeforeground=TXT_PRIMARY,
            relief="flat",
            font=FONT_BTN,
            cursor="hand2",
            bd=0,
            command=self._open_folder,
        )

        self.copy_title_btn = tk.Button(
            btn_row,
            text="Copy Title",
            bg=BG_CARD,
            fg=TXT_MUTED,
            activebackground=BORDER,
            activeforeground=TXT_PRIMARY,
            relief="flat",
            font=FONT_BTN,
            cursor="hand2",
            bd=0,
            command=self._copy_title,
        )

        self.cancel_btn = tk.Button(
            btn_row,
            text="Cancel",
            bg=BG_CARD,
            fg=TXT_ERROR,
            activebackground=BORDER,
            activeforeground=TXT_ERROR,
            relief="flat",
            font=FONT_BTN,
            cursor="hand2",
            bd=0,
            command=self._cancel_download,
        )

        # ── History panel ─────────────────────────────────────────────
        hist_hdr = tk.Frame(self, bg=BG)
        hist_hdr.pack(fill="x", padx=PAD, pady=(18, 4))
        tk.Label(
            hist_hdr, text="Recent Downloads", bg=BG, fg=TXT_MUTED, font=FONT_LABEL
        ).pack(side="left")

        tk.Button(
            hist_hdr,
            text="Export",
            bg=BG,
            fg=TXT_MUTED,
            activebackground=BG,
            activeforeground=TXT_PRIMARY,
            relief="flat",
            font=FONT_SMALL,
            cursor="hand2",
            command=self._export_history,
            bd=0,
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            hist_hdr,
            text="Clear",
            bg=BG,
            fg=TXT_MUTED,
            activebackground=BG,
            activeforeground=TXT_ERROR,
            relief="flat",
            font=FONT_SMALL,
            cursor="hand2",
            command=self._clear_history,
            bd=0,
        ).pack(side="right")

        outer3, card3 = _make_card(self)
        outer3.pack(fill="both", padx=PAD, pady=(0, PAD), expand=True)

        scrollbar = tk.Scrollbar(
            card3, bg=BG_CARD, troughcolor=BG_INPUT, relief="flat", bd=0, width=8
        )
        self.hist_list = tk.Listbox(
            card3,
            bg=BG_CARD,
            fg=TXT_MUTED,
            selectbackground=BG_INPUT,
            selectforeground=TXT_PRIMARY,
            relief="flat",
            bd=0,
            font=FONT_HIST,
            activestyle="none",
            yscrollcommand=scrollbar.set,
            height=6,
        )
        scrollbar.config(command=self.hist_list.yview)  # type: ignore[arg-type]
        self.hist_list.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        scrollbar.pack(side="right", fill="y", pady=6)

        self.hist_list.bind("<Double-1>", self._history_dblclick)
        self._refresh_history_ui()

    # ------------------------------------------------------------------
    # Config persistence
    # ------------------------------------------------------------------
    def _populate_from_config(self) -> None:
        cfg = self._cfg
        if cfg.get("output_dir"):
            self.dir_var.set(cfg["output_dir"])
        self.format_var.set(
            _LABEL_BY_KEY.get(cfg.get("format", "best"), "Best Quality")
        )
        self.sub_var.set(bool(cfg.get("subtitles", False)))
        self.sponsor_var.set(bool(cfg.get("sponsorblock", False)))
        self.playlist_var.set(bool(cfg.get("playlist", False)))

    def _save_current_config(self) -> None:
        ok = save_config(
            {
                "output_dir": self.dir_var.get().strip(),
                "format": FORMAT_LABELS.get(self.format_var.get(), "best"),
                "subtitles": self.sub_var.get(),
                "sponsorblock": self.sponsor_var.get(),
                "playlist": self.playlist_var.get(),
            }
        )
        if not ok:
            self._set_status("Warning: could not save settings", "error")

    # ------------------------------------------------------------------
    # Version check
    # ------------------------------------------------------------------
    def _fetch_version(self) -> None:
        try:
            ver = get_ydl_version()
        except Exception:
            ver = "unknown"
        self._safe_after(0, self._show_version, ver)

    def _show_version(self, ver: str) -> None:
        self.subtitle_var.set(
            f"Paste a URL, press Enter or click Download  \u2022  yt-dlp {ver}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _safe_after(self, ms: int, func: Any, *args: Any) -> None:
        """Like self.after() but silently ignores calls on a destroyed widget."""
        try:
            self.after(ms, func, *args)
        except Exception:
            pass

    def _center(self) -> None:
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"+{x}+{y}")

    def _on_closing(self) -> None:
        """Handle window close: cancel active download first, then destroy.

        Forces destroy after ~5 seconds (25 retries) to prevent the window
        from staying open indefinitely if the download thread blocks.
        """
        if self._download_active:
            self._cancel_event.set()
            # Terminate tracked ffmpeg subprocesses to avoid orphans
            for proc in list(self._child_procs):
                try:
                    proc.terminate()
                except OSError:
                    pass
            self._child_procs.clear()
            self._close_retries += 1
            if self._close_retries < 25:
                self.after(200, self._on_closing)
                return
        self.destroy()

    def _set_status(self, msg: str, state: str = "idle") -> None:
        colors = {
            "idle": TXT_MUTED,
            "loading": TXT_WARN,
            "success": TXT_SUCCESS,
            "error": TXT_ERROR,
        }
        self.status_var.set(msg)
        self.status_lbl.configure(fg=colors.get(state, TXT_MUTED))

    def _get_urls(self) -> list[str]:
        raw = self.url_text.get("1.0", "end").strip()
        return [u.strip() for u in raw.splitlines() if u.strip()]

    def _paste_url(self) -> None:
        try:
            text = self.clipboard_get().strip()
            self.url_text.delete("1.0", "end")
            self.url_text.insert("1.0", text)
        except Exception:
            pass

    def _auto_paste(self, _event: Any) -> None:
        if self.url_text.get("1.0", "end").strip():
            return
        try:
            text = self.clipboard_get().strip()
            # Only auto-paste lines that pass URL validation
            valid_lines = [
                ln
                for ln in text.splitlines()
                if ln.strip() and is_valid_url(ln.strip())
            ]
            if valid_lines:
                self.url_text.insert("1.0", "\n".join(valid_lines))
        except Exception:
            pass

    def _browse_folder(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.dir_var.get())
        if folder:
            self.dir_var.set(folder)

    def _open_folder(self) -> None:
        folder = self.dir_var.get().strip()
        self._open_path(folder)

    def _open_path(self, folder: str) -> None:
        """Open a folder in the system file manager, with error handling."""
        if not folder or not os.path.isdir(folder):
            return
        try:
            if sys.platform == "win32":
                os.startfile(folder)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except FileNotFoundError:
            self._set_status("Could not open folder (file manager not found)", "error")
        except OSError:
            self._set_status("Could not open folder", "error")

    def _copy_title(self) -> None:
        if self._last_title:
            self.clipboard_clear()
            self.clipboard_append(self._last_title)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------
    def _clear_history(self) -> None:
        self._history.clear()
        if not save_history(self._history):
            self._set_status("Warning: could not save history", "error")
        self._refresh_history_ui()

    def _refresh_history_ui(self) -> None:
        self.hist_list.delete(0, "end")
        if not self._history:
            self.hist_list.insert("end", "  No downloads yet")
            self.hist_list.itemconfig(0, fg=TXT_MUTED)  # type: ignore[call-arg]
        else:
            for item in reversed(self._history):
                ts = item.get("time", "")
                title = item.get("title", "Unknown")
                status = item.get("status", "success")
                prefix = "\u2713 " if status == "success" else "\u2717 "
                color = TXT_SUCCESS if status == "success" else TXT_ERROR
                idx = self.hist_list.size()
                self.hist_list.insert("end", f"  {prefix}{ts}   {title}")
                self.hist_list.itemconfig(idx, fg=color)  # type: ignore[call-arg]

    def _history_dblclick(self, _event: Any) -> None:
        sel: tuple[int, ...] = self.hist_list.curselection()  # type: ignore[assignment]
        if not sel:
            return
        idx: int = int(sel[0])  # type: ignore[arg-type]
        real_idx: int = len(self._history) - 1 - idx
        if 0 <= real_idx < len(self._history):
            folder: str = str(self._history[real_idx].get("path", ""))
            self._open_path(folder)

    def _export_history(self) -> None:
        if not self._history:
            messagebox.showinfo("Export", "No history to export.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv")],
            initialfile="yt_history.csv",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["time", "title", "path", "status"])
            for item in self._history:
                writer.writerow(
                    [
                        item.get("time", ""),
                        item.get("title", ""),
                        item.get("path", ""),
                        item.get("status", "success"),
                    ]
                )
        self._set_status(f"History exported to {os.path.basename(path)}", "success")

    # ------------------------------------------------------------------
    # Thumbnail
    # ------------------------------------------------------------------
    def _display_thumbnail(self, data: bytes, title: str) -> None:
        if not _has_pil:
            return
        try:
            img = Image.open(io.BytesIO(data))  # type: ignore[possibly-undefined]
            w, h = img.size
            if w > 200:
                ratio = 200 / w
                img = img.resize((200, int(h * ratio)), Image.LANCZOS)  # type: ignore[possibly-undefined]
            self._thumb_photo = ImageTk.PhotoImage(img)  # type: ignore[possibly-undefined]
            self.thumb_label.configure(image=self._thumb_photo)
            self.thumb_title_lbl.configure(text=title)
            self.thumb_frame.pack(fill="x", padx=20, pady=(10, 0), before=self.progress)
        except Exception:
            pass

    def _hide_thumbnail(self) -> None:
        self.thumb_frame.pack_forget()
        self._thumb_photo = None

    # ------------------------------------------------------------------
    # Speed / ETA helpers
    # ------------------------------------------------------------------
    def _show_speed_eta(self) -> None:
        self.speed_eta_frame.pack(fill="x", padx=20, pady=(4, 0), after=self.progress)

    def _hide_speed_eta(self) -> None:
        self.speed_eta_frame.pack_forget()
        self.speed_lbl.configure(text="")
        self.eta_lbl.configure(text="")

    # ------------------------------------------------------------------
    # Progress update (called on main thread via after())
    # ------------------------------------------------------------------
    def _update_progress(self, d: dict[str, Any]) -> None:
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            if total and total > 0:
                if not self._progress_determinate:
                    self.progress.stop()
                    self._progress_determinate = True
                pct = min(downloaded / total * 100, 100)
                self.progress.configure(mode="determinate")
                self.progress["value"] = pct

            speed = str(d.get("_speed_str", "")).strip()
            eta = str(d.get("_eta_str", "")).strip()
            if speed:
                self.speed_lbl.configure(text=speed)
            if eta:
                self.eta_lbl.configure(text=f"ETA {eta}")

            info: dict[str, Any] = d.get("info_dict") or {}
            pl_idx: Any = info.get("playlist_index") or info.get("playlist_autonumber")
            n_entries: Any = info.get("n_entries") or info.get("playlist_count")
            pct_str = str(d.get("_percent_str", "")).strip()

            parts: list[str] = []
            if self._queue_total > 1:
                parts.append(
                    f"Downloading {d.get('_queue_index', 0)} / {self._queue_total} URLs"
                )
            if pl_idx and n_entries:
                parts.append(f"Video {pl_idx} / {n_entries}")
            if not parts:
                parts.append("Downloading")
            parts.append(pct_str)
            self._set_status(" \u2014 ".join(parts), "loading")

        elif d["status"] == "finished":
            self._set_status("Merging / post-processing\u2026", "loading")

    def _reset_progress_for_url(self) -> None:
        self._progress_determinate = False
        self.progress.stop()
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(10)

    # ------------------------------------------------------------------
    # Download lifecycle
    # ------------------------------------------------------------------
    def _start_download(self) -> None:
        if self._download_active:
            return
        urls = self._get_urls()
        if not urls:
            messagebox.showwarning("No URL", "Please paste a YouTube URL first.")
            return
        invalid = [u for u in urls if not is_valid_url(u)]
        if invalid:
            messagebox.showwarning(
                "Invalid URL",
                "These don't look like YouTube URLs:\n" + "\n".join(invalid[:5]),
            )
            return

        # ffmpeg is required for video formats (merge video+audio streams)
        # and for audio extraction (FFmpegExtractAudio postprocessor)
        if not shutil.which("ffmpeg"):
            messagebox.showwarning(
                "ffmpeg Not Found",
                "ffmpeg is required but was not found on your PATH.\n"
                "Install it from https://ffmpeg.org and restart the app.",
            )
            return

        self._download_active = True
        self._cancel_event.clear()

        self._queue_total = len(urls)
        self._progress_determinate = False

        self._save_current_config()

        # Read tkinter variables on the main thread (thread-safe)
        output_dir = self.dir_var.get().strip() or os.path.join(
            os.path.expanduser("~"), "Downloads", "YouTube"
        )
        format_key = FORMAT_LABELS.get(self.format_var.get(), "best")
        subtitles = self.sub_var.get()
        sponsorblock = self.sponsor_var.get()
        playlist = self.playlist_var.get()

        # UI state
        self.btn.configure(state="disabled", bg="#444455")
        self.open_btn.pack_forget()
        self.copy_title_btn.pack_forget()
        self.cancel_btn.pack(side="left", padx=(10, 0), ipadx=20, ipady=10)
        self.progress.configure(mode="indeterminate", value=0)
        self.progress.start(10)
        self._show_speed_eta()
        self._set_status("Starting download\u2026", "loading")

        threading.Thread(
            target=self._download_thread,
            args=(urls, output_dir, format_key, subtitles, sponsorblock, playlist),
            daemon=True,
        ).start()

    def _cancel_download(self) -> None:
        self._cancel_event.set()
        self._set_status("Cancelling\u2026", "idle")

    def _download_thread(
        self,
        urls: list[str],
        output_dir: str,
        format_key: str,
        subtitles: bool,
        sponsorblock: bool,
        playlist: bool,
    ) -> None:
        try:
            os.makedirs(output_dir, exist_ok=True)

            # Track subprocesses spawned by yt-dlp (ffmpeg) so we can kill
            # them on window close instead of leaving orphaned processes.
            _original_popen_init = subprocess.Popen.__init__

            def _tracking_popen_init(
                popen_self: Any, *args: Any, **kwargs: Any
            ) -> None:
                _original_popen_init(popen_self, *args, **kwargs)
                self._child_procs.add(popen_self)

            subprocess.Popen.__init__ = _tracking_popen_init  # type: ignore[assignment]

            success_count = 0
            error_count = 0
            last_title = "Unknown"

            _last_hook_time = 0.0
            _current_queue_idx = 0

            def gui_hook(d: dict[str, Any]) -> None:
                nonlocal _last_hook_time
                if self._cancel_event.is_set():
                    raise DownloadError("Cancelled by user")
                # Throttle UI updates to ~5/sec; always forward "finished" status
                now = time.monotonic()
                if d.get("status") != "finished" and (now - _last_hook_time) < 0.2:
                    return
                _last_hook_time = now
                # Extract only needed fields — avoids holding a ref to the
                # large, mutable info_dict that yt-dlp may recycle.
                info: dict[str, Any] = d.get("info_dict") or {}
                snap: dict[str, Any] = {
                    "status": d.get("status"),
                    "total_bytes": d.get("total_bytes"),
                    "total_bytes_estimate": d.get("total_bytes_estimate"),
                    "downloaded_bytes": d.get("downloaded_bytes", 0),
                    "_speed_str": _ANSI_RE.sub("", str(d.get("_speed_str", ""))),
                    "_eta_str": _ANSI_RE.sub("", str(d.get("_eta_str", ""))),
                    "_percent_str": _ANSI_RE.sub("", str(d.get("_percent_str", ""))),
                    "_queue_index": _current_queue_idx,
                    "info_dict": {
                        "playlist_index": info.get("playlist_index"),
                        "playlist_autonumber": info.get("playlist_autonumber"),
                        "n_entries": info.get("n_entries"),
                        "playlist_count": info.get("playlist_count"),
                    },
                }
                self._safe_after(0, self._update_progress, snap)

            def pp_hook(d: dict[str, Any]) -> None:
                """Check cancel during post-processing (ffmpeg merge, audio extract, etc.)."""
                if self._cancel_event.is_set():
                    raise DownloadError("Cancelled by user")
                status = d.get("status", "")
                if status == "started":
                    self._safe_after(
                        0,
                        self._set_status,
                        f"Post-processing: {d.get('postprocessor', 'ffmpeg')}\u2026",
                        "loading",
                    )

            for i, url in enumerate(urls, 1):
                if self._cancel_event.is_set():
                    break

                _current_queue_idx = i
                self._safe_after(0, self._reset_progress_for_url)

                if self._queue_total > 1:
                    self._safe_after(
                        0,
                        self._set_status,
                        f"Fetching info \u2014 URL {i} / {len(urls)}\u2026",
                        "loading",
                    )
                else:
                    self._safe_after(
                        0, self._set_status, "Fetching info\u2026", "loading"
                    )

                try:
                    opts = build_ydl_opts(
                        output_dir=output_dir,
                        progress_hooks=[gui_hook],
                        postprocessor_hooks=[pp_hook],
                        quiet=True,
                        format_preset=format_key,
                        subtitles=subtitles,
                        sponsorblock=sponsorblock,
                        playlist=playlist,
                    )
                    with yt_dlp.YoutubeDL(opts) as ydl:  # type: ignore[arg-type]
                        raw = ydl.extract_info(url, download=False)
                        if not raw:
                            raise DownloadError("Could not extract video information")
                        info: dict[str, Any] = dict(raw)
                        title = str(info.get("title", "Unknown"))
                        thumb_url = info.get("thumbnail", "")

                        # Check cancel before thumbnail fetch / download
                        if self._cancel_event.is_set():
                            raise DownloadError("Cancelled by user")

                        # Fetch thumbnail in this thread (I/O), display on main thread
                        if thumb_url and _has_pil and _is_safe_url(thumb_url):
                            try:
                                req = Request(
                                    thumb_url, headers={"User-Agent": "Mozilla/5.0"}
                                )
                                with urlopen(req, timeout=10) as resp:
                                    thumb_data = resp.read(_MAX_THUMB_BYTES)
                                self._safe_after(
                                    0, self._display_thumbnail, thumb_data, title
                                )
                            except Exception:
                                pass

                        # Verify formats exist before starting download (guards
                        # against ignore_no_formats_error silently doing nothing)
                        if not info.get("formats") and not info.get("url"):
                            raise DownloadError(f"No downloadable formats for: {title}")

                        # Check cancel before starting actual download
                        if self._cancel_event.is_set():
                            raise DownloadError("Cancelled by user")

                        # Use download([url]) instead of process_ie_result():
                        # extract_info(download=False) returns an already-processed
                        # result; calling process_ie_result() on it double-processes
                        # and silently fails for playlists.
                        ydl.download([url])

                    success_count += 1
                    last_title = title
                    self._safe_after(0, self._add_history, title, output_dir, "success")

                except DownloadError as e:
                    if "Cancelled" in str(e) or self._cancel_event.is_set():
                        self._safe_after(0, self._on_error, "Cancelled by user")
                        return
                    error_count += 1
                    err_msg = _ANSI_RE.sub("", str(e))[:300]
                    self._safe_after(
                        0, self._add_history, f"Failed: {err_msg}", output_dir, "error"
                    )
                except Exception as e:
                    if self._cancel_event.is_set():
                        self._safe_after(0, self._on_error, "Cancelled by user")
                        return
                    error_count += 1
                    err_msg = _ANSI_RE.sub("", str(e))[:300]
                    self._safe_after(
                        0, self._add_history, f"Failed: {err_msg}", output_dir, "error"
                    )

            # All URLs processed — report accurate outcome
            if self._cancel_event.is_set() and success_count == 0:
                self._safe_after(0, self._on_error, "Cancelled by user")
            elif self._cancel_event.is_set() and success_count > 0:
                self._safe_after(
                    0,
                    self._on_partial,
                    output_dir,
                    last_title,
                    f"{success_count} succeeded before cancellation",
                )
            elif error_count == 0:
                self._safe_after(
                    0, self._on_success, output_dir, last_title, success_count
                )
            elif success_count > 0:
                self._safe_after(
                    0,
                    self._on_partial,
                    output_dir,
                    last_title,
                    f"{success_count} succeeded, {error_count} failed",
                )
            else:
                self._safe_after(
                    0, self._on_error, f"All {error_count} download(s) failed"
                )
        except Exception as exc:
            err_detail = _ANSI_RE.sub("", str(exc))[:300] or "Unexpected error occurred"
            self._safe_after(0, self._on_error, err_detail)
        finally:
            # Restore original Popen and discard finished process refs
            subprocess.Popen.__init__ = _original_popen_init  # type: ignore[assignment]
            self._child_procs = {p for p in self._child_procs if p.poll() is None}
            self._safe_after(0, self._reset_ui)

    # ------------------------------------------------------------------
    # Result handlers
    # ------------------------------------------------------------------
    def _add_history(self, title: str, path: str, status: str) -> None:
        self._history.append(
            {
                "time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                "title": title,
                "path": path,
                "status": status,
            }
        )
        if len(self._history) > 50:
            self._history = self._history[-50:]
        if not save_history(self._history):
            self._set_status("Warning: could not save history", "error")
        self._refresh_history_ui()

    def _reset_ui(self) -> None:
        self._download_active = False
        self._close_retries = 0
        self.progress.stop()
        self.btn.configure(state="normal", bg=ACCENT, text="Download")
        self.btn.bind(
            "<Enter>",
            lambda e: (
                self.btn.config(bg=ACCENT_GLOW)
                if str(self.btn["state"]) != "disabled"
                else None
            ),
        )
        self.btn.bind(
            "<Leave>",
            lambda e: (
                self.btn.config(bg=ACCENT)
                if str(self.btn["state"]) != "disabled"
                else None
            ),
        )
        self.cancel_btn.pack_forget()
        self._hide_speed_eta()

    def _on_success(self, output_dir: str, title: str, count: int) -> None:
        self.progress.configure(mode="determinate", value=100)
        self._last_title = title
        self._hide_thumbnail()
        self.open_btn.pack(side="left", padx=(10, 0), ipadx=20, ipady=10)
        self.copy_title_btn.pack(side="left", padx=(10, 0), ipadx=20, ipady=10)

        msg = f"Download complete \u2014 {title}"
        if count > 1:
            msg = f"All {count} downloads complete \u2014 last: {title}"
        self._set_status(msg, "success")

        self.url_text.delete("1.0", "end")
        self.url_text.focus_set()

    def _on_partial(self, output_dir: str, title: str, msg: str) -> None:
        self.progress.configure(mode="determinate", value=50)  # partial: some succeeded
        self._last_title = title
        self._hide_thumbnail()
        self.open_btn.pack(side="left", padx=(10, 0), ipadx=20, ipady=10)
        self.copy_title_btn.pack(side="left", padx=(10, 0), ipadx=20, ipady=10)
        self._set_status(msg, "error")

    def _on_error(self, msg: str) -> None:
        self.progress.configure(mode="determinate", value=0)
        self._hide_thumbnail()
        if "Cancelled" in msg:
            self._set_status("Download cancelled.", "idle")
        else:
            self._set_status(f"\u274c  {msg[:200]}", "error")


# ---------------------------------------------------------------------------
_LOCK_FILE = os.path.join(DATA_DIR, ".yt_gui.lock")


def _acquire_instance_lock() -> io.TextIOWrapper | None:
    """Try to acquire a single-instance advisory lock. Return the file handle
    on success, or None if another instance already holds the lock."""
    try:
        # Open in write mode; on Windows the file stays locked while open
        lock_fh = open(_LOCK_FILE, "w", encoding="utf-8")  # noqa: SIM115
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(lock_fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fh.write(str(os.getpid()))
        lock_fh.flush()
        return lock_fh
    except (OSError, ImportError):
        return None


if __name__ == "__main__":
    _lock = _acquire_instance_lock()
    if _lock is None:
        _root = tk.Tk()
        _root.withdraw()
        messagebox.showinfo(
            "Already Running",
            "Another instance of YouTube Downloader is already running.",
        )
        _root.destroy()
        sys.exit(0)
    app = App()
    app.mainloop()
