#!/usr/bin/env python3
import os
import sqlite3
from datetime import datetime


def main():
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

    # Recent 50 refreshes summary
    cur.execute(
        """
        SELECT refresh_id, ts, plugin_id, instance, playlist, used_cached,
               request_ms, generate_ms, preprocess_ms, display_ms,
               cpu_percent, memory_percent
        FROM refresh_events
        ORDER BY ts DESC
        LIMIT 50
        """
    )
    rows = cur.fetchall()

    report_path = os.path.join(base_dir, "docs", "benchmarks_report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("## InkyPi Benchmarks Report\n\n")
        fh.write(f"Generated: {datetime.utcnow().isoformat()}Z\n\n")
        fh.write("### Recent refreshes (latest 50)\n\n")
        fh.write("| ts | plugin | instance | playlist | cached | req(ms) | gen(ms) | pre(ms) | disp(ms) | cpu% | mem% |\n")
        fh.write("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|\n")
        for r in rows:
            (_rid, ts, plugin, inst, pl, cached, req, gen, pre, disp, cpu, mem) = r
            iso = datetime.utcfromtimestamp(ts).isoformat() + "Z"
            fh.write(
                f"| {iso} | {plugin or ''} | {inst or ''} | {pl or ''} | {cached or 0} | {req or ''} | {gen or ''} | {pre or ''} | {disp or ''} | {cpu or ''} | {mem or ''} |\n"
            )

        fh.write("\n### Stage samples (latest 50)\n\n")
        fh.write("| ts | refresh_id | stage | duration(ms) | extra |\n")
        fh.write("|---|---|---|---:|---|\n")
        cur.execute(
            """
            SELECT ts, refresh_id, stage, duration_ms, COALESCE(extra_json, '')
            FROM stage_events
            ORDER BY ts DESC
            LIMIT 50
            """
        )
        for ts, rid, stage, dur, extra in cur.fetchall():
            iso = datetime.utcfromtimestamp(ts).isoformat() + "Z"
            fh.write(f"| {iso} | {rid} | {stage} | {dur or ''} | {extra or ''} |\n")

    conn.close()
    print("Wrote:", report_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


