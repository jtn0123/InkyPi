"""Behavioural tests for small utility helpers.

Previously this file existed "to improve code coverage" and its assertions were
either trivially true (``assert result is not None``) or wrapped in
``except Exception: pass`` so they could not fail — including one that made a
live call to httpbin.org. Rewritten to assert real values; the ``*/N`` cases
below are the ones the old ``is not None`` check silently passed while
:func:`parse_cron_field` returned an empty set.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from plugins.plugin_registry import get_plugin_instance, load_plugins
from utils.http_utils import json_error, json_success
from utils.time_utils import get_next_occurrence, parse_cron_field


class TestParseCronField:
    def test_star_covers_the_whole_range(self) -> None:
        assert parse_cron_field("*", 0, 23) == set(range(24))

    def test_explicit_range(self) -> None:
        assert parse_cron_field("0-5", 0, 23) == {0, 1, 2, 3, 4, 5}

    def test_comma_list(self) -> None:
        assert parse_cron_field("0,15,30,45", 0, 59) == {0, 15, 30, 45}

    @pytest.mark.parametrize(
        ("field", "lo", "hi", "expected"),
        [
            ("*/6", 0, 23, {0, 6, 12, 18}),
            ("*/15", 0, 59, {0, 15, 30, 45}),
            ("0-30/10", 0, 59, {0, 10, 20, 30}),
        ],
    )
    def test_step_syntax(
        self, field: str, lo: int, hi: int, expected: set[int]
    ) -> None:
        """``*/N`` used to parse to the empty set — a schedule that never fires."""
        assert parse_cron_field(field, lo, hi) == expected

    @pytest.mark.parametrize("field", ["*/0", "*/-1", "*/x", "", "nonsense"])
    def test_malformed_input_yields_no_values_rather_than_raising(
        self, field: str
    ) -> None:
        assert parse_cron_field(field, 0, 23) == set()

    def test_values_outside_the_range_are_dropped(self) -> None:
        assert parse_cron_field("5,99", 0, 23) == {5}


class TestGetNextOccurrence:
    def test_hourly_advances_to_the_next_hour(self) -> None:
        now = datetime(2025, 1, 1, 12, 30, tzinfo=UTC)
        assert get_next_occurrence("0 * * * *", now) == datetime(
            2025, 1, 1, 13, 0, tzinfo=UTC
        )

    def test_daily_advances_to_tomorrow_when_today_has_passed(self) -> None:
        now = datetime(2025, 1, 1, 13, 0, tzinfo=UTC)
        assert get_next_occurrence("0 12 * * *", now) == datetime(
            2025, 1, 2, 12, 0, tzinfo=UTC
        )

    def test_unsatisfiable_expression_returns_none(self) -> None:
        # Day-of-month 31 in a month that has none, restricted to February.
        assert (
            get_next_occurrence("0 0 31 2 *", datetime(2025, 1, 1, tzinfo=UTC)) is None
        )


class TestJsonHelpers:
    """These build a Flask response, so they need an application context."""

    def test_json_error_carries_message_and_status(self, flask_app: Any) -> None:
        with flask_app.app_context():
            body, status = json_error("Test error", status=400)
        assert status == 400
        assert body.get_json()["error"] == "Test error"
        assert body.get_json()["success"] is False

    def test_json_success_includes_extra_fields(self, flask_app: Any) -> None:
        with flask_app.app_context():
            body, status = json_success("Test success", extra_data="value")
        payload = body.get_json()
        assert status == 200
        assert payload["success"] is True
        assert payload["extra_data"] == "value"


class TestPluginRegistry:
    def test_load_plugins_registers_lazily_and_returns_none(self) -> None:
        """Documents the actual contract: registration is a side effect."""
        assert load_plugins([]) is None

    def test_get_plugin_instance_rejects_an_unknown_id(self) -> None:
        with pytest.raises(Exception):
            get_plugin_instance({"plugin_id": "definitely-not-a-plugin"})
