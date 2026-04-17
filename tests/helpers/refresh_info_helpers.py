"""Helpers for composing RefreshInfo objects in tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def seed_future_refresh_info(device_config, *, days_ahead: int = 90) -> str:
    """Store a future-dated refresh record for clock-skew scenarios."""
    from model import RefreshInfo

    future_ts = (datetime.now(UTC) + timedelta(days=days_ahead)).isoformat()
    device_config.refresh_info = RefreshInfo(
        refresh_type="Playlist",
        plugin_id="clock",
        refresh_time=future_ts,
        image_hash="future-hash",
        playlist="Default",
        plugin_instance="Clock",
    )
    return future_ts
