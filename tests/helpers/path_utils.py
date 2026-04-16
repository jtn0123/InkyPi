"""Shared dotted-path assertions for migration and upgrade-chain tests."""

from __future__ import annotations

from collections.abc import Sequence


def _path_get(payload: object, dotted_path: str) -> object:
    """Resolve a dotted path into nested dict/list payloads."""
    node: object = payload
    for segment in dotted_path.split("."):
        if isinstance(node, list):
            node = node[int(segment)]
            continue
        if not isinstance(node, dict):
            raise KeyError(f"{dotted_path}: expected mapping at '{segment}'")
        node = node[segment]
    return node


def _assert_baseline_preserved(
    baseline_values: dict[str, object],
    actual_payload: dict,
    paths: Sequence[str],
    version: str | None = None,
) -> None:
    """Assert configured dotted paths remain unchanged after migration/upgrade."""
    for dotted_path in paths:
        actual_value = _path_get(actual_payload, dotted_path)
        expected_value = baseline_values[dotted_path]
        prefix = f"Upgrade hop {version} " if version else ""
        assert actual_value == expected_value, (
            f"{prefix}dropped/changed '{dotted_path}': "
            f"expected={expected_value!r} actual={actual_value!r}"
        )
