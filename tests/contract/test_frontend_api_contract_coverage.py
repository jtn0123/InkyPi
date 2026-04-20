"""Coverage guard: frontend-consumed JSON APIs must have contract gates.

JTN-739 follow-up:
* Every frontend-consumed JSON endpoint should be present in
  ``schemas.endpoint_map.ENDPOINT_SCHEMAS`` so dev-mode schema validation runs.
* The same endpoints should be documented in ``/api/openapi.json`` with the
  HTTP methods the frontend uses.
"""

from __future__ import annotations

import json
import re

from tests.helpers.endpoint_schema_helpers import get_endpoint_schema_names

# Flask route syntax for lookup in ``url_map``.
_FRONTEND_JSON_ROUTES = (
    ("GET", "/api/health/system"),
    ("GET", "/api/health/plugins"),
    ("GET", "/api/benchmarks/summary"),
    ("GET", "/api/benchmarks/plugins"),
    ("GET", "/api/diagnostics"),
    ("GET", "/api/job/<job_id>"),
    ("GET", "/api/version/info"),
    ("GET", "/api/uptime"),
    ("GET", "/refresh-info"),
    ("GET", "/next-up"),
    ("GET", "/history/storage"),
    ("POST", "/display-next"),
    ("POST", "/api/plugin_order"),
    ("POST", "/save_settings"),
    ("GET", "/settings/isolation"),
    ("POST", "/settings/isolation"),
    ("DELETE", "/settings/isolation"),
    ("POST", "/settings/safe_reset"),
    ("POST", "/settings/save_api_keys"),
    ("POST", "/create_playlist"),
    ("PUT", "/update_playlist/<playlist_name>"),
    ("DELETE", "/delete_playlist/<playlist_name>"),
    ("PUT", "/update_device_cycle"),
    ("POST", "/reorder_plugins"),
    ("POST", "/display_next_in_playlist"),
    ("POST", "/settings/update"),
    ("POST", "/settings/update/rollback"),
    ("POST", "/settings/delete_api_key"),
    ("POST", "/history/redisplay"),
    ("POST", "/history/delete"),
    ("POST", "/history/clear"),
)

# OpenAPI route syntax.
_FRONTEND_OPENAPI_PATHS = (
    ("GET", "/api/health/system"),
    ("GET", "/api/health/plugins"),
    ("GET", "/api/benchmarks/summary"),
    ("GET", "/api/benchmarks/plugins"),
    ("GET", "/api/diagnostics"),
    ("GET", "/api/job/{job_id}"),
    ("GET", "/api/version/info"),
    ("GET", "/api/uptime"),
    ("GET", "/refresh-info"),
    ("GET", "/next-up"),
    ("GET", "/history/storage"),
    ("POST", "/display-next"),
    ("POST", "/api/plugin_order"),
    ("POST", "/save_settings"),
    ("GET", "/settings/isolation"),
    ("POST", "/settings/isolation"),
    ("DELETE", "/settings/isolation"),
    ("POST", "/settings/safe_reset"),
    ("POST", "/settings/save_api_keys"),
    ("POST", "/create_playlist"),
    ("PUT", "/update_playlist/{playlist_name}"),
    ("DELETE", "/delete_playlist/{playlist_name}"),
    ("PUT", "/update_device_cycle"),
    ("POST", "/reorder_plugins"),
    ("POST", "/display_next_in_playlist"),
    ("POST", "/settings/update"),
    ("POST", "/settings/update/rollback"),
    ("POST", "/settings/delete_api_key"),
    ("POST", "/history/redisplay"),
    ("POST", "/history/delete"),
    ("POST", "/history/clear"),
)

_FRONTEND_OPENAPI_REQUEST_BODIES = (
    ("POST", "/api/plugin_order"),
    ("POST", "/save_settings"),
    ("POST", "/settings/isolation"),
    ("DELETE", "/settings/isolation"),
    ("POST", "/settings/save_api_keys"),
    ("POST", "/settings/delete_api_key"),
    ("POST", "/settings/update"),
    ("POST", "/create_playlist"),
    ("PUT", "/update_playlist/{playlist_name}"),
    ("PUT", "/update_device_cycle"),
    ("POST", "/reorder_plugins"),
    ("POST", "/display_next_in_playlist"),
    ("POST", "/history/redisplay"),
    ("POST", "/history/delete"),
)


def _normalize_route_pattern(route: str) -> str:
    route = route.rstrip("/") or "/"
    return re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"<\1>", route)


def _find_endpoint_for_method(flask_app, route: str, method: str) -> str | None:
    normalized_route = _normalize_route_pattern(route)
    for rule in flask_app.url_map.iter_rules():
        if (
            _normalize_route_pattern(rule.rule) == normalized_route
            and method in rule.methods
        ):
            return rule.endpoint
    return None


def test_frontend_json_routes_have_endpoint_schema(flask_app):
    endpoint_schema_names = get_endpoint_schema_names()
    missing: list[str] = []
    for method, route in _FRONTEND_JSON_ROUTES:
        endpoint = _find_endpoint_for_method(flask_app, route, method)
        if endpoint is None:
            missing.append(f"{method} {route} (route not found)")
            continue
        if endpoint not in endpoint_schema_names:
            missing.append(
                f"{method} {route} -> {endpoint} (missing in ENDPOINT_SCHEMAS)"
            )

    assert not missing, (
        "Frontend JSON routes must be schema-pinned in ENDPOINT_SCHEMAS:\n- "
        + "\n- ".join(missing)
    )


def test_frontend_json_routes_are_documented_in_openapi(client):
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200
    spec = json.loads(resp.data)
    paths = spec.get("paths", {})

    missing: list[str] = []
    for method, path in _FRONTEND_OPENAPI_PATHS:
        path_item = paths.get(path)
        if not isinstance(path_item, dict):
            missing.append(f"{method} {path} (path missing)")
            continue
        if method.lower() not in path_item:
            missing.append(f"{method} {path} (method missing)")

    assert not missing, (
        "OpenAPI spec is missing frontend-consumed JSON route methods:\n- "
        + "\n- ".join(missing)
    )


def test_mutating_frontend_routes_document_request_bodies(client):
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200
    spec = json.loads(resp.data)
    paths = spec.get("paths", {})

    missing: list[str] = []
    for method, path in _FRONTEND_OPENAPI_REQUEST_BODIES:
        path_item = paths.get(path)
        if not isinstance(path_item, dict):
            missing.append(f"{method} {path} (path missing)")
            continue
        operation = path_item.get(method.lower())
        if not isinstance(operation, dict):
            missing.append(f"{method} {path} (method missing)")
            continue
        if "requestBody" not in operation:
            missing.append(f"{method} {path} (requestBody missing)")

    assert not missing, (
        "OpenAPI spec is missing requestBody docs for mutating frontend routes:\n- "
        + "\n- ".join(missing)
    )
