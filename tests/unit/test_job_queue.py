# pyright: reportMissingImports=false
"""Unit tests for refresh_task.job_queue."""

from __future__ import annotations

import threading
import time

import pytest

from refresh_task.job_queue import (
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_RUNNING,
    JobQueue,
    get_job_queue,
    reset_job_queue,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Ensure the module-level singleton is reset between tests."""
    reset_job_queue()
    yield
    reset_job_queue()


class TestJobQueue:
    """Core JobQueue behaviour."""

    def test_enqueue_returns_job_id(self):
        q = JobQueue()
        jid = q.enqueue(lambda: 42)
        assert isinstance(jid, str)
        assert len(jid) == 32  # uuid4 hex
        q.shutdown()

    def test_job_completes_with_done_status(self):
        q = JobQueue()
        jid = q.enqueue(lambda: "hello")
        # Wait for completion
        for _ in range(50):
            info = q.get_status(jid)
            if info["status"] == STATUS_DONE:
                break
            time.sleep(0.05)
        assert info["status"] == STATUS_DONE
        assert info["result"] == "hello"
        q.shutdown()

    def test_job_error_status(self):
        def _fail():
            raise ValueError("boom")

        q = JobQueue()
        jid = q.enqueue(_fail)
        for _ in range(50):
            info = q.get_status(jid)
            if info["status"] == STATUS_ERROR:
                break
            time.sleep(0.05)
        assert info["status"] == STATUS_ERROR
        assert "boom" in info["error"]
        q.shutdown()

    def test_unknown_job_id(self):
        q = JobQueue()
        info = q.get_status("nonexistent")
        assert info["status"] == "unknown"
        q.shutdown()

    def test_pending_jobs_count(self):
        barrier = threading.Event()

        def _block():
            barrier.wait(timeout=5)

        q = JobQueue(max_workers=1)
        q.enqueue(_block)
        q.enqueue(_block)
        # At least one should still be pending/running
        time.sleep(0.1)
        assert q.pending_jobs >= 1
        barrier.set()
        q.shutdown(wait=True)

    def test_job_transitions_through_running(self):
        started = threading.Event()
        proceed = threading.Event()

        def _slow():
            started.set()
            proceed.wait(timeout=5)
            return "ok"

        q = JobQueue(max_workers=1)
        jid = q.enqueue(_slow)
        started.wait(timeout=5)
        info = q.get_status(jid)
        assert info["status"] == STATUS_RUNNING
        proceed.set()
        for _ in range(50):
            info = q.get_status(jid)
            if info["status"] == STATUS_DONE:
                break
            time.sleep(0.05)
        assert info["status"] == STATUS_DONE
        q.shutdown()

    def test_enqueue_with_args_and_kwargs(self):
        def _add(a, b, extra=0):
            return a + b + extra

        q = JobQueue()
        jid = q.enqueue(_add, 1, 2, extra=10)
        for _ in range(50):
            info = q.get_status(jid)
            if info["status"] == STATUS_DONE:
                break
            time.sleep(0.05)
        assert info["result"] == 13
        q.shutdown()


class TestSingleton:
    """get_job_queue / reset_job_queue singleton management."""

    def test_get_returns_same_instance(self):
        q1 = get_job_queue()
        q2 = get_job_queue()
        assert q1 is q2

    def test_reset_creates_new_instance(self):
        q1 = get_job_queue()
        reset_job_queue()
        q2 = get_job_queue()
        assert q1 is not q2
