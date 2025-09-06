"""Minimal stub for waveshare_epd package used in tests.

This module provides an `EPD` base class so tests that dynamically
install fake modules can subclass it without mypy complaining about
`display` attribute existence.
"""
from typing import Any


class EPD:
    """Base EPD class placeholder.

    Real Waveshare drivers provide an `EPD` class with methods like
    `Init`, `getbuffer`, `display`, `Clear`, and `sleep`. Tests install
    fake modules that define their own `EPD` subclasses; having this
    stub ensures static analyzers see the attribute.
    """

    def Init(self) -> None:  # pragma: no cover - simple stub
        raise NotImplementedError

    def getbuffer(self, img: Any) -> Any:  # pragma: no cover - stub
        raise NotImplementedError

    def display(self, buf: Any, *args: Any) -> Any:  # pragma: no cover - stub
        raise NotImplementedError

    def Clear(self) -> None:  # pragma: no cover - stub
        raise NotImplementedError

    def sleep(self) -> None:  # pragma: no cover - stub
        raise NotImplementedError


