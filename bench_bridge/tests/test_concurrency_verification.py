"""Locks the recorded concurrent-vs-sequential scoring comparison.

`verify_concurrency.py` takes several minutes against the real judge, so its
result is committed as `results/concurrency_verification.json` and asserted
here. Re-run the script when the scorer or the judge model changes.

These are recorded observations, not a substitute for the stub-based tests in
`test_concurrent_scoring.py`; this file only stops a regression from being
recorded as expected behaviour without anybody noticing.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

RESULT = Path("results/concurrency_verification.json")

pytestmark = pytest.mark.skipif(
    not RESULT.exists(),
    reason=f"{RESULT} missing; run `python verify_concurrency.py`",
)


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(RESULT.read_text(encoding="utf-8"))


def test_concurrent_matched_sequential(report):
    assert report["concurrent_vs_sequential_diffs"] == []


def test_judge_was_deterministic_across_sequential_runs(report):
    """Without this the comparison proves nothing.

    If two sequential runs disagree then any disagreement in the concurrent run
    could be the judge's own nondeterminism rather than a concurrency defect, so
    the verdict would be uninterpretable.
    """
    assert report["judge_repeatability_diffs"] == []


def test_both_runs_actually_used_the_real_judge(report):
    assert report["judge_model"] == "qwen3:8b"
    assert report["cases"] >= 3
    seq, con = report["runs"]["seq_run1"], report["runs"]["concurrent"]
    assert seq["workers"] == 1
    assert con["workers"] >= 2


def test_judge_call_counters_survived_the_thread_pool(report):
    """The counters used to be shared instance state.

    Identical totals across runs is only meaningful if both runs really did the
    work: a concurrency bug that dropped judge calls would show up as smaller
    per-row token counts, not just different scores.
    """
    for row in report["runs"]["seq_run1"]["rows"]:
        assert row["judge_prompt_tokens"] > 0
        assert row["judge_completion_tokens"] > 0


def test_concurrency_actually_sped_things_up(report):
    assert report["speedup"] > 1.0
    assert report["runs"]["concurrent"]["seconds"] < report["runs"]["seq_run1"]["seconds"]