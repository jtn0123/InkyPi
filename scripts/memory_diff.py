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

# Cap on how many allocators we surface in the diff comment. Matches the
# acceptance criteria in JTN-610 ("top 20 allocators").
TOP_N = 20


def _startup_env() -> dict[str, str]:
    """Environment for the child profiling subprocess.

    Mirrors the setup used by ``tests/unit/test_lazy_imports.py`` so the
    measurement reflects the same startup path that CI's lazy-import gate
    checks. ``INKYPI_NO_REFRESH=1`` keeps plugin side-effects quiet.
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC_DIR)
    env["INKYPI_ENV"] = "dev"
    env["INKYPI_NO_REFRESH"] = "1"
    env["PYTHONWARNINGS"] = "ignore"
    return env


def _read_rss_bytes() -> int:
    """Best-effort RSS read — returns 0 when psutil/resource are unavailable."""
    try:
        import resource  # noqa: PLC0415 — stdlib, Linux/macOS only

        rusage = resource.getrusage(resource.RUSAGE_SELF)
        # Linux reports ru_maxrss in kilobytes; macOS reports in bytes.
        if sys.platform == "darwin":
            return int(rusage.ru_maxrss)
        return int(rusage.ru_maxrss) * 1024
    except Exception:
        return 0


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
            {"location": str(s.traceback[0]), "bytes": int(s.size)}
            for s in stats[:100]
        ]
        # Best-effort RSS — tracemalloc size is the tracked Python heap, not RSS.
        rss = 0
        try:
            import resource
            r = resource.getrusage(resource.RUSAGE_SELF)
            rss = r.ru_maxrss * (1 if sys.platform == "darwin" else 1024)
        except Exception:
            pass
        print(json.dumps({
            "backend": "tracemalloc",
            "total_rss_bytes": rss,
            "module_count": len(sys.modules),
            "allocators": allocators,
        }))
        """)
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
    return json.loads(last)


def _run_memray() -> dict:
    """Profile ``import inkypi`` using memray.

    We shell out to ``memray run`` so the capture file uses the same format
    as ``memray stats`` expects, then parse ``memray stats --json``.
    """
    # Verify memray is actually importable before we try to use it.
    try:
        import memray  # noqa: F401,PLC0415
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

        stats_cmd = [
            sys.executable,
            "-m",
            "memray",
            "stats",
            "--json",
            str(capture),
        ]
        stats_proc = subprocess.run(  # noqa: S603 — fixed argv
            stats_cmd,
            env=_startup_env(),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if stats_proc.returncode != 0:
            raise RuntimeError(
                "memray stats failed.\n"
                f"stdout:\n{stats_proc.stdout}\n\nstderr:\n{stats_proc.stderr}"
            )

        # memray stats --json shape: {"total_bytes_allocated": int,
        #                              "top_locations_by_size": [...]}
        # Field names vary across versions; handle both "top_locations_by_size"
        # and "top_allocations_by_size".
        raw = json.loads(stats_proc.stdout)
        candidates = (
            raw.get("top_locations_by_size")
            or raw.get("top_allocations_by_size")
            or raw.get("top_locations")
            or []
        )
        allocators: list[dict] = []
        for entry in candidates[:100]:
            loc = (
                entry.get("location")
                or entry.get("file")
                or entry.get("name")
                or "<unknown>"
            )
            size = int(
                entry.get("size") or entry.get("total_bytes") or entry.get("bytes") or 0
            )
            allocators.append({"location": str(loc), "bytes": size})

    # Also count modules loaded after import to feed the summary row.
    module_code = textwrap.dedent("""
        import json, sys
        import inkypi  # noqa: F401
        print(json.dumps({"count": len(sys.modules)}))
        """)
    mod_proc = subprocess.run(  # noqa: S603 — fixed argv
        [sys.executable, "-c", module_code],
        env=_startup_env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    module_count = 0
    if mod_proc.returncode == 0:
        last = [line for line in mod_proc.stdout.splitlines() if line.strip()][-1]
        module_count = int(json.loads(last)["count"])

    return {
        "backend": "memray",
        "total_rss_bytes": _read_rss_bytes(),
        "module_count": module_count,
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
        default=TOP_N,
        help="Number of top allocators to keep in the output JSON.",
    )
    args = parser.parse_args(argv)

    backend = _detect_backend(args.backend)
    print(f"memory_diff: using backend={backend}", file=sys.stderr)

    result = _run_memray() if backend == "memray" else _run_tracemalloc()

    # Trim to the top-N allocators by bytes before writing.
    allocators = sorted(
        result.get("allocators", []),
        key=lambda a: int(a.get("bytes", 0)),
        reverse=True,
    )[: args.top]
    result["allocators"] = allocators

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
