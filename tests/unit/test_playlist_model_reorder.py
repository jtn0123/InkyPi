# pyright: reportMissingImports=false
from datetime import datetime, timezone

from model import Playlist, PluginInstance


def _mk_inst(pid: str, name: str) -> PluginInstance:
    return PluginInstance(pid, name, {}, {"interval": 60})


def test_reorder_plugins_accepts_dicts_and_tuples():
    pl = Playlist("P", "00:00", "24:00")
    pl.plugins = [_mk_inst("a", "A"), _mk_inst("b", "B"), _mk_inst("c", "C")]

    ok = pl.reorder_plugins(
        [
            {"plugin_id": "c", "name": "C"},
            {"plugin_id": "a", "name": "A"},
            ("b", "B"),
        ]
    )
    assert ok is True
    assert [(p.plugin_id, p.name) for p in pl.plugins] == [
        ("c", "C"),
        ("a", "A"),
        ("b", "B"),
    ]


def test_reorder_plugins_rejects_missing_or_wrong_length():
    pl = Playlist("P", "00:00", "24:00")
    pl.plugins = [_mk_inst("a", "A"), _mk_inst("b", "B")]

    # Wrong length
    assert pl.reorder_plugins([{"plugin_id": "a", "name": "A"}]) is False
    # Missing item
    assert (
        pl.reorder_plugins(
            [{"plugin_id": "a", "name": "A"}, {"plugin_id": "c", "name": "C"}]
        )
        is False
    )
    # Wrong shape
    assert (
        pl.reorder_plugins([
            {"pid": "a", "nm": "A"},
            {"plugin_id": "b", "name": "B"},
        ])
        is False
    )


def test_get_next_eligible_advances_and_wraps():
    pl = Playlist("P", "00:00", "24:00")
    pl.plugins = [_mk_inst("a", "A"), _mk_inst("b", "B")]
    pl.current_plugin_index = None
    now = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)

    p1 = pl.get_next_eligible_plugin(now)
    assert p1.name == "A"
    p2 = pl.get_next_eligible_plugin(now)
    assert p2.name == "B"
    p3 = pl.get_next_eligible_plugin(now)
    assert p3.name == "A"


