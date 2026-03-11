"""Edge case tests for model.py — Playlist, PluginInstance, PlaylistManager."""

import pytest
from datetime import datetime, UTC, timedelta
from model import Playlist, PluginInstance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plugin_dict(pid="test", name="Test", refresh=None, **kwargs):
    return {
        "plugin_id": pid,
        "name": name,
        "plugin_settings": {},
        "refresh": refresh or {"interval": 3600},
        **kwargs,
    }


def _make_playlist(start, end, plugins=None, index=None):
    return Playlist(
        name="Test",
        start_time=start,
        end_time=end,
        plugins=plugins or [],
        current_plugin_index=index,
    )


def _future_snooze():
    return (datetime.now(UTC) + timedelta(hours=24)).isoformat()


def _past_snooze():
    return (datetime.now(UTC) - timedelta(hours=1)).isoformat()


# ---------------------------------------------------------------------------
# Playlist.is_active() — overnight wrap
# ---------------------------------------------------------------------------

class TestIsActiveOvernight:
    def setup_method(self):
        self.pl = _make_playlist("22:00", "06:00")

    def test_active_before_midnight(self):
        assert self.pl.is_active("23:00") is True

    def test_active_after_midnight(self):
        assert self.pl.is_active("02:00") is True

    def test_inactive_mid_morning(self):
        assert self.pl.is_active("07:00") is False

    def test_inactive_midday(self):
        assert self.pl.is_active("12:00") is False


class TestIsActiveBoundary:
    def test_exactly_at_start_is_active(self):
        pl = _make_playlist("09:00", "17:00")
        assert pl.is_active("09:00") is True

    def test_exactly_at_end_is_not_active(self):
        # is_active uses strict less-than for end
        pl = _make_playlist("09:00", "17:00")
        assert pl.is_active("17:00") is False

    def test_overnight_exactly_at_start_is_active(self):
        pl = _make_playlist("22:00", "06:00")
        assert pl.is_active("22:00") is True

    def test_overnight_exactly_at_end_is_not_active(self):
        pl = _make_playlist("22:00", "06:00")
        assert pl.is_active("06:00") is False


# ---------------------------------------------------------------------------
# Playlist.get_time_range_minutes()
# ---------------------------------------------------------------------------

class TestGetTimeRangeMinutes:
    def test_overnight_range(self):
        pl = _make_playlist("22:00", "06:00")
        assert pl.get_time_range_minutes() == 480

    def test_normal_daytime_range(self):
        pl = _make_playlist("09:00", "17:00")
        assert pl.get_time_range_minutes() == 480

    def test_short_range(self):
        pl = _make_playlist("10:00", "10:30")
        assert pl.get_time_range_minutes() == 30


# ---------------------------------------------------------------------------
# Playlist.get_next_plugin()
# ---------------------------------------------------------------------------

class TestGetNextPlugin:
    def test_corrupted_index_resets_to_zero(self):
        plugins = [_plugin_dict("a"), _plugin_dict("b")]
        pl = _make_playlist("00:00", "24:00", plugins=plugins, index=999)
        plugin = pl.get_next_plugin()
        assert plugin is not None
        assert pl.current_plugin_index == 0

    def test_advances_index(self):
        plugins = [_plugin_dict("a"), _plugin_dict("b"), _plugin_dict("c")]
        pl = _make_playlist("00:00", "24:00", plugins=plugins, index=0)
        pl.get_next_plugin()
        assert pl.current_plugin_index == 1

    def test_wraps_around(self):
        plugins = [_plugin_dict("a"), _plugin_dict("b")]
        pl = _make_playlist("00:00", "24:00", plugins=plugins, index=1)
        pl.get_next_plugin()
        assert pl.current_plugin_index == 0


# ---------------------------------------------------------------------------
# Playlist.get_next_eligible_plugin()
# ---------------------------------------------------------------------------

