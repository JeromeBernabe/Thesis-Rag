"""Report what one run actually stored, for verifying the host end to end.

Prints a single JSON object so a Node caller can assert on it. Unmeasured
metrics are checked for `null` specifically: a run that skipped judging must not
report zeroes, because a zero is a real number that would silently outrank a
genuine measurement downstream.
"""

import json
import sqlite3
import sys


def main() -> int:
    run_id = sys.argv[1]
    db_path = sys.argv[2]

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    run = conn.execute(
        "select run_id, status, dataset, prompt_count, duration_s, error"
        " from runs where run_id = ?",
        (run_id,),
    ).fetchone()
    if run is None:
        print(json.dumps({"found": False}))
        return 1

    prompts = [
        dict(r)
        for r in conn.execute(
            "select system_id, prompt_id, answer, retrieved_k, context_recall,"
            " faithfulness, answer_relevancy, reward"
            " from prompt_rows where run_id = ? order by system_id, prompt_index",
            (run_id,),
        )
    ]
    events = conn.execute(
        "select count(*) from run_events where run_id = ?", (run_id,)
    ).fetchone()[0]
    steps = conn.execute(
        "select count(*) from training_steps where run_id = ?", (run_id,)
    ).fetchone()[0]

    # Which nullable metric columns came back null, so the caller can require
    # that at least the ones nobody measured are.
    nulls = []
    if prompts:
        for field in ("context_recall", "faithfulness", "answer_relevancy"):
            if all(row[field] is None for row in prompts):
                nulls.append(field)

    print(
        json.dumps(
            {
                "found": True,
                "run": dict(run),
                "prompts": len(prompts),
                "events": events,
                "trainingSteps": steps,
                "samplePrompt": prompts[0] if prompts else None,
                "nulls": nulls,
            }
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
