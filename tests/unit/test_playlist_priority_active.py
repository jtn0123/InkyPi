from datetime import datetime

from model import Playlist, PlaylistManager


def test_determine_active_playlist_midnight_wrap():
    # Playlist A active 23:00-01:00 (wraps), B active 01:00-23:00
    a = Playlist("A", "23:00", "01:00", plugins=[])
    b = Playlist("B", "01:00", "23:00", plugins=[])
    pm = PlaylistManager([a, b])

    # 00:30 should be within A
    dt = datetime.strptime("00:30", "%H:%M")
    active = pm.determine_active_playlist(dt)
    assert active is not None and active.name == "A"


def test_priority_prefers_shorter_range():
    # Priority uses time range minutes; smaller range = higher priority
    a = Playlist("Short", "10:00", "11:00", plugins=[{"plugin_id":"x","name":"X","plugin_settings":{},"refresh":{}}])
    b = Playlist("Long", "00:00", "24:00", plugins=[{"plugin_id":"y","name":"Y","plugin_settings":{},"refresh":{}}])
    pm = PlaylistManager([a, b])
    dt = datetime.strptime("10:30", "%H:%M")
    active = pm.determine_active_playlist(dt)
    assert active is not None and active.name == "Short"

