"""Helpers that shield contract tests from schema-map implementation imports."""

from __future__ import annotations


def get_endpoint_schema_names() -> set[str]:
    from schemas.endpoint_map import ENDPOINT_SCHEMAS

    return set(ENDPOINT_SCHEMAS)
