"""Assertions over the recorded metric-probe results.

`probe_metrics.py` costs several judge calls per case, so it does not run in the
normal suite. This replays its recorded output through the same `verdict` logic,
which means the recorded scores are still held to the thresholds they were
collected under - if a case is edited to expect the wrong thing, or a score is
hand-typed, this fails.

Run the probes themselves with `python probe_metrics.py`.

Findings these lock in, both against qwen3:8b:

- **Faithfulness is sound.** It scores 0.0 for a claim contradicted by the
  context, 0.0 for wholly fabricated content, and gives partial credit (2/3)
  for a mixed answer. The 1.0 scores seen in the real runs are therefore
  plausible rather than a judge that always agrees.
- **Context recall is lenient.** It scores 1.0 for a reference that is *not* in
  the context at all, provided the context is on the same topic. It separates
  "completely unrelated" (0.0) from "on topic" (1.0) but not "on topic and
  missing the specific claim" - which it calls full recall.

That second point is what licenses the fintech context-recall result. The metric
is biased *toward* scoring high, so the observed 0.032 cannot be explained by
leniency: those references really were not in the retrieved context.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from probe_metrics import CONTEXT_RECALL_CASES, FAITHFULNESS_CASES, verdict

RECORDED = Path("results/metric_probe_results.json")


@pytest.fixture(scope="module")
def recorded() -> dict:
    if not RECORDED.exists():
        pytest.fail(f"{RECORDED} is missing; run `python probe_metrics.py`")
    return json.loads(RECORDED.read_text(encoding="utf-8"))


def test_every_probe_case_passed_when_recorded(recorded):
    """The known-lenient context-recall case is excluded; see the module docstring.

    Everything else must have met its threshold at collection time.
    """
    results = dict(recorded["results"])
    results["context_recall"] = [
        c for c in results["context_recall"]
        if c["name"] != "reference_absent_but_topically_close"
    ]
    assert verdict(results) == []


def test_faithfulness_rejects_unsupported_claims(recorded):
    """The 1.0s in the real runs are only credible if 0.0s are reachable."""
    cases = {c["name"]: c for c in recorded["results"]["faithfulness"]}
    assert cases["verbatim_support"]["score"] == pytest.approx(1.0)
    assert cases["contradicted_by_context"]["score"] == pytest.approx(0.0)
    assert cases["wholly_fabricated"]["score"] == pytest.approx(0.0)
    assert cases["wholly_unrelated_answer"]["score"] == pytest.approx(0.0)


def test_faithfulness_gives_partial_credit(recorded):
    """A mixed answer must not collapse to 0 or 1.

    If it did, the metric would be reporting whether the judge felt the answer
    was overall good rather than what fraction of it the context supports.
    """
    case = {c["name"]: c for c in recorded["results"]["faithfulness"]}["partially_fabricated"]
    assert 0.4 < case["score"] < 0.9, f"expected partial credit, got {case['score']}"


def test_context_recall_separates_unrelated_from_present(recorded):
    cases = {c["name"]: c for c in recorded["results"]["context_recall"]}
    assert cases["reference_present_verbatim"]["score"] >= 0.8
    assert cases["reference_present_paraphrased"]["score"] >= 0.6
    assert cases["reference_absent"]["score"] <= 0.4


def test_context_recall_leniency_is_recorded_not_silently_fixed(recorded):
    """Pin the limitation instead of leaving it as folklore.

    If a future judge version stops doing this, the recorded number changes and
    this fails - which is the signal to revisit the fintech interpretation.
    """
    case = {c["name"]: c for c in recorded["results"]["context_recall"]}[
        "reference_absent_but_topically_close"
    ]
    assert case["score"] >= 0.8, (
        "context recall no longer scores an absent-but-on-topic reference as full recall. "
        "That is an improvement, not a regression - update the fintech interpretation in "
        "results/analysis_report.md and this assertion."
    )


@pytest.mark.parametrize(
    "cases", [FAITHFULNESS_CASES, CONTEXT_RECALL_CASES], ids=["faithfulness", "context_recall"]
)
def test_recorded_cases_still_match_the_live_definitions(cases):
    """The record is worthless if the cases drifted away from what produced it."""
    recorded = json.loads(RECORDED.read_text(encoding="utf-8"))["results"]
    metric = "faithfulness" if cases is FAITHFULNESS_CASES else "context_recall"
    live = {c["name"]: c["expect"] for c in cases}
    stored = {c["name"]: c["expect"] for c in recorded[metric]}
    assert live == stored, f"{metric} cases changed since the results were recorded"