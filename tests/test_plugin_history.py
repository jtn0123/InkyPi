"""Tests for plugin instance config history and diff (JTN-479)."""

from __future__ import annotations

import json
import os
import urllib.parse

import pytest

# ---------------------------------------------------------------------------
# Unit tests for utils/plugin_history.py
# ---------------------------------------------------------------------------


@pytest.fixture()
def config_dir(tmp_path):
    """Return a temp directory to use as config_dir."""
    return str(tmp_path)


def _hist_file_for(config_dir, instance_name):
    """Helper that mirrors plugin_history._history_file for test assertions."""
    from utils.plugin_history import _history_file

    return _history_file(config_dir, instance_name)


def test_record_change_creates_file(config_dir):
    from utils.plugin_history import record_change

    record_change(config_dir, "my_plugin", {"key": "old"}, {"key": "new"})

    hist_file = _hist_file_for(config_dir, "my_plugin")
    assert os.path.isfile(hist_file)
    with open(hist_file) as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["instance"] == "my_plugin"
    assert entry["before"] == {"key": "old"}
    assert entry["after"] == {"key": "new"}
    assert "ts" in entry


def test_record_change_appends(config_dir):
    from utils.plugin_history import record_change

    record_change(config_dir, "inst", {"a": 1}, {"a": 2})
    record_change(config_dir, "inst", {"a": 2}, {"a": 3})

    hist_file = _hist_file_for(config_dir, "inst")
    with open(hist_file) as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    assert len(lines) == 2


def test_get_history_returns_newest_first(config_dir):
    from utils.plugin_history import get_history, record_change

    for i in range(5):
        record_change(config_dir, "inst", {"v": i}, {"v": i + 1})

    history = get_history(config_dir, "inst", limit=10)
    assert len(history) == 5
    # Newest-first: last recorded change should appear first
    assert history[0]["after"] == {"v": 5}
    assert history[-1]["after"] == {"v": 1}


def test_get_history_respects_limit(config_dir):
    from utils.plugin_history import get_history, record_change

    for i in range(10):
        record_change(config_dir, "inst", {"v": i}, {"v": i + 1})

    history = get_history(config_dir, "inst", limit=3)
    assert len(history) == 3
    # Most-recent 3 should be returned
    assert history[0]["after"] == {"v": 10}


def test_get_history_returns_empty_for_missing_instance(config_dir):
    from utils.plugin_history import get_history

    result = get_history(config_dir, "no_such_instance")
    assert result == []


def test_truncation_at_max_entries(config_dir):
    """Writing more than MAX_ENTRIES records should drop the oldest."""
    from utils.plugin_history import MAX_ENTRIES, get_history, record_change

    total = MAX_ENTRIES + 10
    for i in range(total):
        record_change(config_dir, "inst", {"v": i}, {"v": i + 1})

    # File should contain exactly MAX_ENTRIES lines
    hist_file = _hist_file_for(config_dir, "inst")
    with open(hist_file) as fh:
        lines = [ln.strip() for ln in fh if ln.strip()]
    assert len(lines) == MAX_ENTRIES

    # The newest entry must be the very last recorded
    history = get_history(config_dir, "inst", limit=1)
    assert history[0]["after"] == {"v": total}

    # The oldest retained entry should be the (total - MAX_ENTRIES + 1)-th change
    all_history = get_history(config_dir, "inst", limit=MAX_ENTRIES)
    assert len(all_history) == MAX_ENTRIES
    # Oldest retained: index -1 (newest-first order), after value = total - MAX_ENTRIES + 1
    assert all_history[-1]["after"] == {"v": total - MAX_ENTRIES + 1}


def test_compute_diff_added(config_dir):
    from utils.plugin_history import compute_diff

    diff = compute_diff({}, {"new_key": "value"})
    assert diff["added"] == {"new_key": "value"}
    assert diff["removed"] == {}
    assert diff["changed"] == {}


def test_compute_diff_removed():
    from utils.plugin_history import compute_diff

    diff = compute_diff({"old_key": "value"}, {})
    assert diff["added"] == {}
    assert diff["removed"] == {"old_key": "value"}
    assert diff["changed"] == {}


def test_compute_diff_changed():
    from utils.plugin_history import compute_diff

    diff = compute_diff({"k": "before"}, {"k": "after"})
    assert diff["added"] == {}
    assert diff["removed"] == {}
    assert diff["changed"] == {"k": {"before": "before", "after": "after"}}


def test_compute_diff_no_change():
    from utils.plugin_history import compute_diff

    diff = compute_diff({"k": "same"}, {"k": "same"})
    assert diff == {"added": {}, "removed": {}, "changed": {}}


