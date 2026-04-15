# pyright: reportMissingImports=false
"""End-to-end journey test for the API keys lifecycle (JTN-722).

Covers the full multi-step round-trip that click-level tests in JTN-325/323
do not: add -> reload -> edit -> reload -> delete -> reload, asserting that
state persists across every reload. Intended to catch POST-200-but-not-saved
bugs, ghost rows, and delete resurrection.

All values used here are fake placeholders — see ``_FAKE_KEY_VALUE``.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = [
    pytest.mark.journey,
    pytest.mark.skipif(
        os.getenv("SKIP_UI", "").lower() in ("1", "true"),
        reason="UI interactions skipped by env",
    ),
]

# SECURITY: fake placeholder credentials only. Never put real API keys here —
# the .env written by this test lives in pytest's tmp_path but test logs and
# CI artifacts may still capture the value.
_FAKE_KEY_VALUE = "sk-test-fake-1234"
_FAKE_KEY_VALUE_EDITED = "sk-test-fake-edited-5678"


def _unique_key_name() -> str:
    """Return a key name that satisfies the backend's ^[A-Za-z_][A-Za-z0-9_]*$."""
    # Hyphens are rejected, so use underscores only and a hex-safe suffix.
    return f"TEST_ROUNDTRIP_{uuid.uuid4().hex[:8].upper()}"


def _read_env_keys(env_path: str) -> dict[str, str]:
    """Parse the .env file the way the blueprint does and return {key: value}."""
    from dotenv import dotenv_values

    if not os.path.exists(env_path):
        return {}
    return dict(dotenv_values(env_path))


def test_api_key_add_edit_delete_roundtrip(live_server, browser_page, client):
    """Full lifecycle: add via UI, edit via API, delete via UI — persisted at each step."""
    from tests.integration.browser_helpers import navigate_and_wait

    key_name = _unique_key_name()
    # Resolve the .env path the server is actually using so the browser flow
    # and backend assertions agree on what "persisted" means.
    project_dir = os.environ.get("PROJECT_DIR")
    assert project_dir, "PROJECT_DIR should be set by the device_config_dev fixture"
    env_path = os.path.join(project_dir, ".env")

    try:
        # ---- Step 1: navigate to /api-keys (generic mode) ----
        page = browser_page
        rc = navigate_and_wait(page, live_server, "/api-keys")
        # Stub window.alert/confirm so JS `confirm()` in deleteRow doesn't hang.
        page.evaluate("window.confirm = () => true;" "window.alert = () => undefined;")
        # Prevent the post-save reload from racing Playwright — we'll reload
        # explicitly so we control timing.
        page.evaluate("window.location.reload = () => {};")

        # ---- Step 2: add a new key via the UI ----
        page.locator("#addApiKeyBtn").click()
        new_row = page.locator(".apikey-row[data-existing='false']").last
        new_row.locator(".apikey-key").fill(key_name)
        new_row.locator(".apikey-value").fill(_FAKE_KEY_VALUE)

        save_btn = page.locator("#saveApiKeysBtn")
        with page.expect_response(
            lambda r: "/api-keys/save" in r.url and r.request.method == "POST"
        ) as save_info:
            save_btn.click()
        assert save_info.value.status == 200, "initial save should succeed"

        # ---- Step 3: verify it appears on-disk (the round-trip). ----
        env_after_add = _read_env_keys(env_path)
        assert (
            env_after_add.get(key_name) == _FAKE_KEY_VALUE
        ), f"key {key_name} should be written to .env after save"

        # No console errors / client-log posts from the add flow.
        rc.assert_no_errors(name="api_keys_after_add")

        # ---- Step 4+5: reload and confirm the new row is still listed. ----
        rc = navigate_and_wait(page, live_server, "/api-keys")
        page.evaluate(
            "window.confirm = () => true;" "window.location.reload = () => {};"
        )
        listed_keys = page.locator(".apikey-row[data-existing='true'] .apikey-key")
        listed_values = [
            listed_keys.nth(i).input_value() for i in range(listed_keys.count())
        ]
        assert (
            key_name in listed_values
        ), f"key {key_name} should persist across reload but only saw {listed_values}"

        # ---- Step 6+7: edit the value. Existing-row inputs are readonly in
        # the generic UI, so the supported edit path is to re-POST via the
        # same save endpoint with a new value. That is exactly what the
        # managed-row `keepExisting` branch in the JS bypasses, so hitting
        # the JSON endpoint directly is the correct backend contract.
        resp = client.post(
            "/api-keys/save",
            json={"entries": [{"key": key_name, "value": _FAKE_KEY_VALUE_EDITED}]},
        )
        assert resp.status_code == 200, f"edit save failed: {resp.data!r}"

        # ---- Step 8: edit is reflected — no duplicate row, value updated. ----
        env_after_edit = _read_env_keys(env_path)
        assert (
            env_after_edit.get(key_name) == _FAKE_KEY_VALUE_EDITED
        ), "edit should replace the stored value"
        assert (
            sum(1 for k in env_after_edit if k == key_name) == 1
        ), "editing must not create a duplicate key"

        # ---- Step 9+10: reload and verify the edit persisted visually. ----
        rc = navigate_and_wait(page, live_server, "/api-keys")
        page.evaluate(
            "window.confirm = () => true;" "window.location.reload = () => {};"
        )
        listed_keys = page.locator(".apikey-row[data-existing='true'] .apikey-key")
        listed_values = [
            listed_keys.nth(i).input_value() for i in range(listed_keys.count())
        ]
        assert (
            key_name in listed_values
        ), "edited key should still be present after reload"
        # And the underlying value matches the edit.
        assert _read_env_keys(env_path).get(key_name) == _FAKE_KEY_VALUE_EDITED

        # ---- Step 11+12: delete via the UI. The confirm() dialog is stubbed
        # to return true above, so clicking the delete button removes the row
        # immediately; we then save to persist the deletion.
        target_row = page.locator(
            f".apikey-row[data-existing='true']:has(.apikey-key[value='{key_name}'])"
        ).first
        target_row.locator(".btn-delete").click()
        with page.expect_response(
            lambda r: "/api-keys/save" in r.url and r.request.method == "POST"
        ) as del_info:
            page.locator("#saveApiKeysBtn").click()
        assert del_info.value.status == 200, "save-after-delete should succeed"

        # Backend confirms the key is gone.
        env_after_delete = _read_env_keys(env_path)
        assert (
            key_name not in env_after_delete
        ), f"key {key_name} should be removed from .env after delete+save"
        rc.assert_no_errors(name="api_keys_after_delete")

        # ---- Step 13+14: reload; the key must stay gone (no resurrection). ----
        rc = navigate_and_wait(page, live_server, "/api-keys")
        listed_keys = page.locator(".apikey-row[data-existing='true'] .apikey-key")
        listed_values = [
            listed_keys.nth(i).input_value() for i in range(listed_keys.count())
        ]
        assert (
            key_name not in listed_values
        ), "deletion must not resurrect the key after reload"
        assert _read_env_keys(env_path).get(key_name) is None
        rc.assert_no_errors(name="api_keys_after_delete_reload")

    finally:
        # Teardown: make sure the test key is gone even if an assertion above
        # raised. We always write a .env that omits the test key; other keys
        # present in the .env are preserved by filtering them through.
        try:
            remaining = {
                k: v for k, v in _read_env_keys(env_path).items() if k != key_name
            }
            entries = [{"key": k, "value": v} for k, v in remaining.items()]
            client.post("/api-keys/save", json={"entries": entries})
        except Exception:
            # Teardown best-effort; don't mask the original assertion failure.
            pass
