"""One history retention policy, read from ``history_cleanup`` in device.json (A7).

``DisplayManager`` used to cap history with its own ``INKYPI_HISTORY_MAX_ENTRIES``
(500) while the refresh loop applied ``history_cleanup``, so raising either
limit did nothing: the other one still pruned to 500.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from utils.config_schema import ConfigValidationError, validate_device_config
from utils.history_cleanup import (
    DEFAULT_MAX_AGE_DAYS,
    DEFAULT_MAX_COUNT,
    DEFAULT_MIN_FREE_BYTES,
    RetentionPolicy,
    cleanup_history,
)


def _fill(history_dir: Path, count: int) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        png = history_dir / f"display_{i:04d}.png"
        png.write_bytes(b"img")
        os.utime(png, (1_000_000 + i, 1_000_000 + i))


def _png_count(history_dir: Path) -> int:
    return sum(1 for name in os.listdir(history_dir) if name.endswith(".png"))


# ---------------------------------------------------------------------------
# RetentionPolicy.from_config
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, {}, "500", ["max_count"]])
def test_missing_or_malformed_block_uses_defaults(raw: object) -> None:
    assert RetentionPolicy.from_config(raw) == RetentionPolicy(
        DEFAULT_MAX_AGE_DAYS, DEFAULT_MAX_COUNT, DEFAULT_MIN_FREE_BYTES
    )


def test_configured_limits_are_read() -> None:
    policy = RetentionPolicy.from_config(
        {"max_age_days": 7, "max_count": 1200, "min_free_bytes": 0}
    )
    assert policy == RetentionPolicy(max_age_days=7, max_count=1200, min_free_bytes=0)


@pytest.mark.parametrize("bad", [-1, True, "1000", 2.5, None])
def test_a_bad_value_falls_back_to_its_default(bad: object) -> None:
    policy = RetentionPolicy.from_config({"max_count": bad, "max_age_days": 3})
    assert policy.max_count == DEFAULT_MAX_COUNT
    assert policy.max_age_days == 3


# ---------------------------------------------------------------------------
# The per-save cap and the periodic cleanup share the setting
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_display_manager_state() -> Any:
    from display.display_manager import DisplayManager

    DisplayManager._history_count_estimate = None
    DisplayManager._history_increment_count = 0
    yield
    DisplayManager._history_count_estimate = None
    DisplayManager._history_increment_count = 0


def test_raising_max_count_lets_history_grow_past_500(
    device_config_dev: Any, tmp_path: Path, fresh_display_manager_state: Any
) -> None:
    from display.display_manager import DisplayManager

    device_config_dev.update_value("history_cleanup", {"max_count": 600})
    history_dir = tmp_path / "history"
    _fill(history_dir, 550)

    DisplayManager(device_config_dev)._prune_history(str(history_dir))

    assert _png_count(history_dir) == 550


def test_lowering_max_count_prunes_on_the_next_save(
    device_config_dev: Any, tmp_path: Path, fresh_display_manager_state: Any
) -> None:
    from display.display_manager import DisplayManager

    device_config_dev.update_value("history_cleanup", {"max_count": 4})
    history_dir = tmp_path / "history"
    _fill(history_dir, 6)

    DisplayManager(device_config_dev)._prune_history(str(history_dir))

    assert sorted(os.listdir(history_dir)) == [
        f"display_{i:04d}.png" for i in range(2, 6)
    ]


def test_max_count_zero_turns_the_count_cap_off(
    device_config_dev: Any, tmp_path: Path, fresh_display_manager_state: Any
) -> None:
    from display.display_manager import DisplayManager

    device_config_dev.update_value("history_cleanup", {"max_count": 0})
    history_dir = tmp_path / "history"
    _fill(history_dir, 5)

    DisplayManager(device_config_dev)._prune_history(str(history_dir))

    assert _png_count(history_dir) == 5


def test_periodic_cleanup_reads_the_same_setting(
    device_config_dev: Any, tmp_path: Path
) -> None:
    from refresh_task.housekeeping import RefreshHousekeeper

    history_dir = tmp_path / "history"
    _fill(history_dir, 5)
    device_config_dev.history_image_dir = str(history_dir)
    device_config_dev.update_value(
        "history_cleanup", {"max_count": 2, "max_age_days": 0, "min_free_bytes": 0}
    )

    RefreshHousekeeper(device_config_dev, MagicMock()).maybe_run_history_cleanup(
        tick_count=10, cleanup_interval_ticks=10
    )

    assert _png_count(history_dir) == 2


def test_same_second_snapshots_are_pruned_in_name_order(tmp_path: Path) -> None:
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    # Created newest-name-first so directory order cannot hide a wrong sort.
    for name in (
        "display_20260101_120000_002",
        "display_20260101_120000_001",
        "display_20260101_120000",
    ):
        png = history_dir / f"{name}.png"
        png.write_bytes(b"img")
        os.utime(png, (1_000_000, 1_000_000))

    cleanup_history(str(history_dir), max_age_days=0, max_count=1, min_free_bytes=0)

    assert os.listdir(history_dir) == ["display_20260101_120000_002.png"]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _config(**extra: Any) -> dict[str, Any]:
    return {
        "name": "InkyPi",
        "display_type": "mock",
        "resolution": [800, 480],
        "orientation": "horizontal",
        **extra,
    }


def test_schema_accepts_the_history_cleanup_block() -> None:
    validate_device_config(
        _config(
            history_cleanup={"max_age_days": 0, "max_count": 1000, "min_free_bytes": 0}
        )
    )


@pytest.mark.parametrize(
    "block",
    [{"max_count": -1}, {"max_age_days": "30"}, {"min_free_bytes": 1.5}],
    ids=["negative", "string", "float"],
)
def test_schema_rejects_bad_history_limits(block: dict[str, Any]) -> None:
    with pytest.raises(ConfigValidationError):
        validate_device_config(_config(history_cleanup=block))
