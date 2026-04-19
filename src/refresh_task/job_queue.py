"""Lightweight thread-pool job queue for non-blocking plugin renders.

Provides ``enqueue(fn, *args, **kwargs) -> job_id`` and ``get_status(job_id)``
so HTTP handlers can return 202 Accepted and let the caller poll for results.

No external dependencies (no Celery, no Redis) — uses a stdlib
``concurrent.futures.ThreadPoolExecutor``.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from time import monotonic
from typing import Any

logger = logging.getLogger(__name__)

# Singleton job queue — created lazily via ``get_job_queue()``.
_instance: JobQueue | None = None
_instance_lock = threading.Lock()

# Job status constants
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"

# Default max workers — kept low; Pi Zero has limited resources.
_DEFAULT_MAX_WORKERS = 2
_DEFAULT_COMPLETED_TTL_SECONDS = 15 * 60.0
_DEFAULT_MAX_RETAINED_FINISHED_JOBS = 128


class JobQueue:
    """A thin wrapper around :class:`ThreadPoolExecutor` with status tracking."""

    def __init__(
        self,
        max_workers: int = _DEFAULT_MAX_WORKERS,
        *,
        completed_ttl_seconds: float = _DEFAULT_COMPLETED_TTL_SECONDS,
        max_retained_finished_jobs: int = _DEFAULT_MAX_RETAINED_FINISHED_JOBS,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="job-queue"
        )
        self._jobs: dict[str, _JobEntry] = {}
        self._lock = threading.Lock()
        self._completed_ttl_seconds = max(0.0, completed_ttl_seconds)
        self._max_retained_finished_jobs = max(0, max_retained_finished_jobs)
        self._clock = clock

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, fn: Any, *args: Any, **kwargs: Any) -> str:
        """Submit *fn(*args, **kwargs)* for background execution.

        Returns a unique ``job_id`` (UUID4 hex string) that can be passed to
        :meth:`get_status` to poll for completion.
        """
        job_id = uuid.uuid4().hex
        entry = _JobEntry(job_id)

        with self._lock:
            self._prune_finished_locked()
            self._jobs[job_id] = entry

        future = self._executor.submit(self._run, entry, fn, *args, **kwargs)
        entry.future = future
        return job_id

    def get_status(self, job_id: str) -> dict[str, Any]:
        """Return the current status of *job_id*.

        Returns a dict with keys:
        - ``status``: one of ``pending``, ``running``, ``done``, ``error``
        - ``result``: the return value when ``status == "done"``
        - ``error``:  a string description when ``status == "error"``
        """
        with self._lock:
            self._prune_finished_locked()
            entry = self._jobs.get(job_id)

        if entry is None:
            return {"status": "unknown", "error": "Job not found"}

        return entry.to_dict()

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the underlying thread pool."""
        self._executor.shutdown(wait=wait)

    @property
    def pending_jobs(self) -> int:
        """Number of jobs that have not yet completed (pending or running)."""
        with self._lock:
            self._prune_finished_locked()
            return sum(
                1
                for e in self._jobs.values()
                if e.status in (STATUS_PENDING, STATUS_RUNNING)
            )

    def _prune_finished_locked(self) -> None:
        """Drop stale or excess finished jobs.

        Active jobs are never pruned. Finished entries naturally expire after a
        bounded retention window so a long-lived device does not accumulate
        one status record per historical render forever.
        """
        now = self._clock()
        finished_entries: list[tuple[str, float]] = []

        for job_id, entry in list(self._jobs.items()):
            finished_at = entry.finished_at
            if finished_at is None:
                continue
            if now - finished_at >= self._completed_ttl_seconds:
                del self._jobs[job_id]
                continue
            finished_entries.append((job_id, finished_at))

        excess = len(finished_entries) - self._max_retained_finished_jobs
        if excess <= 0:
            return

        finished_entries.sort(key=lambda item: item[1])
        for job_id, _finished_at in finished_entries[:excess]:
            self._jobs.pop(job_id, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run(self, entry: _JobEntry, fn: Any, *args: Any, **kwargs: Any) -> Any:
        entry.status = STATUS_RUNNING
        try:
            result = fn(*args, **kwargs)
            entry.result = result
            entry.status = STATUS_DONE
            entry.finished_at = self._clock()
            return result
        except Exception as exc:
            logger.exception("Job %s failed", entry.job_id)
            entry.error = str(exc)
            entry.status = STATUS_ERROR
            entry.finished_at = self._clock()
            raise


class _JobEntry:
    """Mutable record tracking one enqueued job."""

    __slots__ = ("job_id", "status", "result", "error", "future", "finished_at")

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.status: str = STATUS_PENDING
        self.result: Any = None
        self.error: str | None = None
        self.future: Future | None = None  # type: ignore[type-arg]
        self.finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"status": self.status}
        if self.status == STATUS_DONE and self.result is not None:
            d["result"] = self.result
        if self.status == STATUS_ERROR and self.error is not None:
            d["error"] = self.error
        return d


def get_job_queue() -> JobQueue:
    """Return the module-level singleton :class:`JobQueue`, creating it lazily."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = JobQueue()
    return _instance


def reset_job_queue() -> None:
    """Shut down and discard the singleton (test helper)."""
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.shutdown(wait=False)
            _instance = None
