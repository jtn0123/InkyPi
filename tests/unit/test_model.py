from datetime import datetime, timedelta

import pytz

import model
from model import Playlist, PlaylistManager, PluginInstance


def test_refresh_info_to_from_dict_and_datetime():
    now_iso = datetime.utcnow().isoformat()
    ri = model.RefreshInfo(
        refresh_type="Manual Update",
        plugin_id="p1",
        refresh_time=now_iso,
        image_hash=123,
    )
    d = ri.to_dict()
    assert d["refresh_time"] == now_iso
    assert d["image_hash"] == 123

    ri2 = model.RefreshInfo.from_dict(d)
    assert ri2.refresh_time == now_iso
    assert ri2.get_refresh_datetime() == datetime.fromisoformat(now_iso)


def test_playlist_and_plugininstance_basic_operations():
    # Create plugin instances
    pdata = {
        "plugin_id": "weather",
        "name": "main",
        "plugin_settings": {"k": "v"},
        "refresh": {},
    }
    plugin = model.PluginInstance.from_dict(pdata)
    assert plugin.plugin_id == "weather"
    assert plugin.get_image_path().endswith("weather_main.png")

    # Test should_refresh with no latest refresh -> True
    now = datetime.utcnow()
    assert plugin.should_refresh(now) is True

    # Set latest refresh and test interval-based refresh
    plugin.latest_refresh_time = (now - timedelta(seconds=10)).isoformat()
    plugin.refresh = {"interval": 5}
    assert plugin.should_refresh(now) is True

    plugin.refresh = {"interval": 1000}
    assert plugin.should_refresh(now) is False

    # Scheduled refresh behavior
    plugin.latest_refresh_time = (now - timedelta(days=1)).isoformat()
    plugin.refresh = {"scheduled": now.strftime("%H:%M")}
    assert plugin.should_refresh(now) is True


def test_playlist_cycle_and_priority():
    # Playlist with two plugins
    plugins = [
        {"plugin_id": "a", "name": "one", "plugin_settings": {}, "refresh": {}},
        {"plugin_id": "b", "name": "two", "plugin_settings": {}, "refresh": {}},
    ]
    pl = model.Playlist("P1", "08:00", "10:00", plugins=plugins)
    # get_next_plugin initializes index
    first = pl.get_next_plugin()
    assert first.plugin_id == "a"
    second = pl.get_next_plugin()
    assert second.plugin_id == "b"

    # Corrupt index should reset to 0
    pl.current_plugin_index = 999
    nxt = pl.get_next_plugin()
    assert nxt.plugin_id in ("a", "b")

    # Time range minutes
    assert pl.get_time_range_minutes() == 120
    assert pl.get_priority() == 120


def test_playlist_manager_operations():
    pm = model.PlaylistManager()
    pm.add_playlist("day", "00:00", "24:00")
    assert pm.get_playlist("day") is not None
    assert pm.get_playlist_names() == ["day"]

    # Add plugin to playlist
    pdata = {"plugin_id": "x", "name": "one", "plugin_settings": {}, "refresh": {}}
    added = pm.add_plugin_to_playlist("day", pdata)
    assert added is True

    # Update playlist
    updated = pm.update_playlist("day", "day2", "01:00", "02:00")
    assert updated is True
    assert pm.get_playlist("day2") is not None

    # Delete playlist
    pm.delete_playlist("day2")
    assert pm.get_playlist("day2") is None

    # should_refresh utility
    assert model.PlaylistManager.should_refresh(None, 10, datetime.utcnow()) is True
    latest = datetime.utcnow()
    assert (
        model.PlaylistManager.should_refresh(latest, 10, latest + timedelta(seconds=11))
        is True
    )
    assert (
        model.PlaylistManager.should_refresh(latest, 10, latest + timedelta(seconds=5))
        is False
    )


# pyright: reportMissingImports=false


def test_should_refresh_interval_true():
    now = datetime(2025, 1, 1, 12, 0, 0)
    last = now - timedelta(seconds=3601)
    assert PlaylistManager.should_refresh(last, 3600, now) is True


def test_should_refresh_interval_false():
    now = datetime(2025, 1, 1, 12, 0, 0)
    last = now - timedelta(seconds=3599)
    assert PlaylistManager.should_refresh(last, 3600, now) is False


def test_determine_active_playlist_priority():
    tz = pytz.UTC
    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=tz)
    p1 = Playlist(
        "All Day",
        "00:00",
        "24:00",
        plugins=[
            {
                "plugin_id": "x",
                "name": "a",
                "plugin_settings": {},
                "refresh": {"interval": 300},
            }
        ],
    )
    p2 = Playlist(
        "Lunch",
        "11:30",
        "13:30",
        plugins=[
            {
                "plugin_id": "x",
                "name": "b",
                "plugin_settings": {},
                "refresh": {"interval": 300},
            }
        ],
    )
    pm = PlaylistManager([p1, p2])
    active = pm.determine_active_playlist(now)
    assert active.name == "Lunch"


def test_plugin_instance_should_refresh_interval_and_scheduled():
    tz = pytz.UTC
    now = datetime(2025, 1, 1, 13, 0, 0, tzinfo=tz)
    pi = PluginInstance(
        "x",
        "inst",
        {},
        {"interval": 300},
        latest_refresh_time=(now - timedelta(seconds=301)).isoformat(),
    )
    assert pi.should_refresh(now) is True

    # With scheduled in the past today -> True if not refreshed yet after schedule
    pi = PluginInstance(
        "x",
        "inst",
        {},
        {"scheduled": "12:00"},
        latest_refresh_time=(now - timedelta(hours=2)).isoformat(),
    )
    assert pi.should_refresh(now) is True


def test_get_time_range_minutes():
    p = Playlist("Morning", "06:00", "09:30")
    assert p.get_time_range_minutes() == 210