class TestGetNextEligiblePlugin:
    def test_all_snoozed_returns_none(self):
        plugins = [
            _plugin_dict("a", snooze_until=_future_snooze()),
            _plugin_dict("b", snooze_until=_future_snooze()),
        ]
        pl = _make_playlist("00:00", "24:00", plugins=plugins, index=0)
        original_index = pl.current_plugin_index
        result = pl.get_next_eligible_plugin(datetime.now(UTC))
        assert result is None
        assert pl.current_plugin_index == original_index

    def test_skips_snoozed_returns_next_eligible(self):
        plugins = [
            _plugin_dict("a"),
            _plugin_dict("b", snooze_until=_future_snooze()),
            _plugin_dict("c"),
        ]
        pl = _make_playlist("00:00", "24:00", plugins=plugins, index=0)
        result = pl.get_next_eligible_plugin(datetime.now(UTC))
        assert result is not None
        assert result.plugin_id != "b"

    def test_index_advances_to_eligible(self):
        plugins = [
            _plugin_dict("a"),
            _plugin_dict("b", snooze_until=_future_snooze()),
            _plugin_dict("c"),
        ]
        pl = _make_playlist("00:00", "24:00", plugins=plugins, index=0)
        pl.get_next_eligible_plugin(datetime.now(UTC))
        # Index should point to a non-snoozed plugin
        assert pl.plugins[pl.current_plugin_index].plugin_id != "b"


# ---------------------------------------------------------------------------
# Playlist.peek_next_eligible_plugin()
# ---------------------------------------------------------------------------

class TestPeekNextEligiblePlugin:
    def test_does_not_mutate_index(self):
        plugins = [_plugin_dict("a"), _plugin_dict("b"), _plugin_dict("c")]
        pl = _make_playlist("00:00", "24:00", plugins=plugins, index=1)
        original_index = pl.current_plugin_index
        pl.peek_next_eligible_plugin(datetime.now(UTC))
        assert pl.current_plugin_index == original_index

    def test_returns_eligible_plugin(self):
        plugins = [_plugin_dict("a"), _plugin_dict("b")]
        pl = _make_playlist("00:00", "24:00", plugins=plugins, index=0)
        result = pl.peek_next_eligible_plugin(datetime.now(UTC))
        assert result is not None

    def test_all_snoozed_does_not_mutate_index(self):
        plugins = [
            _plugin_dict("a", snooze_until=_future_snooze()),
            _plugin_dict("b", snooze_until=_future_snooze()),
        ]
        pl = _make_playlist("00:00", "24:00", plugins=plugins, index=0)
        original_index = pl.current_plugin_index
        result = pl.peek_next_eligible_plugin(datetime.now(UTC))
        assert result is None
        assert pl.current_plugin_index == original_index


# ---------------------------------------------------------------------------
# Playlist.reorder_plugins()
# ---------------------------------------------------------------------------

class TestReorderPlugins:
    def _pl_with_abc(self):
        plugins = [_plugin_dict("a", "Alpha"), _plugin_dict("b", "Beta"), _plugin_dict("c", "Gamma")]
        return _make_playlist("00:00", "24:00", plugins=plugins)

    def test_reorder_with_dicts(self):
        pl = self._pl_with_abc()
        result = pl.reorder_plugins([
            {"plugin_id": "c", "name": "Gamma"},
            {"plugin_id": "a", "name": "Alpha"},
            {"plugin_id": "b", "name": "Beta"},
        ])
        assert result is not False
        ids = [p.plugin_id for p in pl.plugins]
        assert ids == ["c", "a", "b"]

    def test_reorder_with_tuples(self):
        pl = self._pl_with_abc()
        result = pl.reorder_plugins([("c", "Gamma"), ("a", "Alpha"), ("b", "Beta")])
        assert result is not False
        ids = [p.plugin_id for p in pl.plugins]
        assert ids == ["c", "a", "b"]

    def test_too_few_items_returns_false(self):
        pl = self._pl_with_abc()
        result = pl.reorder_plugins([{"plugin_id": "a", "name": "Alpha"}])
        assert result is False

    def test_too_many_items_returns_false(self):
        pl = self._pl_with_abc()
        result = pl.reorder_plugins([
            {"plugin_id": "a", "name": "Alpha"},
            {"plugin_id": "b", "name": "Beta"},
            {"plugin_id": "c", "name": "Gamma"},
            {"plugin_id": "d", "name": "Delta"},
        ])
        assert result is False

    def test_unknown_plugin_id_returns_false(self):
        pl = self._pl_with_abc()
        result = pl.reorder_plugins([
            {"plugin_id": "x", "name": "X"},
            {"plugin_id": "a", "name": "Alpha"},
            {"plugin_id": "b", "name": "Beta"},
        ])
        assert result is False


# ---------------------------------------------------------------------------
# PluginInstance.should_refresh()
# ---------------------------------------------------------------------------

