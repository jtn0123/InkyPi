"""Tests for the internal history path helpers."""

from __future__ import annotations


def test_resolve_history_entry_path_returns_real_file(tmp_path):
    from blueprints.history import _resolve_history_entry_path

    history_dir = tmp_path / "history"
    history_dir.mkdir()
    image = history_dir / "display_20250101_000000.png"
    image.write_bytes(b"png")

    resolved = _resolve_history_entry_path(str(history_dir), image.name)

    assert resolved == str(image)


def test_resolve_history_entry_path_returns_none_for_missing_file(tmp_path):
    from blueprints.history import _resolve_history_entry_path

    history_dir = tmp_path / "history"
    history_dir.mkdir()

    assert _resolve_history_entry_path(str(history_dir), "missing.png") is None


def test_resolve_history_entry_path_returns_none_for_directory_entry(tmp_path):
    from blueprints.history import _resolve_history_entry_path

    history_dir = tmp_path / "history"
    history_dir.mkdir()
    (history_dir / "nested").mkdir()

    assert _resolve_history_entry_path(str(history_dir), "nested") is None


def test_resolve_history_entry_path_returns_none_for_symlink_escape(tmp_path):
    from blueprints.history import _resolve_history_entry_path

    history_dir = tmp_path / "history"
    history_dir.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")
    link = history_dir / "escape.png"
    link.symlink_to(outside)

    assert _resolve_history_entry_path(str(history_dir), link.name) is None


def test_resolve_history_entry_path_returns_none_when_listdir_fails(
    tmp_path, monkeypatch
):
    from blueprints.history import _resolve_history_entry_path

    history_dir = tmp_path / "history"
    history_dir.mkdir()

    def raise_oserror(_path):
        raise OSError("boom")

    monkeypatch.setattr("blueprints.history.os.listdir", raise_oserror)

    assert _resolve_history_entry_path(str(history_dir), "display.png") is None


def test_remove_history_entry_by_name_deletes_file(tmp_path):
    from blueprints.history import _remove_history_entry_by_name

    history_dir = tmp_path / "history"
    history_dir.mkdir()
    image = history_dir / "display_20250101_000000.png"
    image.write_bytes(b"png")

    _remove_history_entry_by_name(str(history_dir), image.name)

    assert not image.exists()
