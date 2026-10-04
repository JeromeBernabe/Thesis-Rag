"""Check concurrent scoring against sequential scoring on the real judge.

The unit tests prove the plumbing with a stub. This proves the end-to-end
property on the actual judge model, with three runs:

    seq_run1     workers=1
    seq_run2     workers=1   <- baseline, to measure the judge's own repeatability
    concurrent   workers=N

Comparing concurrent against a single sequential run would conflate two things:
a concurrency defect and the judge simply not being deterministic. Running
sequential twice separates them - if the two sequential runs disagree, then
disagreement in the concurrent run is the judge's noise, not the thread pool.

Each row is compared on its three metrics *and* its judge token counts, since
the counters used to be shared instance state.

    python verify_concurrency.py [--workers 4]

Writes `results/concurrency_verification.json`. Exits non-zero if concurrent
scoring differs from sequential, or if the judge is too noisy for the comparison
to mean anything.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.ragas_eval import RagasScorer  # noqa: E402

OUT_PATH = Path("results/concurrency_verification.json")

# Short, self-evident cases. Long retrieved contexts would dominate the runtime
# without exercising anything the short ones do not.
CASES = [
    {
        "question": "What is the capital of France?",
        "answer": "The capital of France is Paris.",
        "contexts": ["Paris is the capital and most populous city of France."],
        "reference": "Paris is the capital of France.",
    },
    {
        "question": "How many legs does a spider have?",
        "answer": "A spider has eight legs.",
        "contexts": ["Spiders are arachnids and have eight legs."],
        "reference": "Spiders have eight legs.",
    },
    {
        "question": "When was the Eiffel Tower finished?",
        "answer": "The Eiffel Tower was finished in 1889.",
        "contexts": ["The Eiffel Tower was completed in 1889 for the World's Fair."],
        "reference": "The Eiffel Tower was finished in 1889.",
    },
]

METRICS = ("faithfulness", "answer_relevancy", "context_recall")
COUNTERS = ("judge_prompt_tokens", "judge_completion_tokens")


def _run(workers: int) -> dict:
    scorer = RagasScorer(max_workers=workers)
    try:
        started = time.perf_counter()
        rows = scorer.score(
            [c["question"] for c in CASES],
            [c["answer"] for c in CASES],
            [c["contexts"] for c in CASES],
            [c["reference"] for c in CASES],
        )
        elapsed = time.perf_counter() - started
    finally:
        scorer.close()
    return {
        "workers": workers,
        "seconds": round(elapsed, 1),
        "rows": [{k: row[k] for k in METRICS + COUNTERS} for row in rows],
    }


def _compare(left: dict, right: dict) -> list[str]:
    """Field-level differences between two runs."""
    diffs: list[str] = []
    for i, (a, b) in enumerate(zip(left["rows"], right["rows"])):
        for key in METRICS + COUNTERS:
            if a[key] != b[key]:
                diffs.append(f"row {i} {key}: {a[key]!r} vs {b[key]!r}")
    return diffs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    print(f"judge: qwen3:8b, {len(CASES)} cases, three runs (this takes a few minutes)\n")
    runs = {}
    for label, workers in (
        ("seq_run1", 1), ("seq_run2", 1), ("concurrent", args.workers),
    ):
        print(f"  {label} (workers={workers}) ...", end="", flush=True)
        runs[label] = _run(workers)
        print(f" {runs[label]['seconds']}s")

    seq_noise = _compare(runs["seq_run1"], runs["seq_run2"])
    concurrent_diffs = _compare(runs["seq_run1"], runs["concurrent"])
    speedup = runs["seq_run1"]["seconds"] / max(runs["concurrent"]["seconds"], 1e-9)

    payload = {
        "judge_model": "qwen3:8b",
        "cases": len(CASES),
        "runs": runs,
        "judge_repeatability_diffs": seq_noise,
        "concurrent_vs_sequential_diffs": concurrent_diffs,
        "speedup": round(speedup, 2),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {OUT_PATH}\n")

    print(f"judge repeatability (seq vs seq): {len(seq_noise)} difference(s)")
    for line in seq_noise:
        print(f"  - {line}")

    print(f"concurrent vs sequential:        {len(concurrent_diffs)} difference(s)")
    for line in concurrent_diffs:
        print(f"  - {line}")

    print(f"speedup: {runs['seq_run1']['seconds']}s -> "
          f"{runs['concurrent']['seconds']}s ({speedup}x at {args.workers} workers)")

    failures: list[str] = []
    if concurrent_diffs:
        if seq_noise:
            failures.append(
                f"concurrent scoring differs from sequential in {len(concurrent_diffs)} field(s), "
                f"and the judge is itself unstable ({len(seq_noise)} difference(s) between two "
                f"sequential runs), so the cause cannot be attributed"
            )
        else:
            failures.append(
                f"concurrent scoring differs from sequential in {len(concurrent_diffs)} field(s) "
                f"while the judge is stable: this is a concurrency defect"
            )
    if not seq_noise:
        print("\njudge is deterministic at temperature 0, so the comparison is exact.")

    print()
    if failures:
        print("FAILURES:")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("PASS: concurrent scoring is indistinguishable from sequential on the real judge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())