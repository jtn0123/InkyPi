# pyright: reportMissingImports=false
"""Tests for Playlist.is_active() and PlaylistManager.determine_active_playlist()."""

from datetime import datetime

from model import Playlist, PlaylistManager

# ---------------------------------------------------------------------------
# Playlist.is_active() — normal ranges
# ---------------------------------------------------------------------------


class TestIsActiveNormalRange:
    """Start < end (no midnight wraparound)."""

    def test_within_range(self):
        pl = Playlist("Day", "08:00", "20:00")
        assert pl.is_active("12:00") is True

    def test_at_start_boundary(self):
        pl = Playlist("Day", "08:00", "20:00")
        assert pl.is_active("08:00") is True  # inclusive start

    def test_at_end_boundary(self):
        pl = Playlist("Day", "08:00", "20:00")
        assert pl.is_active("20:00") is False  # exclusive end

    def test_before_range(self):
        pl = Playlist("Day", "08:00", "20:00")
        assert pl.is_active("07:59") is False

    def test_after_range(self):
        pl = Playlist("Day", "08:00", "20:00")
        assert pl.is_active("20:01") is False


# ---------------------------------------------------------------------------
# Playlist.is_active() — midnight wraparound (start > end)
# ---------------------------------------------------------------------------


class TestIsActiveWraparound:
    """Start > end wraps across midnight."""

    def test_before_midnight(self):
        pl = Playlist("Night", "22:00", "06:00")
        assert pl.is_active("23:00") is True

    def test_after_midnight(self):
        pl = Playlist("Night", "22:00", "06:00")
        assert pl.is_active("03:00") is True

    def test_at_start_boundary(self):
        pl = Playlist("Night", "22:00", "06:00")
        assert pl.is_active("22:00") is True  # inclusive start

    def test_at_end_boundary(self):
        pl = Playlist("Night", "22:00", "06:00")
        assert pl.is_active("06:00") is False  # exclusive end

    def test_outside_range_midday(self):
        pl = Playlist("Night", "22:00", "06:00")
        assert pl.is_active("12:00") is False

    def test_just_before_start(self):
        pl = Playlist("Night", "22:00", "06:00")
        assert pl.is_active("21:59") is False

    def test_just_after_end(self):
        pl = Playlist("Night", "22:00", "06:00")
        assert pl.is_active("06:01") is False


# ---------------------------------------------------------------------------
# Playlist.is_active() — full-day and edge cases
# ---------------------------------------------------------------------------


class TestIsActiveEdgeCases:
    def test_full_day_range(self):
        pl = Playlist("AllDay", "00:00", "24:00")
        assert pl.is_active("00:00") is True
        assert pl.is_active("12:00") is True
        assert pl.is_active("23:59") is True

    def test_same_start_end_is_never_active(self):
        """When start == end the range is empty."""
        pl = Playlist("Empty", "12:00", "12:00")
        assert pl.is_active("12:00") is False
        assert pl.is_active("11:59") is False
        assert pl.is_active("12:01") is False

    def test_one_minute_range(self):
        pl = Playlist("Tiny", "12:00", "12:01")
        assert pl.is_active("12:00") is True
        assert pl.is_active("12:01") is False
        assert pl.is_active("11:59") is False


# ---------------------------------------------------------------------------
# PlaylistManager.determine_active_playlist()
# ---------------------------------------------------------------------------


class TestDetermineActivePlaylist:
    def _make_pm(self, playlists):
        pm = PlaylistManager(playlists=[])
        pm.playlists = playlists
        return pm

    def test_no_playlists_returns_none(self):
        pm = self._make_pm([])
        dt = datetime(2025, 6, 15, 12, 0)
        assert pm.determine_active_playlist(dt) is None

    def test_no_active_playlists_returns_none(self):
        pl = Playlist("Morning", "06:00", "10:00")
        pm = self._make_pm([pl])
        dt = datetime(2025, 6, 15, 14, 0)  # 14:00, outside 06-10
        assert pm.determine_active_playlist(dt) is None

    def test_single_active_playlist(self):
        pl = Playlist("Morning", "06:00", "10:00")
        pm = self._make_pm([pl])
        dt = datetime(2025, 6, 15, 8, 0)  # 08:00
        assert pm.determine_active_playlist(dt) is pl

    def test_multiple_active_prefers_shorter_range(self):
        """Shorter time range = higher priority (lower get_priority value)."""
        broad = Playlist("AllDay", "00:00", "24:00")  # 1440 min
        narrow = Playlist("Morning", "08:00", "10:00")  # 120 min
        pm = self._make_pm([broad, narrow])
        dt = datetime(2025, 6, 15, 9, 0)  # 09:00 — both active
        result = pm.determine_active_playlist(dt)
        assert result is narrow

    def test_multiple_active_order_independent(self):
        """Result should be the same regardless of insertion order."""
        broad = Playlist("AllDay", "00:00", "24:00")
        narrow = Playlist("Lunch", "11:00", "13:00")
        # Reverse insertion order
        pm = self._make_pm([narrow, broad])
        dt = datetime(2025, 6, 15, 12, 0)
        assert pm.determine_active_playlist(dt) is narrow

    def test_wraparound_playlist_active_at_midnight(self):
        night = Playlist("Night", "22:00", "06:00")
        pm = self._make_pm([night])
        dt = datetime(2025, 6, 15, 23, 30)  # 23:30
        assert pm.determine_active_playlist(dt) is night

    def test_wraparound_not_active_midday(self):
        night = Playlist("Night", "22:00", "06:00")
        pm = self._make_pm([night])
        dt = datetime(2025, 6, 15, 12, 0)
        assert pm.determine_active_playlist(dt) is None
