"""Outcome policy for direct manual renders (needs no request or app context).

``/update_now`` and ``/display-next`` render in the request thread when the
refresh loop is not running. Both go through :func:`execute_direct_render`, so
a plugin that returns no image, a plugin failure and the known failures get
the same status and code on either route.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from time import perf_counter

from PIL import Image

from utils.backend_errors import route_error_for
from utils.json_types import JsonObject
from utils.plugin_errors import URLValidationError
from utils.progress import track_progress

INTERNAL_ERROR_MSG = "An internal error occurred"


@dataclass(frozen=True)
class DirectRenderOutcome:
    ok: bool
    message: str
    status: int = 200
    code: str | None = None
    details: JsonObject = field(default_factory=dict)
    metrics: JsonObject = field(default_factory=dict)


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


def _render_failure_outcome(
    error: Exception, plugin_error_message: str
) -> DirectRenderOutcome:
    known = known_failure_outcome(error)
    if known is not None:
        return known
    if isinstance(error, RuntimeError):
        # A plugin that gave up. Its text goes to the log (and, on
        # /update_now, the error card on the panel), not into the response.
        return DirectRenderOutcome(False, plugin_error_message, 400, "plugin_error")
    return internal_failure_outcome()


def execute_direct_render(
    generate: Callable[[], Image.Image | None],
    display: Callable[[Image.Image], None],
    read_timings: Callable[[], tuple[int | None, int | None]],
    fallback: Callable[[BaseException, bool], None],
    *,
    plugin_error_message: str = INTERNAL_ERROR_MSG,
) -> DirectRenderOutcome:
    """Apply identical no-image, failure, fallback and metric rules to all callers.

    A plugin that returns no image (a control-only plugin) is a completed
    refresh with nothing to show: 200 with ``metrics={"no_image": True}`` and
    the display left alone, as the refresh loop treats it. A plugin failure is
    400 ``plugin_error`` with *plugin_error_message* (a fixed, safe string);
    the known failures are mapped by :func:`known_failure_outcome`, and
    anything else is 500 ``internal_error``. *fallback* runs on every failure
    with the error and whether it counts as a real render attempt.
    """
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
                _render_failure_outcome(error, plugin_error_message)
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
