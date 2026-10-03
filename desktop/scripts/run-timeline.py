"""Timeline of one run: every event with its offset from the first, in ms.

Written to settle whether a cancelled run kept going or was killed and then
overwritten, which look identical from the run row alone.
"""

import json
import sqlite3
import sys


def main() -> int:
    db_path = sys.argv[1]
    run_id = sys.argv[2] if len(sys.argv) > 2 else None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    if run_id is None:
        run_id = conn.execute(
            "select run_id from runs order by created_at desc limit 1"
        ).fetchone()["run_id"]

    run = conn.execute(
        "select run_id, status, error, created_at, started_at, finished_at, duration_s,"
        " prompt_count, completed_prompts, prompt_rows"
        " from runs where run_id = ?",
        (run_id,),
    ).fetchone()
    print(f"run {run['run_id']}  status={run['status']}")
    print(f"  error          : {run['error']}")
    print(f"  created_at     : {run['created_at']}")
    print(f"  started_at     : {run['started_at']}")
    print(f"  finished_at    : {run['finished_at']}")
    print(f"  duration_s     : {run['duration_s']}")
    print(f"  prompt_count   : {run['prompt_count']}")
    print(f"  completed      : {run['completed_prompts']}")
    print(f"  prompt_rows    : {run['prompt_rows']}")

    rows = conn.execute(
        "select seq, type, ts_ms, payload_json from run_events where run_id = ?"
        " order by seq",
        (run_id,),
    ).fetchall()
    if not rows:
        print("  no events")
        return 0

    t0 = rows[0]["ts_ms"]
    print(f"\n  {len(rows)} events, offsets in ms from the first:")
    for r in rows:
        extra = ""
        if r["type"] == "log":
            extra = " " + json.loads(r["payload_json"]).get("message", "")[:60]
        elif r["type"] in ("run_finished", "run_failed"):
            extra = " " + json.dumps(json.loads(r["payload_json"]))[:120]
        print(f"  +{r['ts_ms'] - t0:>7} ms  seq {r['seq']:>4}  {r['type']}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
