"""Coverage guard: frontend-consumed JSON APIs must have contract gates.

JTN-739 follow-up:
* Every frontend-consumed GET JSON endpoint should be present in
  ``schemas.endpoint_map.ENDPOINT_SCHEMAS`` so dev-mode schema validation runs.
* The same endpoints should be documented in ``/api/openapi.json``.
"""

from __future__ import annotations

import json

from tests.helpers.endpoint_schema_helpers import get_endpoint_schema_names

# Flask route syntax for lookup in ``url_map``.
_FRONTEND_JSON_ROUTES = (
    "/api/health/system",
    "/api/health/plugins",
    "/api/benchmarks/summary",
    "/api/benchmarks/plugins",
    "/api/diagnostics",
    "/api/job/<job_id>",
    "/api/version/info",
    "/api/uptime",
    "/refresh-info",
    "/next-up",
    "/history/storage",
)

# OpenAPI route syntax.
_FRONTEND_OPENAPI_PATHS = (
    "/api/health/system",
    "/api/health/plugins",
    "/api/benchmarks/summary",
    "/api/benchmarks/plugins",
    "/api/diagnostics",
    "/api/job/{job_id}",
    "/api/version/info",
    "/api/uptime",
    "/refresh-info",
    "/next-up",
    "/history/storage",
)


def _find_endpoint_for_get(flask_app, route: str) -> str | None:
    for rule in flask_app.url_map.iter_rules():
        if rule.rule == route and "GET" in rule.methods:
            return rule.endpoint
    return None


def test_frontend_json_routes_have_endpoint_schema(flask_app):
    endpoint_schema_names = get_endpoint_schema_names()
    missing: list[str] = []
    for route in _FRONTEND_JSON_ROUTES:
        endpoint = _find_endpoint_for_get(flask_app, route)
        if endpoint is None:
            missing.append(f"{route} (no GET route found)")
            continue
        if endpoint not in endpoint_schema_names:
            missing.append(f"{route} -> {endpoint} (missing in ENDPOINT_SCHEMAS)")

    assert not missing, (
        "Frontend JSON routes must be schema-pinned in ENDPOINT_SCHEMAS:\n- "
        + "\n- ".join(missing)
    )


def test_frontend_json_routes_are_documented_in_openapi(client):
    resp = client.get("/api/openapi.json")
    assert resp.status_code == 200
    spec = json.loads(resp.data)
    paths = set(spec.get("paths", {}).keys())

    missing = [path for path in _FRONTEND_OPENAPI_PATHS if path not in paths]
    assert (
        not missing
    ), "OpenAPI spec is missing frontend-consumed JSON routes:\n- " + "\n- ".join(
        missing
    )
