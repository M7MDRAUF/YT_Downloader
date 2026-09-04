"""Shared test fixtures.

Two jobs, both about making the suite hermetic:

1. Install a minimal ``tkinter`` stub *once*, before any test module imports
   ``gui``, so the GUI module is importable without a display.
2. Neutralise browser-cookie probing.  ``build_ydl_opts()`` calls
   ``get_cookies_browser()``, which opens the real Firefox/Chrome cookie
   stores of whoever runs pytest.  Without this the suite reads a developer's
   personal data, and — because a dev machine finds cookies while CI does not
   — dev and CI exercise different branches and build different option dicts.
"""

import sys
import types
from collections.abc import Iterator
from typing import Any

import pytest

from tests.helpers import FakeYDL


def _install_tkinter_stub() -> None:
    """Register a stub ``tkinter`` in sys.modules if the real one is unusable."""
    tk = types.ModuleType("tkinter")
    widget_names = (
        "Tk",
        "Frame",
        "Label",
        "Misc",
        "StringVar",
        "BooleanVar",
        "IntVar",
        "Text",
        "Entry",
        "Listbox",
        "Scrollbar",
        "OptionMenu",
        "Checkbutton",
        "Button",
        "PhotoImage",
    )
    for name in widget_names:
        setattr(tk, name, type(name, (), {}))

    # gui._safe_after suppresses tk.TclError, so the stub must expose it.
    tk.TclError = type("TclError", (Exception,), {})  # type: ignore[attr-defined]

    constants = {
        "END": "end",
        "NORMAL": "normal",
        "DISABLED": "disabled",
        "SINGLE": "single",
        "X": "x",
        "Y": "y",
        "BOTH": "both",
        "LEFT": "left",
        "RIGHT": "right",
        "TOP": "top",
        "BOTTOM": "bottom",
        "W": "w",
        "E": "e",
    }
    for key, value in constants.items():
        setattr(tk, key, value)

    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.askdirectory = lambda *_a, **_k: ""  # type: ignore[attr-defined]
    filedialog.asksaveasfilename = lambda *_a, **_k: ""  # type: ignore[attr-defined]

    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Progressbar", "Combobox", "Style"):
        setattr(ttk, name, type(name, (), {}))

    messagebox = types.ModuleType("tkinter.messagebox")
    for name in ("showerror", "showinfo", "showwarning", "askyesno"):
        setattr(messagebox, name, lambda *_a, **_k: None)

    tk.filedialog = filedialog  # type: ignore[attr-defined]
    sys.modules["tkinter"] = tk
    sys.modules["tkinter.filedialog"] = filedialog
    sys.modules["tkinter.ttk"] = ttk
    sys.modules["tkinter.messagebox"] = messagebox


_install_tkinter_stub()

# Captured before any fixture patches it, so tests that genuinely target the
# cookie-probe logic can opt back into the real implementation.
import download  # noqa: E402 — must follow the tkinter stub install

_REAL_GET_COOKIES_BROWSER = download.get_cookies_browser


@pytest.fixture(autouse=True)
def _no_browser_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop every test from touching the developer's real browser cookie DBs.

    Autouse and unconditional: ``build_ydl_opts()`` reaches
    ``get_cookies_browser()`` on every call, so opting in per-test would leave
    the default path reading private data.  Tests that care about the
    cookies-found branch patch it explicitly instead.
    """
    import download

    monkeypatch.setattr(download, "get_cookies_browser", lambda: None)


@pytest.fixture
def real_cookie_probe(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Restore the genuine ``get_cookies_browser`` for tests that target it.

    The autouse fixture above stubs it out for everyone; these tests supply
    their own fake ``YoutubeDL`` so no real cookie store is ever opened.
    """
    import download

    monkeypatch.setattr(download, "get_cookies_browser", _REAL_GET_COOKIES_BROWSER)
    return _REAL_GET_COOKIES_BROWSER


@pytest.fixture
def fake_ydl() -> Iterator[type[FakeYDL]]:
    """Return the fake yt-dlp driver, with its recorded instances reset.

    Clears on teardown as well as setup: `instances` is module-level state, so
    a stale entry would otherwise be visible to any later test that touches
    FakeYDL without requesting this fixture.
    """
    FakeYDL.instances = []
    yield FakeYDL
    FakeYDL.instances = []
