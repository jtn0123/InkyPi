from model import Playlist, PluginInstance


def test_reorder_plugins_rejects_mismatch_and_invalid():
    p = Playlist("P", "00:00", "24:00", plugins=[
        {"plugin_id": "a", "name": "A", "plugin_settings": {}, "refresh": {}},
        {"plugin_id": "b", "name": "B", "plugin_settings": {}, "refresh": {}},
    ])

    # Mismatched count
    assert p.reorder_plugins([{"plugin_id": "a", "name": "A"}]) is False

    # Bad element shape
    assert p.reorder_plugins([{"pid": "a", "n": "A"}, {"pid": "b", "n": "B"}]) is False

    # Unknown item
    assert p.reorder_plugins([{"plugin_id": "x", "name": "X"}, {"plugin_id": "b", "name": "B"}]) is False


def test_get_next_plugin_resets_out_of_bounds():
    p = Playlist("P", "00:00", "24:00", plugins=[
        {"plugin_id": "a", "name": "A", "plugin_settings": {}, "refresh": {}},
        {"plugin_id": "b", "name": "B", "plugin_settings": {}, "refresh": {}},
    ], current_plugin_index=99)

    nxt = p.get_next_plugin()
    assert isinstance(nxt, PluginInstance)
    assert p.current_plugin_index in (0, 1)

