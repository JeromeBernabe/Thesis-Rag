"""Check that the judge metrics actually respond to the thing they measure.

Two of the thesis results depend on metrics behaving sensibly, and neither had
been checked against a case where the right answer is known:

- Faithfulness scored 1.0 on 4 of 5 observed prompts. That is either a very good
  retriever or a judge that says yes.
- Fintech context recall was ~0.0 for both systems across 50 prompts with no
  missing values. A metric that returns almost nothing regardless of the system
  under test is more likely to be mis-specified than to be reporting a -70.9%
  effect.

So this runs hand-built cases whose correct score is unambiguous, through the
real `RagasScorer` and the real judge model. Each case states what it expects and
why; the script exits non-zero if a metric fails to discriminate.

    python probe_metrics.py
    python probe_metrics.py --metric faithfulness

Each case costs judge calls (~60s), so it is not part of the normal test suite.
The assertions live in `bench_bridge/tests/test_metric_probes.py` as skipped-by-
default tests over the recorded results, so a regression in the recorded output
is still caught.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.ragas_eval import RagasScorer  # noqa: E402

RECORDED_PATH = Path("results/metric_probe_results.json")

# Each case: metric, inputs, expected direction, and the bound it must clear.
# "high" means the answer/reference is genuinely supported/present; "low" means
# it is not. A metric that returns the same score for both is not measuring the
# thing the report relies on it to measure.
FAITHFULNESS_CASES = [
    {
        "name": "verbatim_support",
        "expect": "high",
        "bound": 0.8,
        "question": "What is the capital city of Australia?",
        "contexts": ["The capital city of Australia is Canberra."],
        "answer": "The capital city of Australia is Canberra.",
    },
    {
        "name": "contradicted_by_context",
        "expect": "low",
        "bound": 0.4,
        "question": "What is the capital city of Australia?",
        "contexts": ["The capital city of Australia is Canberra."],
        "answer": "The capital city of Australia is Sydney.",
    },
    {
        # Two of the three statements are supported and one is invented, so the
        # correct faithfulness is 2/3. This checks that partial credit is given
        # rather than the metric collapsing to 0 or 1 on a mixed answer - which
        # is what a broken judge would do.
        "name": "partially_fabricated",
        "expect": "mid",
        "low_bound": 0.4,
        "high_bound": 0.9,
        "question": "How many terminals does Port Meridian International Airport have?",
        "contexts": [
            "Port Meridian International Airport opened in 1974 and is the third busiest in the region."
        ],
        "answer": (
            "Port Meridian International Airport has seven terminals. "
            "It was opened in 1974 and is the third busiest airport in the region."
        ),
    },
    {
        # Every statement invented. Nothing here is supported, so this must be 0.
        "name": "wholly_fabricated",
        "expect": "low",
        "bound": 0.2,
        "question": "How many terminals does Port Meridian International Airport have?",
        "contexts": [
            "Port Meridian International Airport opened in 1974 and is the third busiest in the region."
        ],
        "answer": (
            "Port Meridian International Airport has seven terminals. "
            "It was designed by the architect Lina Bo Bardi. "
            "Its runway is 4,200 metres long."
        ),
    },
    {
        "name": "wholly_unrelated_answer",
        "expect": "low",
        "bound": 0.4,
        "question": "What is the boiling point of water at sea level?",
        "contexts": ["The French Revolution began in 1789."],
        "answer": "The boiling point of water at sea level is 100 degrees Celsius.",
    },
]

CONTEXT_RECALL_CASES = [
    {
        "name": "reference_present_verbatim",
        "expect": "high",
        "bound": 0.8,
        "question": "How do I reset my device to factory settings?",
        "contexts": [
            "To reset your device to factory settings, hold the power button for 10 seconds "
            "until the screen flashes, then confirm the reset."
        ],
        "reference": "Hold the power button for 10 seconds until the screen flashes, then confirm.",
    },
    {
        "name": "reference_absent",
        "expect": "low",
        "bound": 0.4,
        "question": "How do I reset my device to factory settings?",
        "contexts": [
            "The device ships with a 4000 mAh battery and charges over USB-C in about 90 minutes."
        ],
        "reference": "Hold the power button for 10 seconds until the screen flashes, then confirm.",
    },
    {
        "name": "reference_present_paraphrased",
        "expect": "high",
        "bound": 0.6,
        "question": "What are the account fees for the Basic plan?",
        "contexts": [
            "The Basic plan carries no monthly account fee. There is no charge for holding the "
            "account and no minimum balance requirement."
        ],
        "reference": "There is no monthly fee on the Basic plan.",
    },
    {
        "name": "reference_absent_but_topically_close",
        "expect": "low",
        "bound": 0.4,
        "question": "What are the account fees for the Basic plan?",
        "contexts": [
            "The Basic plan includes unlimited transactions and 24/7 support at no extra cost."
        ],
        "reference": "The Basic plan has no monthly account fee and no minimum balance.",
    },
]


def _score_faithfulness(scorer: RagasScorer, case: dict) -> float | None:
    return scorer.score_single(
        case["question"], case["answer"], case["contexts"], metric_names=["faithfulness"]
    ).get("faithfulness")


def _score_context_recall(scorer: RagasScorer, case: dict) -> float | None:
    return scorer.score_single(
        case["question"],
        "",
        case["contexts"],
        reference=case["reference"],
        metric_names=["context_recall"],
    ).get("context_recall")


def _record(case: dict, score: float | None, t0: float) -> dict:
    """A scored case. Bounds vary by expectation, so carry whichever apply."""
    row = {
        "name": case["name"],
        "expect": case["expect"],
        "score": score,
        "seconds": round(time.perf_counter() - t0, 1),
    }
    for key in ("bound", "low_bound", "high_bound"):
        if key in case:
            row[key] = case[key]
    return row


def run(metrics: list[str], out_path: Path | None = None) -> dict:
    scorer = RagasScorer()
    results: dict = {}

    if "faithfulness" in metrics:
        results["faithfulness"] = []
        for case in FAITHFULNESS_CASES:
            t0 = time.perf_counter()
            score = _score_faithfulness(scorer, case)
            results["faithfulness"].append(_record(case, score, t0))
            print(f"  faithfulness/{case['name']:32} = {score}  (expect {case['expect']})")

    if "context_recall" in metrics:
        results["context_recall"] = []
        for case in CONTEXT_RECALL_CASES:
            t0 = time.perf_counter()
            score = _score_context_recall(scorer, case)
            results["context_recall"].append(_record(case, score, t0))
            print(f"  context_recall/{case['name']:32} = {score}  (expect {case['expect']})")

    out_path = Path(out_path or RECORDED_PATH)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"judge_model": "qwen3:8b", "results": results}
    if out_path.exists():
        try:
            payload["previous_run"] = json.loads(out_path.read_text(encoding="utf-8")).get("results")
        except (json.JSONDecodeError, OSError):
            pass
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {out_path}")
    return payload


def verdict(results: dict) -> list[str]:
    """Per-case pass/fail, plus the cross-case discrimination check.

    `expect` is one of:
      high - score must be >= bound
      low  - score must be <= bound
      mid  - score must be between low_bound and high_bound, i.e. the metric
             gives partial credit for a partly-supported answer
    """
    failures: list[str] = []
    for metric, cases in results.items():
        scored = [c for c in cases if c["score"] is not None]
        if not scored:
            failures.append(f"{metric}: every case returned None")
            continue
        for case in cases:
            score = case["score"]
            if score is None:
                failures.append(f"{metric}/{case['name']}: no score")
                continue
            expect = case["expect"]
            if expect == "high":
                ok = score >= case["bound"]
                detail = f"at least {case['bound']}"
            elif expect == "low":
                ok = score <= case["bound"]
                detail = f"at most {case['bound']}"
            else:
                ok = case["low_bound"] <= score <= case["high_bound"]
                detail = f"between {case['low_bound']} and {case['high_bound']}"
            if not ok:
                failures.append(
                    f"{metric}/{case['name']}: scored {score:.3f}, expected {detail}"
                )
        high = [c["score"] for c in scored if c["expect"] == "high"]
        low = [c["score"] for c in scored if c["expect"] == "low"]
        if high and low and min(high) <= max(low):
            failures.append(
                f"{metric}: does not discriminate - worst 'high' case ({min(high):.3f}) is not "
                f"above best 'low' case ({max(low):.3f})"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metric", action="append", choices=["faithfulness", "context_recall"])
    args = parser.parse_args()
    metrics = args.metric or ["faithfulness", "context_recall"]

    print(f"probing {', '.join(metrics)} against qwen3:8b (this takes a few minutes)\n")
    payload = run(metrics)
    failures = verdict(payload["results"])

    print()
    if failures:
        print("PROBE FAILURES:")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("all probes passed: the metrics move in the direction they are supposed to")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())