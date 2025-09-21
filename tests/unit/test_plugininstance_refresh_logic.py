from datetime import datetime, timezone, timedelta

from model import PluginInstance


def test_should_refresh_interval_and_initial():
    inst = PluginInstance("x", "A", {}, {"interval": 60}, latest_refresh_time=None)
    now = datetime.now(timezone.utc)
    # No latest -> should refresh
    assert inst.should_refresh(now) is True

    # Set last refresh to long ago -> should refresh
    inst.latest_refresh_time = (now - timedelta(seconds=120)).isoformat()
    assert inst.should_refresh(now) is True

    # Set last refresh recent -> may not refresh
    inst.latest_refresh_time = (now - timedelta(seconds=10)).isoformat()
    assert inst.should_refresh(now) is False


def test_should_refresh_scheduled_with_tz_alignment():
    # Schedule at current minute; last refresh earlier today should trigger
    now = datetime.now(timezone.utc)
    hhmm = now.strftime("%H:%M")
    inst = PluginInstance("x", "A", {}, {"scheduled": hhmm}, latest_refresh_time=(now - timedelta(hours=1)).isoformat())
    assert inst.should_refresh(now) is True

    # Last refresh after scheduled -> should not refresh
    inst.latest_refresh_time = (now + timedelta(minutes=1)).isoformat()
    assert inst.should_refresh(now) is False

