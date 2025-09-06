# pyright: reportMissingImports=false
from datetime import datetime

import pytz

from model import Playlist, PlaylistManager, PluginInstance, RefreshInfo


def test_playlist_manager_serialization_roundtrip():
    p1 = Playlist(
        "Morning",
        "06:00",
        "09:00",
        plugins=[
            {
                "plugin_id": "x",
                "name": "inst",
                "plugin_settings": {"a": 1},
                "refresh": {"interval": 60},
            }
        ],
    )
    pm = PlaylistManager([p1], active_playlist="Morning")

    data = pm.to_dict()
    pm2 = PlaylistManager.from_dict(data)
    assert pm2.active_playlist == "Morning"
    assert pm2.get_playlist("Morning") is not None


def test_playlist_update_and_delete():
    pm = PlaylistManager([])
    pm.add_playlist("P1", "01:00", "02:00")
    assert pm.get_playlist("P1") is not None
    assert pm.update_playlist("P1", "P2", "01:00", "03:00") is True
    assert pm.get_playlist("P1") is None
    assert pm.get_playlist("P2") is not None
    pm.delete_playlist("P2")
    assert pm.get_playlist("P2") is None


def test_plugin_instance_update_and_image_path():
    pi = PluginInstance("x", "My Inst", {}, {"interval": 300}, latest_refresh_time=None)
    assert pi.get_image_path() == "x_My_Inst.png"
    pi.update({"name": "New Name"})
    assert pi.name == "New Name"


def test_refresh_info_helpers():
    now = datetime.now(tz=pytz.UTC)
    ri = RefreshInfo("Manual Update", "ai_text", now.isoformat(), 123)
    assert ri.get_refresh_datetime().date() == now.date()
    d = ri.to_dict()
    ri2 = RefreshInfo.from_dict(d)
    assert ri2.plugin_id == "ai_text"
