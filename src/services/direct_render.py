"""Outcome policy for direct manual renders (needs no request or app context)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from PIL import Image

from utils.backend_errors import route_error_for
from utils.plugin_errors import URLValidationError
from utils.progress import track_progress

INTERNAL_ERROR_MSG = "An internal error occurred"


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


def known_failure_outcome(error: BaseException) -> DirectRenderOutcome | None:
    """Return the outcome for a failure every display route reports alike.

    :func:`utils.backend_errors.route_error_for` owns that mapping (blackout,
    a stopped loop, a rejected URL, a provider refusal, chromium down, a
    timeout). Its messages are module constants or ``safe_message()``, so no
    exception text reaches a response. None means *error* is not one of them.
    """
    mapped = route_error_for(error)
    if mapped is None:
        return None
    return DirectRenderOutcome(
        False,
        mapped.message,
        mapped.status,
        None if mapped.code is None else str(mapped.code),
        dict(mapped.details or {}),
    )


def internal_failure_outcome() -> DirectRenderOutcome:
    """Return the outcome for a failure with no safe, specific message."""
    return DirectRenderOutcome(False, INTERNAL_ERROR_MSG, 500, "internal_error")


def _render_failure_outcome(error: Exception) -> DirectRenderOutcome:
    known = known_failure_outcome(error)
    if known is not None:
        return known
    if isinstance(error, RuntimeError):
        # A plugin that gave up. Its text goes to the log and the error card
        # on the panel, not into the response.
        return DirectRenderOutcome(False, INTERNAL_ERROR_MSG, 400, "plugin_error")
    return internal_failure_outcome()


def execute_direct_render(
    generate: Callable[[], Image.Image | None],
    display: Callable[[Image.Image], None],
    read_timings: Callable[[], tuple[int | None, int | None]],
    fallback: Callable[[BaseException, bool], None],
) -> DirectRenderOutcome:
    """Apply identical no-image, failure, fallback and metric rules to all callers."""
    started = perf_counter()
    with track_progress() as tracker:
        generating = True
        try:
            image = generate()
            generate_ms = int((perf_counter() - started) * 1000)
            if image is None:
                return DirectRenderOutcome(
                    True,
                    "Plugin produced no image; display unchanged",
                    metrics={"no_image": True},
                )
            generating = False
            display(image)
        except Exception as error:
            outcome = (
                _render_failure_outcome(error)
                if generating
                else internal_failure_outcome()
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
