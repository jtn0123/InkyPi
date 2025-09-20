from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from threading import local
from time import perf_counter
from typing import Optional

_thread_local = local()


@dataclass
class ProgressStep:
    """Detailed information about a progress step."""

    name: str
    description: str
    elapsed_ms: int
    status: str = "completed"  # completed, failed, in_progress
    error_message: Optional[str] = None
    substeps: list[str] = field(default_factory=list)


@dataclass
class ProgressTracker:
    """Track named steps with detailed information and timing."""

    steps: list[ProgressStep] = field(default_factory=list)
    _start: float = field(default_factory=perf_counter)
    _last: float = field(init=False)
    _current_step: Optional[str] = None
    _current_step_start: float = field(init=False)

    def __post_init__(self) -> None:  # pragma: no cover - trivial
        self._last = self._start
        self._current_step_start = self._start

    def step(self, name: str, description: str = "") -> None:
        """Record a completed step with timing information."""
        now = perf_counter()
        elapsed_ms = int((now - self._last) * 1000)

        step = ProgressStep(
            name=name,
            description=description or name,
            elapsed_ms=elapsed_ms,
            status="completed"
        )
        self.steps.append(step)
        self._last = now
        self._current_step = None

    def start_step(self, name: str, description: str = "") -> None:
        """Start a new step that will be updated later."""
        now = perf_counter()
        self._current_step = name
        self._current_step_start = now

        step = ProgressStep(
            name=name,
            description=description or name,
            elapsed_ms=0,
            status="in_progress"
        )
        self.steps.append(step)

    def update_current_step(self, description: str, substeps: Optional[list[str]] = None) -> None:
        """Update the description or substeps of the current step."""
        if self.steps and self.steps[-1].status == "in_progress":
            self.steps[-1].description = description
            if substeps:
                self.steps[-1].substeps = substeps

    def complete_current_step(self, description: str = "") -> None:
        """Complete the current step with final timing."""
        if self.steps and self.steps[-1].status == "in_progress":
            now = perf_counter()
            elapsed_ms = int((now - self._current_step_start) * 1000)
            self.steps[-1].elapsed_ms = elapsed_ms
            self.steps[-1].status = "completed"
            if description:
                self.steps[-1].description = description
            self._last = now
            self._current_step = None

    def fail_current_step(self, error_message: str) -> None:
        """Mark the current step as failed with an error message."""
        if self.steps and self.steps[-1].status == "in_progress":
            now = perf_counter()
            elapsed_ms = int((now - self._current_step_start) * 1000)
            self.steps[-1].elapsed_ms = elapsed_ms
            self.steps[-1].status = "failed"
            self.steps[-1].error_message = error_message
            self._last = now
            self._current_step = None

    def get_steps(self) -> list[ProgressStep]:
        """Get all recorded steps."""
        return list(self.steps)

    def get_total_elapsed_ms(self) -> int:
        """Get total elapsed time since tracking started."""
        now = perf_counter()
        return int((now - self._start) * 1000)

    def get_current_step_name(self) -> Optional[str]:
        """Get the name of the currently active step."""
        return self._current_step

    def is_step_active(self) -> bool:
        """Check if there's currently an active step."""
        return self._current_step is not None


@contextmanager
def track_progress() -> Iterator[ProgressTracker]:
    """Context manager to expose a tracker via thread-local storage."""

    tracker = ProgressTracker()
    _thread_local.tracker = tracker
    try:
        yield tracker
    finally:
        _thread_local.tracker = None


def record_step(name: str, description: str = "") -> None:
    """Record a completed progress step if a tracker is active."""
    tracker: ProgressTracker | None = getattr(_thread_local, "tracker", None)
    if tracker:
        tracker.step(name, description)


def start_step(name: str, description: str = "") -> None:
    """Start a new progress step that can be updated later."""
    tracker: ProgressTracker | None = getattr(_thread_local, "tracker", None)
    if tracker:
        tracker.start_step(name, description)


def update_step(description: str, substeps: Optional[list[str]] = None) -> None:
    """Update the current progress step with new information."""
    tracker: ProgressTracker | None = getattr(_thread_local, "tracker", None)
    if tracker:
        tracker.update_current_step(description, substeps)


def complete_step(description: str = "") -> None:
    """Complete the current progress step."""
    tracker: ProgressTracker | None = getattr(_thread_local, "tracker", None)
    if tracker:
        tracker.complete_current_step(description)


def fail_step(error_message: str) -> None:
    """Mark the current progress step as failed."""
    tracker: ProgressTracker | None = getattr(_thread_local, "tracker", None)
    if tracker:
        tracker.fail_current_step(error_message)


def get_current_tracker() -> Optional[ProgressTracker]:
    """Get the current progress tracker if active."""
    return getattr(_thread_local, "tracker", None)
