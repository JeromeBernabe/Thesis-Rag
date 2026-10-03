"""Row counts plus the most recent run, as JSON.

Used by scripts/drive-window.mjs, which watches this file change while a run
executes in the real window. Read-only, so it cannot perturb the database it is
observing, and safe to call while the app holds the WAL.
"""

import json
import sqlite3
import sys


def main() -> int:
    db_path = sys.argv[1]
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    newest = conn.execute(
        "select run_id, status, error, prompt_count from runs"
        " order by created_at desc limit 1"
    ).fetchone()

    def count(table):
        return conn.execute(f"select count(*) from {table}").fetchone()[0]

    print(
        json.dumps(
            {
                "runs": count("runs"),
                "prompts": count("prompt_rows"),
                "events": count("run_events"),
                "newest": dict(newest) if newest else None,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
