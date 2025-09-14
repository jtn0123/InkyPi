#!/usr/bin/env python3
import os
import sqlite3
from datetime import datetime, UTC


def main(limit: int = 20) -> int:
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_dir = os.path.join(base_dir, "src")

    import sys

    sys.path.insert(0, src_dir)

    from config import Config

    cfg = Config()
    db_path = cfg.get_config("benchmarks_db_path", default=os.path.join(cfg.BASE_DIR, "benchmarks.db"))
    if not os.path.exists(db_path):
        print("No benchmarks database found at:", db_path)
        return 0

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT refresh_id, ts, plugin_id, instance, playlist, used_cached,
               request_ms, generate_ms, preprocess_ms, display_ms,
               cpu_percent, memory_percent
        FROM refresh_events
        ORDER BY ts DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = cur.fetchall()

    # Build rows with formatted values
    formatted = []
    for r in rows:
        rid, ts, plugin, inst, pl, cached, req, gen, pre, disp, cpu, mem = r
        ts_s = datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        rid_s = str(rid)
        plugin_s = plugin or ""
        inst_s = inst or ""
        pl_s = pl or ""
        cached_s = "Y" if cached else "N"
        req_s = "" if req is None else str(int(req))
        gen_s = "" if gen is None else str(int(gen))
        pre_s = "" if pre is None else str(int(pre))
        disp_s = "" if disp is None else str(int(disp))
        cpu_s = "" if cpu is None else f"{float(cpu):.1f}"
        mem_s = "" if mem is None else f"{float(mem):.1f}"
        formatted.append([ts_s, rid_s, plugin_s, inst_s, pl_s, cached_s, req_s, gen_s, pre_s, disp_s, cpu_s, mem_s])

    # Column definitions: (header, max_width, align)
    cols = [
        ("ts", 23, "left"),
        ("refresh_id", 12, "left"),
        ("plugin", 12, "left"),
        ("instance", 14, "left"),
        ("playlist", 14, "left"),
        ("cached", 6, "right"),
        ("req(ms)", 8, "right"),
        ("gen(ms)", 8, "right"),
        ("pre(ms)", 8, "right"),
        ("disp(ms)", 9, "right"),
        ("cpu%", 6, "right"),
        ("mem%", 6, "right"),
    ]

    # Compute widths
    widths = []
    for idx, (hdr, maxw, _align) in enumerate(cols):
        max_len = len(hdr)
        for row in formatted:
            cell = row[idx]
            if cell is None:
                cell = ""
            max_len = max(max_len, len(cell))
        widths.append(min(max_len, maxw))

    # Helper to truncate
    def trunc(s: str, w: int) -> str:
        if len(s) <= w:
            return s
        if w <= 1:
            return s[:w]
        return s[: w - 1] + "…"

    # Render header
    header_cells = []
    for (hdr, _m, align), w in zip(cols, widths):
        header_cells.append(f"{hdr:<{w}}" if align == "left" else f"{hdr:>{w}}")
    print(" | ".join(header_cells))
    print("-+-".join("-" * w for w in widths))

    # Render rows
    for row in formatted:
        cells = []
        for idx, ((_, _m, align), w) in enumerate(zip(cols, widths)):
            val = row[idx] or ""
            # Use truncated refresh_id
            if idx == 1 and len(val) > w:
                val = trunc(val, w)
            else:
                val = trunc(val, w)
            cells.append(f"{val:<{w}}" if align == "left" else f"{val:>{w}}")
        print(" | ".join(cells))

    conn.close()
    return 0


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Show recent InkyPi benchmark runs")
    p.add_argument("--limit", type=int, default=20, help="number of rows to display")
    args = p.parse_args()
    raise SystemExit(main(args.limit))


