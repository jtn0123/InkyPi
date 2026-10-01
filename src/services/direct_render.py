"""Flask-independent outcome policy for direct manual renders."""

from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from PIL import Image

from utils.plugin_errors import (
    MANUAL_UPDATE_TIMEOUT_MSG,
    SCREENSHOT_BACKEND_UNAVAILABLE_MSG,
    ScreenshotBackendError,
    URLValidationError,
)
from utils.progress import track_progress


@dataclass(frozen=True)
class DirectRenderOutcome:
    ok: bool
    message: str
    status: int = 200
    code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)


class DirectRenderFailure(RuntimeError):
    """Safe typed failure carried through the background job adapter."""

    def __init__(self, outcome: DirectRenderOutcome) -> None:
        super().__init__(outcome.message)
        self.outcome = outcome


def execute_direct_render(
    generate: Callable[[], Image.Image | None],
    display: Callable[[Image.Image], None],
    read_timings: Callable[[], tuple[int | None, int | None]],
    fallback: Callable[[BaseException, bool], None],
) -> DirectRenderOutcome:
    """Apply identical no-image, failure, fallback and metric rules to all callers."""
    started = perf_counter()
    with track_progress() as tracker:
        try:
            image = generate()
            generate_ms = int((perf_counter() - started) * 1000)
            if image is None:
                return DirectRenderOutcome(
                    True,
                    "Plugin produced no image; display unchanged",
                    metrics={"no_image": True},
                )
            display(image)
        except Exception as error:
            if isinstance(error, URLValidationError):
                outcome = DirectRenderOutcome(
                    False,
                    error.safe_message(),
                    422,
                    "validation_error",
                    {"field": "url"},
                )
            elif isinstance(error, ScreenshotBackendError):
                outcome = DirectRenderOutcome(
                    False,
                    SCREENSHOT_BACKEND_UNAVAILABLE_MSG,
                    503,
                    "backend_unavailable",
                )
            elif isinstance(error, TimeoutError):
                outcome = DirectRenderOutcome(
                    False, MANUAL_UPDATE_TIMEOUT_MSG, 504, "manual_update_timeout"
                )
            elif isinstance(error, RuntimeError):
                outcome = DirectRenderOutcome(
                    False, "An internal error occurred", 400, "plugin_error"
                )
            else:
                outcome = DirectRenderOutcome(
                    False, "An internal error occurred", 500, "internal_error"
                )
            fallback(error, not isinstance(error, URLValidationError))
            return outcome
        try:
            display_ms, preprocess_ms = read_timings()
        except Exception:
            display_ms = preprocess_ms = None
        return DirectRenderOutcome(
            True,
            "Display updated",
            metrics={
                "request_ms": int((perf_counter() - started) * 1000),
                "display_ms": display_ms,
                "generate_ms": generate_ms,
                "preprocess_ms": preprocess_ms,
                "steps": tracker.get_steps(),
            },
        )
