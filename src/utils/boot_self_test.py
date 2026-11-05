"""Boot self-test after an install or update (B9).

When the panel or its driver is broken, the first visible symptom is usually a
plugin "failing" — and the plugin gets blamed. The self-test proves the bottom
of the stack on its own: once per installed version, push a known test
pattern straight to the driver and record whether ``display_image`` completed.

Trigger
-------
Neither ``install.sh`` nor ``update.sh`` leaves a "just finished" marker (the
``prev_version`` breadcrumb is written *before* an update and survives it, so
it cannot say whether this boot is the first one on the new code). The record
itself is therefore the trigger: it stores the version it ran against, and a
boot whose ``VERSION`` differs — a fresh install has no record at all — runs
the test again. Every other boot is a no-op stat of one small file.

The record lives in the persistent state dir (``/var/lib/inkypi``, alongside
``prev_version`` and the crash verdict) via the hardened writer in
:mod:`utils.crash_breadcrumb`.

Skipping
--------
* ``INKYPI_SKIP_BOOT_SELF_TEST=1`` in the environment, or
* ``"boot_self_test": false`` in ``device.json``, or
* ``display_type: "mock"`` — there is no panel to test.

A boot during blackout (B12) defers the test without recording it, so it runs
on the first boot after the blackout is lifted.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from utils import crash_breadcrumb

logger = logging.getLogger(__name__)

STATE_NAME = "boot_self_test.json"
SKIP_ENV = "INKYPI_SKIP_BOOT_SELF_TEST"
CONFIG_KEY = "boot_self_test"

#: Leave the pattern up long enough for a person at the frame to see it.
_DEFAULT_HOLD_SECONDS = 5.0
#: Slow colour panels take ~30 s per full refresh; two writes plus the hold.
_COMMAND_TIMEOUT_SECONDS = 240.0

#: Pure colours every supported panel can at least approximate.
_BARS: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("Black", (0, 0, 0)),
    ("White", (255, 255, 255)),
    ("Red", (255, 0, 0)),
    ("Green", (0, 255, 0)),
    ("Blue", (0, 0, 255)),
    ("Yellow", (255, 255, 0)),
    ("Orange", (255, 128, 0)),
)

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def last_result() -> dict[str, Any] | None:
    """The recorded outcome of the most recent self-test, if any."""
    return crash_breadcrumb.read_state(STATE_NAME)


def skip_reason(device_config: Any) -> str | None:
    """Why the self-test is disabled on this device, or ``None`` if enabled."""
    if os.getenv(SKIP_ENV, "").strip().lower() in _TRUTHY:
        return f"{SKIP_ENV} is set"
    if device_config.get_config(CONFIG_KEY, default=True) is False:
        return f"{CONFIG_KEY} is false in device config"
    if device_config.get_config("display_type", default="") == "mock":
        return "mock display"
    return None


def is_due(version: str) -> bool:
    """True when no self-test has been recorded for *version* yet."""
    record = last_result()
    return record is None or record.get("version") != version


def make_test_pattern(width: int, height: int, version: str) -> Any:
    """Vertical colour bars with a label naming the test and the version."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    label_h = max(24, height // 6)
    bar_w = width / len(_BARS)
    for index, (_name, color) in enumerate(_BARS):
        x0 = round(index * bar_w)
        x1 = round((index + 1) * bar_w)
        draw.rectangle([x0, 0, x1, height - label_h], fill=color)
    # Outline the white bar so it reads as a bar, not a gap.
    white_x0 = round(bar_w)
    draw.rectangle(
        [white_x0, 0, round(2 * bar_w) - 1, height - label_h], outline=(0, 0, 0)
    )

    text = f"InkyPi self-test  v{version}"
    font: Any = None
    try:
        from utils.app_utils import get_font

        font = get_font("Jost", max(12, label_h // 2))
    except Exception:  # noqa: BLE001 — a missing font must not fail the test
        logger.debug("self-test: font unavailable, using default", exc_info=True)
    draw.text(
        (width / 2, height - label_h / 2), text, fill=(0, 0, 0), font=font, anchor="mm"
    )
    return image


def _record(version: str, status: str, **details: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "version": version,
        "status": status,
        "ran_at": datetime.now(UTC).isoformat(),
    }
    record.update(details)
    crash_breadcrumb.write_state(STATE_NAME, record)
    return record


def run(
    refresh_task: Any,
    device_config: Any,
    version: str,
    *,
    restore: bool = True,
    hold_seconds: float | None = None,
) -> dict[str, Any]:
    """Push the test pattern once and record pass/fail.

    "Pass" means the display driver's ``display_image`` returned without
    raising. Afterwards the previous frame is restored (unless *restore* is
    False, e.g. because the startup image is about to replace it) so the
    panel does not sit on the pattern until the next scheduled refresh.

    Runs through :meth:`RefreshTask.run_display_command` so it is serialised
    with plugin refreshes. Never raises.
    """
    hold = _DEFAULT_HOLD_SECONDS if hold_seconds is None else hold_seconds
    width, height = device_config.get_resolution()
    pattern = make_test_pattern(int(width), int(height), version)

    def _command(display_manager: Any) -> Mapping[str, object]:
        metrics = dict(display_manager.show_system_image(pattern))
        if hold > 0:
            time.sleep(hold)
        if restore:
            try:
                display_manager.restore_last_frame()
            except Exception as exc:  # noqa: BLE001 — the test itself passed
                logger.warning("self-test: could not restore previous frame: %s", exc)
                metrics["restore_error"] = type(exc).__name__
        return metrics

    logger.info("Boot self-test: pushing test pattern for v%s", version)
    try:
        metrics = refresh_task.run_display_command(
            "boot_self_test", _command, timeout=_COMMAND_TIMEOUT_SECONDS
        )
    except Exception as exc:  # noqa: BLE001 — recorded, never raised
        logger.error("Boot self-test FAILED: %s: %s", type(exc).__name__, exc)
        return _record(version, "fail", error=f"{type(exc).__name__}: {exc}"[:500])

    logger.info("Boot self-test passed (%s)", metrics.get("display_driver", "?"))
    details = {
        key: metrics[key]
        for key in ("display_driver", "display_ms", "restore_error")
        if key in metrics
    }
    return _record(version, "pass", error=None, **details)


def maybe_run(
    refresh_task: Any,
    device_config: Any,
    version: str,
    *,
    restore: bool = True,
) -> dict[str, Any] | None:
    """Run the self-test if it is enabled, due, and not deferred by blackout.

    Returns the new record, or ``None`` when nothing ran.
    """
    from utils import blackout

    reason = skip_reason(device_config)
    if reason is not None:
        logger.info("Boot self-test skipped: %s", reason)
        return None
    if not is_due(version):
        return None
    if blackout.is_active(device_config):
        logger.info("Boot self-test deferred: display is in blackout")
        return None
    return run(refresh_task, device_config, version, restore=restore)
