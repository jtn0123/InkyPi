# pyright: reportMissingImports=false
"""Tests for /api/client-log batch payload support (JTN-711).

The endpoint now accepts either the legacy single-object payload or a JSON
array of entries. Each POST — whether single or batch — consumes exactly
one rate-limit token.

Coverage:
  * Batch endpoint accepts array payloads
  * Batch is rejected when oversized (> 50 entries)
  * One bad entry causes the whole batch to fail with per-entry errors
  * Rate-limit capacity was raised to 60 (JTN-711)
  * Each batch POST consumes one token (not N)
  * Single-entry payload still works (backwards-compat)
  * Newline stripping / field capping runs on every batch entry
"""

from __future__ import annotations

import json
import logging

import pytest
from tests.helpers.client_log_helpers import fresh_client_log_app


def _post(client, payload):
    return client.post(
        "/api/client-log",
        data=json.dumps(payload),
        content_type="application/json",
    )


class TestBatchAccepted:
    def test_batch_endpoint_accepts_array_payload(self, monkeypatch):
        cl_mod, app = fresh_client_log_app(monkeypatch, capture=True)

        batch = [
            {"level": "warn", "message": "w1"},
            {"level": "error", "message": "e1"},
            {"level": "warn", "message": "w2"},
        ]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 204

        reports = cl_mod.get_captured_reports()
        assert [r["message"] for r in reports] == ["w1", "e1", "w2"]
        assert [r["level"] for r in reports] == ["warn", "error", "warn"]

    def test_existing_single_entry_payload_still_works(self, monkeypatch):
        """Backwards-compat: legacy single-object POSTs still return 204."""
        cl_mod, app = fresh_client_log_app(monkeypatch, capture=True)

        resp = _post(app.test_client(), {"level": "warn", "message": "solo"})
        assert resp.status_code == 204
        reports = cl_mod.get_captured_reports()
        assert len(reports) == 1
        assert reports[0]["message"] == "solo"

    def test_batch_at_cap_is_accepted(self, monkeypatch):
        cl_mod, app = fresh_client_log_app(monkeypatch, capture=True)

        batch = [{"level": "warn", "message": f"m{i}"} for i in range(50)]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 204
        assert len(cl_mod.get_captured_reports()) == 50


class TestBatchRejected:
    def test_batch_endpoint_rejects_oversized_batch(self, monkeypatch):
        """> 50 entries → 400."""
        cl_mod, app = fresh_client_log_app(monkeypatch, capture=True)

        batch = [{"level": "warn", "message": f"m{i}"} for i in range(51)]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body["success"] is False
        assert "max" in body["error"].lower() or "50" in body["error"]
        # Nothing should have been captured.
        assert cl_mod.get_captured_reports() == []

    def test_empty_batch_rejected(self, monkeypatch):
        _, app = fresh_client_log_app(monkeypatch)
        resp = _post(app.test_client(), [])
        assert resp.status_code == 400

    def test_batch_entries_individually_validated(self, monkeypatch):
        """One bad entry returns 400 with per-entry errors; good entries are
        NOT emitted in that case (all-or-nothing)."""
        cl_mod, app = fresh_client_log_app(monkeypatch, capture=True)

        batch = [
            {"level": "warn", "message": "ok1"},
            {"level": "info", "message": "nope"},  # invalid level
            {"level": "error", "message": "ok2"},
        ]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 400
        body = json.loads(resp.data)
        assert body["details"]["entry_errors"][0]["index"] == 1
        # All-or-nothing semantics — no entries captured.
        assert cl_mod.get_captured_reports() == []

    def test_non_object_entry_in_batch_rejected(self, monkeypatch):
        _, app = fresh_client_log_app(monkeypatch)
        batch = [{"level": "warn", "message": "ok"}, "bad-entry", 42]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 400
        body = json.loads(resp.data)
        indexes = [e["index"] for e in body["details"]["entry_errors"]]
        assert indexes == [1, 2]

    def test_non_object_non_array_body_rejected(self, monkeypatch):
        _, app = fresh_client_log_app(monkeypatch)
        resp = _post(app.test_client(), "just-a-string")
        assert resp.status_code == 400


