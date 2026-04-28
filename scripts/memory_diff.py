#!/usr/bin/env python3
"""JTN-610: Startup memory profile capture for the per-PR memory diff job.

This helper is invoked twice by ``.github/workflows/memory-diff.yml`` — once
against the PR branch and once against the base branch — to produce
comparable JSON summaries of what an ``import inkypi`` actually allocates.

Unlike ``scripts/test_install_memcap.sh`` (JTN-608, which samples RSS of the
running service), this script profiles the *startup allocator breakdown* so
a reviewer can see which modules grew at import time. It is deliberately
orthogonal to the render-exercise RSS gate — JTN-613 tracks fixing that.

Two backends are supported:

* **memray** (preferred) — gives per-file allocation bytes and is much more
  accurate for C-extension backed allocators like numpy / PIL.
* **tracemalloc** (stdlib fallback) — always available, per-file aggregated
  bytes. Used when ``memray`` is not installed (e.g. first-time setup before
  the lockfile is regenerated).

Output format (stable so ``format_memory_diff.py`` can parse both halves):

    {
      "backend": "memray" | "tracemalloc",
      "total_rss_bytes": int,           # best-effort process RSS after import
      "module_count": int,              # len(sys.modules) after import
      "allocators": [
        {"location": "<file>:<line or module>", "bytes": int},
        ...
      ]
    }

Usage:
    python scripts/memory_diff.py --output pr.json
    python scripts/memory_diff.py --backend tracemalloc --output base.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"

# Capture more than the comment displays. Comparing only each side's top 20
# makes the diff lie with "0 B" whenever a location merely fell out of the
# other side's top 20. The formatter still keeps the PR comment short.
DEFAULT_ALLOCATOR_SAMPLE_LIMIT = 500


def _startup_env() -> dict[str, str]:
    """Environment for the child profiling subprocess.

    Mirrors the setup used by ``tests/unit/test_lazy_imports.py`` so the
    measurement reflects the same startup path that CI's lazy-import gate
    checks. ``INKYPI_NO_REFRESH=1`` keeps plugin side-effects quiet.
    """
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(SRC_DIR)
        if not existing_pythonpath
        else str(SRC_DIR) + os.pathsep + existing_pythonpath
    )
    env["INKYPI_ENV"] = "dev"
    env["INKYPI_NO_REFRESH"] = "1"
    env["PYTHONWARNINGS"] = "ignore"
    return env


def _run_plain_import_stats() -> dict[str, int]:
    """Measure RSS and module count in a plain child process.

    Keep this separate from memray/tracemalloc. Profilers add their own import
    and allocation overhead, which makes the summary row look precise while
    measuring the tool rather than InkyPi startup.
    """
    code = textwrap.dedent("""
        import json
        import resource
        import sys

        import inkypi  # noqa: F401

        rusage = resource.getrusage(resource.RUSAGE_SELF)
        rss = int(rusage.ru_maxrss)
        if sys.platform != "darwin":
            rss *= 1024

        print(json.dumps({
            "module_count": len(sys.modules),
            "total_rss_bytes": rss,
        }))
        """)
    proc = subprocess.run(  # noqa: S603 — fixed argv
        [sys.executable, "-c", code],
        env=_startup_env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0:
        return {"module_count": 0, "total_rss_bytes": 0}
    last = [line for line in proc.stdout.splitlines() if line.strip()][-1]
    raw = json.loads(last)
    return {
        "module_count": int(raw.get("module_count", 0) or 0),
        "total_rss_bytes": int(raw.get("total_rss_bytes", 0) or 0),
    }


def _run_tracemalloc() -> dict:
    """Profile ``import inkypi`` using stdlib tracemalloc.

    Runs in a subprocess so ``sys.modules`` starts empty and tracemalloc
    captures every module-level allocation done during import.
    """
    code = textwrap.dedent("""
        import json, sys, tracemalloc
        tracemalloc.start()
        import inkypi  # noqa: F401 — we only care about the import side effects
        snapshot = tracemalloc.take_snapshot()
        stats = snapshot.statistics("filename")
        allocators = [
            {{"location": str(s.traceback[0]), "bytes": int(s.size)}}
            for s in stats[:{limit}]
        ]
        print(json.dumps({{
            "backend": "tracemalloc",
            "total_rss_bytes": 0,
            "module_count": 0,
            "allocators": allocators,
        }}))
        """).format(limit=DEFAULT_ALLOCATOR_SAMPLE_LIMIT)
    proc = subprocess.run(  # noqa: S603 — trusted stdlib-only snippet
        [sys.executable, "-c", code],
        env=_startup_env(),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"tracemalloc probe failed (rc={proc.returncode}).\n"
            f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
        )
    # The subprocess may emit warnings / log lines before the JSON; take the
    # last non-empty line.
    last = [line for line in proc.stdout.splitlines() if line.strip()][-1]
    result = json.loads(last)
    result.update(_run_plain_import_stats())
    return result


def _run_memray() -> dict:
    """Profile ``import inkypi`` using memray.

    Runs ``memray run`` in a subprocess to produce a capture file, then
    opens it with memray's Python API (``FileReader``) to aggregate
    high-watermark allocations by source location. The CLI's ``stats``
    subcommand emits a human-readable report to stdout (not JSON), so we
    go straight to the API for a stable machine-readable result.
    """
    # Verify memray is actually importable before we try to use it.
    try:
        import memray  # noqa: F401,PLC0415
        from memray import FileReader  # noqa: PLC0415
    except ImportError as exc:
        raise RuntimeError("memray backend requested but not installed") from exc

    with tempfile.TemporaryDirectory() as tmp:
        capture = Path(tmp) / "inkypi.bin"
        # memray refuses to overwrite an existing file; pass -f to be safe.
        run_cmd = [
            sys.executable,
            "-m",
            "memray",
            "run",
            "-f",
            "-o",
            str(capture),
            "-c",
            "import inkypi",
        ]
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            run_cmd,
            env=_startup_env(),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "memray run failed.\n"
                f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
            )

        # Aggregate high-watermark allocations by source location using the
        # FileReader API. ``get_high_watermark_allocation_records`` returns
        # the set of allocations live at peak RSS — a better signal than
        # total-ever-allocated because short-lived churn is excluded.
        reader = FileReader(str(capture))
        by_location: dict[str, int] = {}
        records = reader.get_high_watermark_allocation_records(
            merge_threads=True,
        )
        for rec in records:
            size = int(getattr(rec, "size", 0) or 0)
            if size <= 0:
                continue
            # Try Python-only stack first (always available on Python frames),
            # then fall back to the hybrid/native stack if the allocation
            # happened inside a C extension. Each yields (func, file, lineno)
            # tuples from innermost frame outward.
            loc = "<unknown>"
            for stack_method in ("stack_trace", "hybrid_stack_trace"):
                try:
                    frames = list(getattr(rec, stack_method)())
                except Exception:
                    frames = []
                if frames:
                    _func, fname, lineno = frames[0]
                    loc = f"{fname}:{lineno}"
                    break
            by_location[loc] = by_location.get(loc, 0) + size

        allocators: list[dict] = [
            {"location": loc, "bytes": total}
            for loc, total in sorted(
                by_location.items(), key=lambda kv: kv[1], reverse=True
            )
        ]

    plain_stats = _run_plain_import_stats()

    return {
        "backend": "memray",
        "total_rss_bytes": plain_stats["total_rss_bytes"],
        "module_count": plain_stats["module_count"],
        "allocators": allocators,
    }


def _detect_backend(requested: str) -> str:
    """Resolve the backend request, falling back gracefully.

    ``auto`` prefers memray when importable, else tracemalloc. Explicit
    ``memray`` / ``tracemalloc`` values are respected if available.
    """
    if requested == "tracemalloc":
        return "tracemalloc"
    if requested == "memray":
        try:
            import memray  # noqa: F401,PLC0415
        except ImportError:
            print(
                "memory_diff: memray requested but not installed; "
                "falling back to tracemalloc",
                file=sys.stderr,
            )
            return "tracemalloc"
        return "memray"
    # auto
    try:
        import memray  # noqa: F401,PLC0415

        return "memray"
    except ImportError:
        return "tracemalloc"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        required=True,
        help="Path to write the JSON summary to.",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "memray", "tracemalloc"),
        default="auto",
        help="Profiling backend. 'auto' uses memray when available.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_ALLOCATOR_SAMPLE_LIMIT,
        help=(
            "Number of top allocators to keep in the output JSON. Keep this "
            "larger than the comment display limit so base/PR comparison is "
            "not distorted by top-N truncation."
        ),
    )
    args = parser.parse_args(argv)

    backend = _detect_backend(args.backend)
    print(f"memory_diff: using backend={backend}", file=sys.stderr)

    # memray is preferred, but if it blows up (missing method, bad capture,
    # container sandboxing quirks) we fall back to tracemalloc so the job
    # still produces *a* comment instead of dying with a traceback. JTN-610
    # specifically calls out "Tolerant of first-time setup".
    if backend == "memray":
        try:
            result = _run_memray()
        except Exception as exc:  # noqa: BLE001 — intentional broad fallback
            print(
                f"memory_diff: memray backend failed ({exc}); "
                "falling back to tracemalloc",
                file=sys.stderr,
            )
            result = _run_tracemalloc()
    else:
        result = _run_tracemalloc()

    # Trim to the sampled allocator limit before writing. The formatter applies
    # its own smaller display limit after merging base + PR locations.
    sampled_allocator_count = len(result.get("allocators", []))
    allocators = sorted(
        result.get("allocators", []),
        key=lambda a: int(a.get("bytes", 0)),
        reverse=True,
    )[: args.top]
    result["allocators"] = allocators
    result["sampled_allocator_count"] = sampled_allocator_count
    result["allocator_sample_limit"] = args.top

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2))
    print(
        f"memory_diff: wrote {len(allocators)} allocators to {out_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