class TestShouldRefreshInterval:
    def test_refreshed_two_hours_ago_interval_one_hour(self):
        two_hours_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        d = _plugin_dict(refresh={"interval": 3600}, latest_refresh_time=two_hours_ago)
        plugin = PluginInstance.from_dict(d)
        assert plugin.should_refresh(datetime.now(UTC)) is True

    def test_refreshed_thirty_min_ago_interval_one_hour(self):
        thirty_min_ago = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        d = _plugin_dict(refresh={"interval": 3600}, latest_refresh_time=thirty_min_ago)
        plugin = PluginInstance.from_dict(d)
        assert plugin.should_refresh(datetime.now(UTC)) is False

    def test_never_refreshed_always_needs_refresh(self):
        d = _plugin_dict(refresh={"interval": 3600})
        plugin = PluginInstance.from_dict(d)
        assert plugin.should_refresh(datetime.now(UTC)) is True


class TestShouldRefreshScheduled:
    def test_scheduled_time_passed_last_refresh_yesterday(self):
        yesterday_early = (datetime.now(UTC).replace(hour=6, minute=0, second=0, microsecond=0)
                           - timedelta(days=1)).isoformat()
        d = _plugin_dict(refresh={"scheduled": "08:00"}, latest_refresh_time=yesterday_early)
        plugin = PluginInstance.from_dict(d)
        current_time = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)
        assert plugin.should_refresh(current_time) is True

    def test_scheduled_already_refreshed_today(self):
        today_8_30 = datetime.now(UTC).replace(hour=8, minute=30, second=0, microsecond=0).isoformat()
        d = _plugin_dict(refresh={"scheduled": "08:00"}, latest_refresh_time=today_8_30)
        plugin = PluginInstance.from_dict(d)
        current_time = datetime.now(UTC).replace(hour=9, minute=0, second=0, microsecond=0)
        assert plugin.should_refresh(current_time) is False


# ---------------------------------------------------------------------------
# PluginInstance.is_show_eligible()
# ---------------------------------------------------------------------------

class TestIsShowEligible:
    def test_active_snooze_returns_false(self):
        d = _plugin_dict(snooze_until=_future_snooze())
        plugin = PluginInstance.from_dict(d)
        assert plugin.is_show_eligible(datetime.now(UTC)) is False

    def test_expired_snooze_returns_true(self):
        d = _plugin_dict(snooze_until=_past_snooze())
        plugin = PluginInstance.from_dict(d)
        assert plugin.is_show_eligible(datetime.now(UTC)) is True

    def test_only_show_when_fresh_not_due_returns_false(self):
        # Refreshed 30 min ago with 1 hour interval — not due for refresh → ineligible
        thirty_min_ago = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        d = _plugin_dict(
            refresh={"interval": 3600},
            latest_refresh_time=thirty_min_ago,
            only_show_when_fresh=True,
        )
        plugin = PluginInstance.from_dict(d)
        assert plugin.is_show_eligible(datetime.now(UTC)) is False

    def test_only_show_when_fresh_due_returns_true(self):
        # Refreshed 2 hours ago with 1 hour interval — due for refresh → eligible
        two_hours_ago = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
        d = _plugin_dict(
            refresh={"interval": 3600},
            latest_refresh_time=two_hours_ago,
            only_show_when_fresh=True,
        )
        plugin = PluginInstance.from_dict(d)
        assert plugin.is_show_eligible(datetime.now(UTC)) is True

    def test_no_snooze_no_only_fresh_returns_true(self):
        d = _plugin_dict()
        plugin = PluginInstance.from_dict(d)
        assert plugin.is_show_eligible(datetime.now(UTC)) is True


# ---------------------------------------------------------------------------
# PluginInstance.from_dict() round-trip
# ---------------------------------------------------------------------------

class TestFromDictRoundTrip:
    def test_round_trip_preserves_fields(self):
        snooze = _future_snooze()
        original_dict = _plugin_dict(
            pid="rt_test",
            name="RoundTrip",
            refresh={"interval": 7200},
            only_show_when_fresh=True,
            snooze_until=snooze,
        )
        plugin = PluginInstance.from_dict(original_dict)
        round_trip_dict = plugin.to_dict()
        plugin2 = PluginInstance.from_dict(round_trip_dict)

        assert plugin2.plugin_id == "rt_test"
        assert plugin2.name == "RoundTrip"
        assert plugin2.only_show_when_fresh is True
        assert plugin2.snooze_until == plugin.snooze_until

    def test_from_dict_defaults(self):
        d = _plugin_dict()
        plugin = PluginInstance.from_dict(d)
        assert plugin.only_show_when_fresh is False
        assert plugin.snooze_until is None
        assert plugin.latest_refresh_time is None