def test_compute_diff_mixed():
    from utils.plugin_history import compute_diff

    before = {"a": 1, "b": 2, "c": 3}
    after = {"a": 10, "b": 2, "d": 4}
    diff = compute_diff(before, after)
    assert diff["added"] == {"d": 4}
    assert diff["removed"] == {"c": 3}
    assert diff["changed"] == {"a": {"before": 1, "after": 10}}


# ---------------------------------------------------------------------------
# Endpoint tests (use flask_app fixture from conftest.py)
# ---------------------------------------------------------------------------


def _add_plugin_instance(flask_app, instance_name: str):
    """Helper: add a plugin instance to the Default playlist via the app config."""
    device_config = flask_app.config["DEVICE_CONFIG"]
    pm = device_config.get_playlist_manager()
    default = pm.get_playlist("Default")
    if default is None:
        pm.add_playlist("Default")
        default = pm.get_playlist("Default")
    default.add_plugin(
        {
            "plugin_id": "clock",
            "refresh": {"interval": 3600},
            "plugin_settings": {"color": "white"},
            "name": instance_name,
        }
    )
    device_config.write_config()


def _write_history(flask_app, instance_name: str, entries: int = 3):
    """Write *entries* history records for *instance_name* via the utility."""
    import os

    from utils.plugin_history import record_change

    device_config = flask_app.config["DEVICE_CONFIG"]
    config_dir = os.path.dirname(device_config.config_file)
    for i in range(entries):
        record_change(
            config_dir,
            instance_name,
            {"color": f"color_{i}"},
            {"color": f"color_{i + 1}"},
        )


def test_history_endpoint_returns_json(flask_app):
    client = flask_app.test_client()
    instance_name = "clock_test"
    _add_plugin_instance(flask_app, instance_name)
    _write_history(flask_app, instance_name, entries=3)

    resp = client.get(f"/api/plugins/instance/{instance_name}/history")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["instance"] == instance_name
    assert isinstance(data["history"], list)
    assert len(data["history"]) == 3


def test_history_endpoint_limit_param(flask_app):
    client = flask_app.test_client()
    instance_name = "clock_limited"
    _add_plugin_instance(flask_app, instance_name)
    _write_history(flask_app, instance_name, entries=5)

    resp = client.get(f"/api/plugins/instance/{instance_name}/history?limit=2")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data["history"]) == 2


def test_history_endpoint_404_for_unknown_instance(flask_app):
    client = flask_app.test_client()
    resp = client.get("/api/plugins/instance/no_such_plugin/history")
    assert resp.status_code == 404


def test_diff_endpoint_returns_correct_diff(flask_app):
    client = flask_app.test_client()
    instance_name = "clock_diff"
    _add_plugin_instance(flask_app, instance_name)
    _write_history(flask_app, instance_name, entries=2)

    resp = client.get(f"/api/plugins/instance/{instance_name}/diff")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["instance"] == instance_name
    assert "diff" in data
    assert "changed" in data["diff"]
    assert "from_ts" in data
    assert "to_ts" in data


def test_diff_endpoint_404_not_enough_history(flask_app):
    client = flask_app.test_client()
    instance_name = "clock_onehist"
    _add_plugin_instance(flask_app, instance_name)
    _write_history(flask_app, instance_name, entries=1)

    resp = client.get(f"/api/plugins/instance/{instance_name}/diff")
    assert resp.status_code == 404


def test_diff_endpoint_404_for_unknown_instance(flask_app):
    client = flask_app.test_client()
    resp = client.get("/api/plugins/instance/ghost_instance/diff")
    assert resp.status_code == 404


@pytest.mark.parametrize(
    "bad_name",
    [
        "../etc/passwd",
        "foo/bar",
        "foo\\bar",
        "foo..bar",
        "../secret",
        ".hidden",
    ],
)
def test_path_traversal_returns_400(flask_app, bad_name):
    client = flask_app.test_client()
    # URL-encode slashes so Flask doesn't route them as path separators
    encoded = urllib.parse.quote(bad_name, safe="")
    for endpoint in ("history", "diff"):
        resp = client.get(f"/api/plugins/instance/{encoded}/{endpoint}")
        assert resp.status_code in (
            400,
            404,
        ), f"Expected 400/404 for name={bad_name!r} endpoint={endpoint}, got {resp.status_code}"


def test_safe_name_with_slashes_gives_400(flask_app):
    """Instance names containing slashes must be rejected."""
    client = flask_app.test_client()
    resp = client.get("/api/plugins/instance/foo%2Fbar/history")
    assert resp.status_code in (400, 404)
