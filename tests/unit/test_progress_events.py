# pyright: reportMissingImports=false
"""Tests for utils/progress_events.py — ProgressEventBus and helpers."""

import json
import threading
import time

from utils.progress_events import ProgressEventBus, get_progress_bus, to_sse


# ---- publish() ----


def test_publish_returns_event_with_seq():
    bus = ProgressEventBus()
    evt = bus.publish({"msg": "hello"})
    assert evt["seq"] == 1
    assert evt["msg"] == "hello"
    assert "ts" in evt


def test_publish_increments_seq():
    bus = ProgressEventBus()
    e1 = bus.publish({"step": 1})
    e2 = bus.publish({"step": 2})
    e3 = bus.publish({"step": 3})
    assert e1["seq"] == 1
    assert e2["seq"] == 2
    assert e3["seq"] == 3


def test_publish_preserves_payload_keys():
    bus = ProgressEventBus()
    evt = bus.publish({"type": "progress", "pct": 50})
    assert evt["type"] == "progress"
    assert evt["pct"] == 50


def test_publish_respects_max_events():
    bus = ProgressEventBus(max_events=3)
    for i in range(5):
        bus.publish({"i": i})
    events = bus.recent(limit=10)
    assert len(events) == 3
    # Oldest events evicted; newest remain
    assert events[0]["i"] == 2
    assert events[2]["i"] == 4


# ---- recent() ----


def test_recent_returns_recent_events():
    bus = ProgressEventBus()
    for i in range(10):
        bus.publish({"i": i})
    recent = bus.recent(limit=3)
    assert len(recent) == 3
    assert recent[0]["i"] == 7
    assert recent[2]["i"] == 9


def test_recent_returns_all_when_limit_exceeds_count():
    bus = ProgressEventBus()
    bus.publish({"a": 1})
    bus.publish({"a": 2})
    recent = bus.recent(limit=100)
    assert len(recent) == 2


def test_recent_returns_empty_for_zero_limit():
    bus = ProgressEventBus()
    bus.publish({"a": 1})
    assert bus.recent(limit=0) == []


def test_recent_returns_empty_for_negative_limit():
    bus = ProgressEventBus()
    bus.publish({"a": 1})
    assert bus.recent(limit=-5) == []


def test_recent_returns_empty_when_no_events():
    bus = ProgressEventBus()
    assert bus.recent() == []


# ---- wait_for() ----


def test_wait_for_returns_new_events_immediately():
    bus = ProgressEventBus()
    bus.publish({"step": "first"})
    bus.publish({"step": "second"})
    result = bus.wait_for(last_seq=0, timeout_s=0.1)
    assert len(result) == 2


def test_wait_for_filters_by_seq():
    bus = ProgressEventBus()
    bus.publish({"step": 1})
    bus.publish({"step": 2})
    bus.publish({"step": 3})
    result = bus.wait_for(last_seq=2, timeout_s=0.1)
    assert len(result) == 1
    assert result[0]["step"] == 3


def test_wait_for_blocks_then_returns_on_publish():
    bus = ProgressEventBus()
    results = []

    def waiter():
        results.extend(bus.wait_for(last_seq=0, timeout_s=5.0))

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.01)
    bus.publish({"msg": "wakeup"})
    t.join(timeout=2.0)
    assert len(results) == 1
    assert results[0]["msg"] == "wakeup"


def test_wait_for_times_out_returns_empty():
    bus = ProgressEventBus()
    start = time.monotonic()
    result = bus.wait_for(last_seq=0, timeout_s=0.1)
    elapsed = time.monotonic() - start
    assert result == []
    assert elapsed >= 0.08  # approximately respected timeout


# ---- to_sse() ----


def test_to_sse_formats_event_type_and_data():
    payload = {"seq": 1, "msg": "hi"}
    output = to_sse("progress", payload)
    assert output.startswith("event: progress\n")
    assert "data: " in output
    assert output.endswith("\n\n")
    # Parse the data line
    data_line = [l for l in output.split("\n") if l.startswith("data:")][0]
    data_json = json.loads(data_line[len("data: "):])
    assert data_json["seq"] == 1
    assert data_json["msg"] == "hi"


def test_to_sse_uses_compact_json():
    output = to_sse("test", {"a": 1, "b": 2})
    data_line = [l for l in output.split("\n") if l.startswith("data:")][0]
    # Compact separators: no spaces after , or :
    assert '" :' not in data_line
    assert '", ' not in data_line


# ---- get_progress_bus() ----


def test_get_progress_bus_returns_singleton():
    bus1 = get_progress_bus()
    bus2 = get_progress_bus()
    assert bus1 is bus2


def test_get_progress_bus_is_instance():
    bus = get_progress_bus()
    assert isinstance(bus, ProgressEventBus)


# ---- Thread safety ----


def test_concurrent_publishes_no_lost_events():
    bus = ProgressEventBus(max_events=2000)
    n_threads = 10
    n_per_thread = 100
    barrier = threading.Barrier(n_threads)

    def publisher():
        barrier.wait()
        for _ in range(n_per_thread):
            bus.publish({"t": threading.current_thread().name})

    threads = [threading.Thread(target=publisher) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    events = bus.recent(limit=n_threads * n_per_thread)
    assert len(events) == n_threads * n_per_thread
    # Sequence numbers should be unique and sequential
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, n_threads * n_per_thread + 1))


def test_concurrent_publish_and_wait():
    """Ensure wait_for correctly wakes when a concurrent publish happens."""
    bus = ProgressEventBus()
    results = []

    def waiter():
        r = bus.wait_for(last_seq=0, timeout_s=5.0)
        results.extend(r)

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.01)
    bus.publish({"concurrent": True})
    t.join(timeout=2.0)
    assert len(results) >= 1
    assert results[0]["concurrent"] is True
