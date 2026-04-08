# pyright: reportMissingImports=false
from datetime import UTC, datetime

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
    now = datetime.now(tz=UTC)
    ri = RefreshInfo("Manual Update", "ai_text", now.isoformat(), 123)
    assert ri.get_refresh_datetime().date() == now.date()
    d = ri.to_dict()
    ri2 = RefreshInfo.from_dict(d)
    assert ri2.plugin_id == "ai_text"


def test_add_default_playlist_returns_true_and_grows_list():
    pm = PlaylistManager([])
    before = len(pm.playlists)
    result = pm.add_default_playlist()
    assert result is True
    assert len(pm.playlists) == before + 1


# ---------------------------------------------------------------------------
# Tests for PluginInstance.update() allowlist (JTN-230)
# ---------------------------------------------------------------------------


class TestPluginInstanceUpdateAllowlist:
    """PluginInstance.update() should only apply fields in _UPDATABLE."""

    def _make_pi(self):
        return PluginInstance(
            plugin_id="weather",
            name="main",
            settings={"city": "London"},
            refresh={"interval": 300},
            latest_refresh_time=None,
            only_show_when_fresh=False,
            snooze_until=None,
        )

    def test_update_settings_allowed(self):
        pi = self._make_pi()
        pi.update({"settings": {"city": "Paris"}})
        assert pi.settings == {"city": "Paris"}

    def test_update_refresh_allowed(self):
        pi = self._make_pi()
        pi.update({"refresh": {"interval": 600}})
        assert pi.refresh == {"interval": 600}

    def test_update_latest_refresh_time_allowed(self):
        pi = self._make_pi()
        ts = "2024-01-01T12:00:00"
        pi.update({"latest_refresh_time": ts})
        assert pi.latest_refresh_time == ts

    def test_update_only_show_when_fresh_allowed(self):
        pi = self._make_pi()
        pi.update({"only_show_when_fresh": True})
        assert pi.only_show_when_fresh is True

    def test_update_snooze_until_allowed(self):
        pi = self._make_pi()
        ts = "2024-06-01T08:00:00"
        pi.update({"snooze_until": ts})
        assert pi.snooze_until == ts

    def test_update_name_allowed(self):
        pi = self._make_pi()
        pi.update({"name": "Renamed"})
        assert pi.name == "Renamed"

    def test_update_unknown_key_silently_ignored(self):
        """Unknown keys must not raise and must not be applied."""
        pi = self._make_pi()
        pi.update({"evil_key": "evil_value"})
        assert not hasattr(pi, "evil_key")

    def test_update_plugin_id_injection_blocked(self):
        """plugin_id is not in _UPDATABLE and must not be overwritten."""
        pi = self._make_pi()
        pi.update({"plugin_id": "injected"})
        assert pi.plugin_id == "weather"

    def test_update_mixed_allowed_and_unknown(self):
        """Allowed fields are applied; unknown fields are ignored."""
        pi = self._make_pi()
        pi.update(
            {
                "settings": {"city": "Tokyo"},
                "plugin_id": "evil",
                "__class__": "hacked",
            }
        )
        assert pi.settings == {"city": "Tokyo"}
        assert pi.plugin_id == "weather"
        assert not hasattr(pi, "__class__") or pi.__class__ is PluginInstance

    def test_playlist_update_plugin_end_to_end(self):
        """Playlist.update_plugin() still applies legitimate settings correctly."""
        pl = Playlist(
            "Default",
            "00:00",
            "24:00",
            plugins=[
                {
                    "plugin_id": "clock",
                    "name": "desk",
                    "plugin_settings": {"format": "12h"},
                    "refresh": {"interval": 60},
                }
            ],
        )
        result = pl.update_plugin(
            "clock",
            "desk",
            {"settings": {"format": "24h"}, "refresh": {"interval": 120}},
        )
        assert result is True
        plugin = pl.find_plugin("clock", "desk")
        assert plugin is not None
        assert plugin.settings == {"format": "24h"}
        assert plugin.refresh == {"interval": 120}

    def test_playlist_update_plugin_blocks_id_injection(self):
        """Passing plugin_id in updated_data must not overwrite the stored id."""
        pl = Playlist(
            "Default",
            "00:00",
            "24:00",
            plugins=[
                {
                    "plugin_id": "clock",
                    "name": "desk",
                    "plugin_settings": {},
                    "refresh": {},
                }
            ],
        )
        pl.update_plugin("clock", "desk", {"plugin_id": "evil", "settings": {"x": 1}})
        plugin = pl.find_plugin("clock", "desk")
        assert plugin is not None
        assert plugin.plugin_id == "clock"
        assert plugin.settings == {"x": 1}
