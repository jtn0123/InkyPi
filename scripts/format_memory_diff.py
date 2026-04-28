#!/usr/bin/env python3
"""JTN-610: Format a Markdown memory diff comment from two JSON summaries.

Consumes two JSON files produced by ``scripts/memory_diff.py`` — one for the
PR branch, one for the base branch — and renders a sticky-comment-friendly
Markdown body suitable for posting via ``actions/github-script``.

The output deliberately starts with a hidden HTML marker
``<!-- memory-diff:jtn-610 -->`` so the workflow can find and overwrite the
previous comment on every force-push instead of piling new comments onto
the PR.

Usage:
    python scripts/format_memory_diff.py \
        --base base.json --pr pr.json --output comment.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The marker is the first line of the comment and is how github-script finds
# the previous comment to overwrite. Do NOT change without also updating the
# workflow that looks for it.
STICKY_MARKER = "<!-- memory-diff:jtn-610 -->"

# Delta (in bytes) above which we flag a row with a warning emoji. Keep this
# high enough that allocator arena churn does not turn the whole table yellow.
WARN_DELTA_BYTES = 5 * 1024 * 1024
DETAIL_DELTA_FLOOR_BYTES = 256 * 1024
GROUP_TOP_N = 10


def _fmt_bytes(n: int) -> str:
    """Render a byte count as a short human-friendly string."""
    if n == 0:
        return "0 B"
    abs_n = abs(n)
    if abs_n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.2f} MB"
    if abs_n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _fmt_delta(delta: int) -> str:
    """Render a signed delta with a leading sign so the column reads naturally."""
    if delta == 0:
        return "0"
    sign = "+" if delta > 0 else ""
    formatted = f"{sign}{_fmt_bytes(delta)}"
    if abs(delta) >= WARN_DELTA_BYTES:
        return f"**{formatted}** :warning:"
    return formatted


def _short_location(loc: str, max_len: int = 60) -> str:
    """Shorten allocator location strings so the table stays readable.

    memray and tracemalloc emit absolute paths; we keep only the last two
    path components to avoid a comment that is 200 columns wide.
    """
    if not loc:
        return "<unknown>"
    # Drop runner-specific absolute path prefix, keep last 2 segments.
    parts = loc.replace("\\", "/").split("/")
    tail = "/".join(parts[-2:]) if len(parts) > 1 else parts[-1]
    if len(tail) > max_len:
        tail = "..." + tail[-(max_len - 3) :]
    # Escape markdown pipe characters inside the location string so a
    # filename containing a pipe cannot break the table rendering.
    return tail.replace("|", "\\|")


def _location_group(loc: str) -> str:
    """Return a reviewer-friendly bucket for a source allocator location."""
    if not loc:
        return "<unknown>"
    normalized = loc.replace("\\", "/")
    if normalized.startswith("<string>"):
        return "profile harness"
    if normalized.startswith("<frozen importlib"):
        return "python import system"
    if normalized.startswith("<frozen"):
        return "python runtime"

    parts = [part for part in normalized.split("/") if part]
    if "site-packages" in parts:
        idx = parts.index("site-packages")
        if idx + 1 < len(parts):
            package = parts[idx + 1]
            if package.endswith(".py"):
                package = package[:-3]
            return package.replace("|", "\\|")
    if "src" in parts:
        idx = parts.index("src")
        if idx + 1 < len(parts):
            package = parts[idx + 1]
            if package.endswith(".py"):
                package = package[:-3]
            return f"inkypi:{package}".replace("|", "\\|")
    for idx, part in enumerate(parts):
        if part.startswith("python") and idx + 1 < len(parts):
            return "python stdlib"
    return _short_location(loc, max_len=40)


def _is_displayable_allocator(entry: dict) -> bool:
    """Drop profiler-wrapper rows that are not actionable app attribution."""
    loc = str(entry.get("location", ""))
    return not loc.startswith("<string>")


def _load(path: Path) -> dict:
    """Load a JSON summary, returning an empty shell if the file is missing.

    Missing files are tolerated so the formatter can still emit a helpful
    comment on the very first run when the base-branch measurement hasn't
    been produced yet (e.g. cache miss + setup flake).
    """
    if not path.exists():
        return {
            "backend": "unavailable",
            "total_rss_bytes": 0,
            "module_count": 0,
            "allocators": [],
        }
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        print(
            f"format_memory_diff: failed to parse {path}: {exc}",
            file=sys.stderr,
        )
        return {
            "backend": "unavailable",
            "total_rss_bytes": 0,
            "module_count": 0,
            "allocators": [],
        }


def _merge_allocators(base: list[dict], pr: list[dict]) -> list[dict]:
    """Merge two allocator lists by location, producing union-sorted rows.

    Returns a list of dicts with ``location``, ``base_bytes``, ``pr_bytes``,
    and ``delta`` keyed fields, sorted by absolute delta descending so the
    biggest regressors land at the top of the table.
    """
    index: dict[str, dict] = {}
    for entry in base:
        loc = str(entry.get("location", "<unknown>"))
        index[loc] = {
            "location": loc,
            "base_bytes": int(entry.get("bytes", 0)),
            "pr_bytes": 0,
        }
    for entry in pr:
        loc = str(entry.get("location", "<unknown>"))
        if loc in index:
            index[loc]["pr_bytes"] = int(entry.get("bytes", 0))
        else:
            index[loc] = {
                "location": loc,
                "base_bytes": 0,
                "pr_bytes": int(entry.get("bytes", 0)),
            }
    rows = list(index.values())
    for row in rows:
        row["delta"] = row["pr_bytes"] - row["base_bytes"]
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return rows


def _merge_allocator_groups(base: list[dict], pr: list[dict]) -> list[dict]:
    """Aggregate allocator rows into package/module buckets before diffing."""
    index: dict[str, dict] = {}
    for side, entries in (("base_bytes", base), ("pr_bytes", pr)):
        for entry in entries:
            group = _location_group(str(entry.get("location", "<unknown>")))
            bucket = index.setdefault(
                group,
                {"location": group, "base_bytes": 0, "pr_bytes": 0},
            )
            bucket[side] += int(entry.get("bytes", 0))
    rows = list(index.values())
    for row in rows:
        row["delta"] = row["pr_bytes"] - row["base_bytes"]
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return rows


def _significant_rows(rows: list[dict], top: int) -> list[dict]:
    """Return rows worth showing, suppressing zero-delta allocator noise."""
    return [
        row for row in rows if abs(int(row.get("delta", 0))) >= DETAIL_DELTA_FLOOR_BYTES
    ][:top]


def format_comment(base: dict, pr: dict, top: int = 20) -> str:
    """Build the full Markdown comment body.

    The comment has three parts:

    1. Header with the sticky marker + a summary line (total RSS delta,
       module-count delta, which backend was used).
    2. A collapsible details block containing the top-N allocator table.
    3. A footer linking back to JTN-610 so reviewers know where to file
       bugs about the gate itself.
    """
    base_backend = str(base.get("backend", "unavailable"))
    pr_backend = str(pr.get("backend", "unavailable"))

    base_rss = int(base.get("total_rss_bytes", 0) or 0)
    pr_rss = int(pr.get("total_rss_bytes", 0) or 0)
    rss_delta = pr_rss - base_rss

    base_mods = int(base.get("module_count", 0) or 0)
    pr_mods = int(pr.get("module_count", 0) or 0)
    mod_delta = pr_mods - base_mods

    base_allocators = [
        entry for entry in list(base.get("allocators", [])) if _is_displayable_allocator(entry)
    ]
    pr_allocators = [
        entry for entry in list(pr.get("allocators", [])) if _is_displayable_allocator(entry)
    ]
    rows = _significant_rows(_merge_allocators(base_allocators, pr_allocators), top)
    group_rows = _significant_rows(
        _merge_allocator_groups(base_allocators, pr_allocators),
        GROUP_TOP_N,
    )
    base_sample_count = int(
        base.get("allocator_sample_limit")
        or base.get("sampled_allocator_count")
        or len(base_allocators)
    )
    pr_sample_count = int(
        pr.get("allocator_sample_limit")
        or pr.get("sampled_allocator_count")
        or len(pr_allocators)
    )

    lines: list[str] = []
    lines.append(STICKY_MARKER)
    lines.append("## Memory diff vs base")
    lines.append("")

    if base_backend == "unavailable" and pr_backend == "unavailable":
        lines.append(
            ":information_source: Memory profiling is not yet available on this "
            "runner — install `memray` or ensure `tracemalloc` is reachable."
        )
        lines.append("")
        lines.append("<sub>JTN-610 · backend=unavailable</sub>")
        return "\n".join(lines) + "\n"

    # Summary row — mirrors the `| Total |` row from the issue sketch but
    # lives in its own compact table so readers can grok the delta at a glance.
    lines.append("| Metric | Base | PR | Delta |")
    lines.append("|---|---|---|---|")
    lines.append(
        f"| Peak RSS | {_fmt_bytes(base_rss)} | {_fmt_bytes(pr_rss)} "
        f"| {_fmt_delta(rss_delta)} |"
    )
    lines.append(
        f"| `sys.modules` count | {base_mods} | {pr_mods} | "
        f"{'+' if mod_delta > 0 else ''}{mod_delta} |"
    )
    lines.append("")

    lines.append("### Largest grouped allocator deltas")
    lines.append("")
    lines.append("| Group | Base | PR | Delta |")
    lines.append("|---|---|---|---|")
    if not group_rows:
        lines.append("| _(no significant grouped allocator deltas)_ | — | — | — |")
    else:
        lines.extend(
            (
                f"| `{row['location']}` "
                f"| {_fmt_bytes(row['base_bytes'])} "
                f"| {_fmt_bytes(row['pr_bytes'])} "
                f"| {_fmt_delta(row['delta'])} |"
            )
            for row in group_rows
        )
    lines.append("")

    # Collapse the long allocator table by default so the PR conversation
    # stays skimmable. GitHub renders <details> nicely in comments.
    lines.append("<details>")
    detail_summary = (
        f"Source-location detail: top {len(rows)} deltas"
        if rows
        else "Source-location detail: no significant deltas"
    )
    lines.append(
        f"<summary>{detail_summary} "
        f"(sampled base={base_sample_count}, PR={pr_sample_count})</summary>"
    )
    lines.append("")
    lines.append("| # | Location | Base | PR | Delta |")
    lines.append("|---|---|---|---|---|")
    if not rows:
        lines.append("| — | _(no significant source-location deltas)_ | — | — | — |")
    else:
        for i, row in enumerate(rows, 1):
            lines.append(
                f"| {i} | `{_short_location(row['location'])}` "
                f"| {_fmt_bytes(row['base_bytes'])} "
                f"| {_fmt_bytes(row['pr_bytes'])} "
                f"| {_fmt_delta(row['delta'])} |"
            )
    lines.append("")
    lines.append("</details>")
    lines.append("")
    lines.append(
        f"<sub>JTN-610 · backend=base:{base_backend}, pr:{pr_backend} · "
        "informational only, does not block merge. Hard RSS budgets are enforced "
        "separately by JTN-608. Source-location rows are sampled allocator "
        "attribution, not exact module ownership.</sub>"
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Base-branch JSON summary")
    parser.add_argument("--pr", required=True, help="PR-branch JSON summary")
    parser.add_argument(
        "--output",
        default="-",
        help="Path to write the Markdown comment to, or '-' for stdout.",
    )
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args(argv)

    base = _load(Path(args.base))
    pr = _load(Path(args.pr))
    body = format_comment(base, pr, top=args.top)

    if args.output == "-":
        sys.stdout.write(body)
    else:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