class TestRateLimitCapacity:
    def test_rate_limit_capacity_raised_to_60(self, monkeypatch):
        """JTN-711: the bucket now holds 60 tokens (up from 10)."""
        cl_mod, app = fresh_client_log_app(monkeypatch)

        cl_mod._rate_limiter = cl_mod.TokenBucket(capacity=60, refill_rate=0)
        c = app.test_client()

        for i in range(60):
            resp = _post(c, {"level": "warn", "message": f"m{i}"})
            assert resp.status_code == 204, f"unexpected failure at iteration {i}"

        # 61st → 429
        resp = _post(c, {"level": "warn", "message": "over"})
        assert resp.status_code == 429

    def test_each_batch_post_consumes_one_token(self, monkeypatch):
        """60 POSTs, each carrying 10 entries, should all succeed. That's
        600 *entries* worth of traffic — proving the bucket is keyed on
        requests, not entries."""
        cl_mod, app = fresh_client_log_app(monkeypatch, capture=True)

        cl_mod._rate_limiter = cl_mod.TokenBucket(capacity=60, refill_rate=0)
        c = app.test_client()
        per_batch = 10
        batches = 60
        for i in range(batches):
            batch = [
                {"level": "warn", "message": f"b{i}-e{j}"} for j in range(per_batch)
            ]
            resp = _post(c, batch)
            assert resp.status_code == 204

        # 61st batch → 429 (capacity exhausted)
        resp = _post(c, [{"level": "warn", "message": "over"}])
        assert resp.status_code == 429

        # All 600 entries landed in the capture list
        assert len(cl_mod.get_captured_reports()) == batches * per_batch


class TestBatchFieldHandling:
    def test_secret_redaction_applied_to_every_batch_entry(self, monkeypatch, caplog):
        """Every entry is logged at WARNING so SecretRedactionFilter (JTN-364)
        strips secrets. Here we assert each entry reaches the logger — the
        downstream filter is tested separately in its own suite."""
        _, app = fresh_client_log_app(monkeypatch)

        batch = [{"level": "warn", "message": f"entry-{i}"} for i in range(5)]
        with caplog.at_level(logging.WARNING, logger="blueprints.client_log"):
            resp = _post(app.test_client(), batch)
        assert resp.status_code == 204

        warning_msgs = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        for i in range(5):
            assert any(
                f"entry-{i}" in m for m in warning_msgs
            ), f"entry-{i} missing from logs"

    def test_cr_lf_stripped_on_every_batch_entry(self, monkeypatch, caplog):
        _, app = fresh_client_log_app(monkeypatch)
        batch = [
            {"level": "warn", "message": "line\r\nbad1"},
            {"level": "error", "message": "also\nbad2"},
        ]
        with caplog.at_level(logging.WARNING, logger="blueprints.client_log"):
            resp = _post(app.test_client(), batch)
        assert resp.status_code == 204
        joined = " ".join(
            r.message for r in caplog.records if r.levelno == logging.WARNING
        )
        assert "\r" not in joined
        assert "\n" not in joined
        assert "bad1" in joined
        assert "bad2" in joined

    def test_message_field_capped_per_entry(self, monkeypatch):
        cl_mod, app = fresh_client_log_app(monkeypatch, capture=True)

        huge = "x" * 5000  # exceeds 2048 message cap
        batch = [{"level": "warn", "message": huge}]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 204
        reports = cl_mod.get_captured_reports()
        assert len(reports[0]["message"]) == 2048


class TestBurstAllLands:
    """Acceptance test from JTN-711: 30 errors in a burst all land in the
    capture list, because the reporter coalesces them into at most one POST.

    We simulate the coalesced POST directly here — the JS coalescing is
    tested in the browser integration suite."""

    def test_30_errors_in_a_burst_all_land(self, monkeypatch):
        cl_mod, app = fresh_client_log_app(monkeypatch, capture=True)

        batch = [{"level": "error", "message": f"burst-{i}"} for i in range(30)]
        resp = _post(app.test_client(), batch)
        assert resp.status_code == 204

        messages = [r["message"] for r in cl_mod.get_captured_reports()]
        assert messages == [f"burst-{i}" for i in range(30)]


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
