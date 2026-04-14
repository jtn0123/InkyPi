"""Hand-rolled TypedDict payload validator.

Extracted from ``tests/contract/test_response_shapes.py`` so that both the
contract tests and the dev-mode response-schema middleware (JTN-664) can share
a single implementation. The validator walks a TypedDict's ``__annotations__``
and checks:

* every required key is present with a value matching its declared type
* for ``total=False`` TypedDicts, keys that *are* present also type-check

``Any`` annotations short-circuit the type check, mirroring mypy semantics.
Kept intentionally dependency-free (no pydantic) so importing it is cheap and
safe to do from request paths.

Error messages intentionally omit the raw mismatched value. The middleware
surfaces these at WARNING level; responses occasionally contain user-visible
strings (plugin labels, paths) that should not be echoed into logs.
"""

from __future__ import annotations

import types
import typing
from typing import Any, get_args, get_origin


def _is_typeddict(tp: Any) -> bool:
    return (
        isinstance(tp, type)
        and issubclass(tp, dict)
        and hasattr(tp, "__total__")
        and hasattr(tp, "__annotations__")
    )


def _check_union(value: Any, tp: Any, path: str) -> list[str]:
    for arm in get_args(tp):
        if not _check_type(value, arm, path):
            return []
    return [f"{path}: no union arm matched ({tp})"]


def _check_list(value: Any, tp: Any, path: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{path}: expected list, got {type(value).__name__}"]
    (inner,) = get_args(tp) or (Any,)
    errs: list[str] = []
    for i, item in enumerate(value):
        errs.extend(_check_type(item, inner, f"{path}[{i}]"))
    return errs


def _check_dict(value: Any, tp: Any, path: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{path}: expected dict, got {type(value).__name__}"]
    args = get_args(tp)
    if not args:
        return []
    _k, vt = args
    errs: list[str] = []
    for k, v in value.items():
        errs.extend(_check_type(v, vt, f"{path}[{k!r}]"))
    return errs


def _check_plain_class(value: Any, tp: type, path: str) -> list[str]:
    # bool is a subclass of int; keep them distinct to catch accidents.
    if tp is int and isinstance(value, bool):
        return [f"{path}: expected int, got bool"]
    if not isinstance(value, tp):
        return [f"{path}: expected {tp.__name__}, got {type(value).__name__}"]
    return []


def _check_type(value: Any, tp: Any, path: str) -> list[str]:
    """Return a list of error strings (empty if ``value`` matches ``tp``)."""
    # Any -> accept anything
    if tp is Any or tp is object:
        return []

    origin = get_origin(tp)

    if origin is typing.Union or origin is types.UnionType:
        return _check_union(value, tp, path)
    if origin in (list, typing.List):  # noqa: UP006
        return _check_list(value, tp, path)
    if origin in (dict, typing.Dict):  # noqa: UP006
        return _check_dict(value, tp, path)

    # Nested TypedDict
    if _is_typeddict(tp):
        return validate_typeddict(value, tp, path=path)

    # Plain class
    if isinstance(tp, type):
        return _check_plain_class(value, tp, path)

    # Unknown / exotic annotation — skip silently
    return []


def validate_typeddict(payload: Any, schema: Any, *, path: str = "$") -> list[str]:
    """Validate *payload* against the TypedDict *schema*. Returns error list."""
    if not isinstance(payload, dict):
        return [f"{path}: expected dict, got {type(payload).__name__}"]

    hints = typing.get_type_hints(schema)
    required_keys = set(getattr(schema, "__required_keys__", set()))
    optional_keys = set(getattr(schema, "__optional_keys__", set()))
    # Older Pythons: fall back to __total__
    if not required_keys and not optional_keys:
        if getattr(schema, "__total__", True):
            required_keys = set(hints.keys())
        else:
            optional_keys = set(hints.keys())

    errors: list[str] = []
    for key in required_keys:
        if key not in payload:
            errors.append(f"{path}.{key}: missing required key")
            continue
        errors.extend(_check_type(payload[key], hints[key], f"{path}.{key}"))

    for key in optional_keys:
        if key in payload:
            errors.extend(_check_type(payload[key], hints[key], f"{path}.{key}"))

    return errors
