from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import local
from time import perf_counter

_thread_local = local()


@dataclass
class ProgressTracker:
    """Track named steps and their elapsed time in milliseconds."""

    steps: list[tuple[str, int]] = field(default_factory=list)
    _start: float = field(default_factory=perf_counter)
    _last: float = field(init=False)

    def __post_init__(self) -> None:  # pragma: no cover - trivial
        self._last = self._start

    def step(self, name: str) -> None:
        now = perf_counter()
        elapsed_ms = int((now - self._last) * 1000)
        self.steps.append((name, elapsed_ms))
        self._last = now

    def get_steps(self) -> list[tuple[str, int]]:
        return list(self.steps)


@contextmanager
def track_progress() -> Iterator[ProgressTracker]:
    """Context manager to expose a tracker via thread-local storage."""

    tracker = ProgressTracker()
    _thread_local.tracker = tracker
    try:
        yield tracker
    finally:
        _thread_local.tracker = None


def record_step(name: str) -> None:
    """Record a progress step if a tracker is active."""

    tracker: ProgressTracker | None = getattr(_thread_local, "tracker", None)
    if tracker:
        tracker.step(name)
