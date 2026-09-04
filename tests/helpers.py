"""Test doubles shared across test modules.

Lives here rather than in conftest.py so both pytest and mypy can import it
by a normal module path.
"""

from typing import Any, ClassVar


class FakeYDL:
    """A stand-in for ``yt_dlp.YoutubeDL`` recording how it was driven."""

    instances: ClassVar[list["FakeYDL"]] = []

    def __init__(self, opts: dict[str, Any] | None = None) -> None:
        self.opts = opts or {}
        self.extract_calls: list[tuple[str, bool]] = []
        self.download_calls: list[list[str]] = []
        self.process_calls: list[dict[str, Any]] = []
        self.info: dict[str, Any] | None = {"title": "T", "duration": 61}
        FakeYDL.instances.append(self)

    def __enter__(self) -> "FakeYDL":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def extract_info(self, url: str, download: bool = True) -> dict[str, Any] | None:
        self.extract_calls.append((url, download))
        return self.info

    def download(self, urls: list[str]) -> None:
        self.download_calls.append(urls)

    def process_info(self, info: dict[str, Any]) -> None:
        self.process_calls.append(info)
