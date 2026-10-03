# pyright: reportMissingImports=false
"""Tests for the service worker route (JTN-303)."""

import shutil
import subprocess
from pathlib import Path

import pytest
from flask.testing import FlaskClient


@pytest.mark.parametrize(
    "scenario",
    [
        "updated",
        "offline",
        "hashed",
        "error",
        "cross-origin",
        "non-get",
        "private-image",
        "private-image-traversal",
    ],
)
def test_worker_cache_policy(scenario: str) -> None:
    """Execute the shipped worker against a primed cache, not a source-pattern mock."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required to execute service-worker JavaScript")
    worker = Path(__file__).parents[1] / "src/static/sw.js"
    script = r"""
const vm = require("node:vm");
const fs = require("node:fs");
const assert = require("node:assert/strict");
const scenario = process.argv[1];
const handlers = {};
let requests = 0;
let policy;
const response = (text, status = 200) => ({text, status, clone() { return response(text, status); }});
let cached = response("old");
let writes = 0;
const cache = {match: async () => cached, put: async (_request, value) => {cached = value; writes++;}};
vm.runInNewContext(fs.readFileSync(process.argv[2], "utf8"), {
  self: {location: {origin: "https://inkypi.test"}, addEventListener: (name, fn) => handlers[name] = fn},
  caches: {open: async () => cache, match: async () => cached},
  URL,
  fetch: async (_request, options) => {
    requests++; policy = options;
    if (scenario === "offline") throw new Error("offline");
    return response("new", scenario === "error" ? 503 : 200);
  },
});
(async () => {
  const request = {
    method: scenario === "non-get" ? "POST" : "GET",
    url: scenario === "cross-origin" ? "https://other.test/static/x.css" :
      scenario === "hashed" ? "https://inkypi.test/static/dist/common.bundle.a1b2c3d4.min.js" :
      scenario === "private-image" ? "https://inkypi.test/static/images/current_image.png" :
      scenario === "private-image-traversal" ? "https://inkypi.test/static/styles/../images/saved/me.jpg" :
      "https://inkypi.test/static/styles/main.css",
  };
  let pending;
  const waits = [];
  handlers.fetch({request, respondWith: p => pending = p, waitUntil: p => waits.push(p)});
  // Auth-gated /static/images/ responses must never enter the shared cache.
  if (["cross-origin", "non-get", "private-image", "private-image-traversal"].includes(scenario)) {
    assert.equal(pending, undefined); assert.equal(requests, 0); return;
  }
  const result = await pending;
  await Promise.all(waits);
  if (scenario === "hashed") {
    assert.equal(result.text, "old"); assert.equal(requests, 0);
  } else if (scenario === "offline") {
    assert.equal(result.text, "old"); assert.equal(requests, 1);
  } else if (scenario === "error") {
    assert.equal(result.status, 503); assert.equal(writes, 0);
  } else {
    assert.equal(result.text, "new"); assert.equal(cached.text, "new");
    assert.equal(policy.cache, "no-cache");
    // A subsequent page load must also revalidate, even with the updated cache.
    handlers.fetch({request, respondWith: p => pending = p, waitUntil: p => waits.push(p)});
    assert.equal((await pending).text, "new"); assert.equal(requests, 2);
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
"""
    subprocess.run(
        [node, "-e", script, scenario, str(worker)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_sw_js_returns_200(client: FlaskClient) -> None:
    """GET /sw.js returns HTTP 200."""
    response = client.get("/sw.js")
    assert response.status_code == 200


def test_sw_js_content_type_javascript(client: FlaskClient) -> None:
    """GET /sw.js returns application/javascript content type."""
    response = client.get("/sw.js")
    assert "application/javascript" in response.content_type


def test_sw_js_contains_cache_name(client: FlaskClient) -> None:
    """GET /sw.js body contains the versioned CACHE_NAME constant.

    The cache version is bumped whenever the shell asset list changes; we
    only care that the name follows the `inkypi-shell-v<n>` convention so
    the activate handler can prune stale versions deterministically.
    """
    import re

    response = client.get("/sw.js")
    body = response.data.decode("utf-8")
    assert re.search(
        r"inkypi-shell-v\d+", body
    ), "sw.js must declare a versioned CACHE_NAME (inkypi-shell-v<n>)"


def test_sw_js_service_worker_allowed_header(client: FlaskClient) -> None:
    """GET /sw.js includes Service-Worker-Allowed header set to '/'."""
    response = client.get("/sw.js")
    assert response.headers.get("Service-Worker-Allowed") == "/"
