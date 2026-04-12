# pyright: reportMissingImports=false
"""Tests for the utils.refresh_info.RefreshInfoRepository."""

from model import RefreshInfo
from utils.refresh_info import RefreshInfoRepository


class TestRefreshInfoRepository:
    def test_load_valid_data(self):
        data = {
            "refresh_type": "Manual Update",
            "plugin_id": "clock",
            "refresh_time": "2025-01-01T00:00:00",
            "image_hash": "abc123",
        }
        repo = RefreshInfoRepository(data)
        ri = repo.get()
        assert isinstance(ri, RefreshInfo)
        assert ri.refresh_type == "Manual Update"
        assert ri.plugin_id == "clock"
        assert ri.refresh_time == "2025-01-01T00:00:00"
        assert ri.image_hash == "abc123"

    def test_load_none_falls_back_to_defaults(self):
        repo = RefreshInfoRepository(None)
        ri = repo.get()
        assert ri.refresh_type == "Manual Update"
        assert ri.plugin_id == ""
        assert ri.refresh_time is None
        assert ri.image_hash is None

    def test_load_empty_dict_falls_back_to_defaults(self):
        repo = RefreshInfoRepository({})
        ri = repo.get()
        assert ri.refresh_type == "Manual Update"
        assert ri.plugin_id == ""

    def test_load_missing_keys_falls_back(self):
        repo = RefreshInfoRepository({"refresh_type": "Playlist"})
        ri = repo.get()
        assert ri.refresh_type == "Manual Update"  # fell back to default

    def test_set_replaces_refresh_info(self):
        repo = RefreshInfoRepository(None)
        new_ri = RefreshInfo("Playlist", "weather", "2025-06-01T12:00:00", "xyz")
        repo.set(new_ri)
        assert repo.get() is new_ri

    def test_to_dict_round_trip(self):
        data = {
            "refresh_type": "Playlist",
            "plugin_id": "weather",
            "refresh_time": "2025-06-01T12:00:00",
            "image_hash": "xyz",
            "playlist": "Default",
            "plugin_instance": "Weather 1",
        }
        repo = RefreshInfoRepository(data)
        result = repo.to_dict()
        assert result["refresh_type"] == "Playlist"
        assert result["plugin_id"] == "weather"
        assert result["playlist"] == "Default"
        assert result["plugin_instance"] == "Weather 1"
