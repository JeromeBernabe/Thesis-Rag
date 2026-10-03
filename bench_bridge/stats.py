"""Statistics for the results page, produced at the end of every run.

The thesis compares System A (fixed k) against System B (DQN-chosen k) on the
same prompts, so the statistics that matter are **paired** ones: per-prompt
descriptives, paired t-tests, Wilcoxon signed-rank tests, and the distribution of
chosen k. Those are the same measures ``src/stats_analysis.py`` computes for the
committed reports, so the app and the thesis cannot disagree.

Everything returned here is JSON-ready. NaN is preserved through
:func:`json_safe` as ``None`` so the frontend renders "n/a" instead of a broken
chart - a Wilcoxon test on a metric that is entirely missing is ``nan`` by
definition.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable, Sequence

__all__ = ["METRICS", "ALPHA", "build_stats_payload", "json_safe"]

METRICS = ("faithfulness", "answer_relevancy", "context_recall")
ALPHA = 0.05


def json_safe(value: Any) -> Any:
    """Replace non-finite floats with ``None`` recursively."""
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def _clean_pairs(rows: Sequence[dict]) -> dict[str, tuple[list[float], list[float]]]:
    """Pair System A and System B values per prompt, dropping unjudged rows.

    Pairing is by ``prompt_id`` rather than list position because the two
    systems run in separate phases and a prompt can be skipped in one of them.
    A row with a ``None`` metric (the judge produced no verdict) is dropped
    rather than treated as zero.
    """
    a_by_id = {r["prompt_id"]: r for r in rows if r.get("system") == "A"}
    b_by_id = {r["prompt_id"]: r for r in rows if r.get("system") == "B"}
    shared = sorted(set(a_by_id) & set(b_by_id))

    out: dict[str, tuple[list[float], list[float]]] = {}
    for metric in METRICS:
        a_vals: list[float] = []
        b_vals: list[float] = []
        for pid in shared:
            a = a_by_id[pid].get(metric)
            b = b_by_id[pid].get(metric)
            if a is None or b is None:
                continue
            a_vals.append(float(a))
            b_vals.append(float(b))
        out[metric] = (a_vals, b_vals)
    return out


def _describe(values: Iterable[float]) -> dict:
    data = [float(v) for v in values]
    n = len(data)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "min": None, "max": None,
                "median": None, "sem": None}
    mean = sum(data) / n
    if n > 1:
        variance = sum((v - mean) ** 2 for v in data) / (n - 1)
        std = math.sqrt(variance)
    else:
        std = 0.0
    ordered = sorted(data)
    mid = n // 2
    median = ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return {
        "n": n,
        "mean": mean,
        "std": std,
        "min": min(data),
        "max": max(data),
        "median": median,
        "sem": std / math.sqrt(n) if n else None,
    }


def _paired_tests(a_vals: list[float], b_vals: list[float]) -> dict:
    """Paired t-test plus Wilcoxon signed-rank, mirroring src/stats_analysis.py.

    scipy/pandas are imported lazily: the dry-run path and the projection-only
    path must work in an environment where the scientific stack is absent.
    """
    n = len(a_vals)
    if n < 2:
        return {
            "n": n,
            "t_stat": None,
            "p_two_tailed": None,
            "p_one_tailed_better": None,
            "w_stat": None,
            "p_wilcoxon_two_tailed": None,
            "mean_diff": (b_vals[0] - a_vals[0]) if n == 1 else None,
            "note": "need at least 2 paired observations",
        }

    try:
        import numpy as np
        from scipy import stats
    except ImportError:
        return {
            "n": n,
            "t_stat": None,
            "p_two_tailed": None,
            "p_one_tailed_better": None,
            "w_stat": None,
            "p_wilcoxon_two_tailed": None,
            "mean_diff": sum(b - a for a, b in zip(a_vals, b_vals)) / n,
            "note": "scipy unavailable; descriptive statistics only",
        }

    a = np.asarray(a_vals, dtype=float)
    b = np.asarray(b_vals, dtype=float)
    diff = b - a

    t_stat, p_two = stats.ttest_rel(a, b)

    w_stat, p_wilcoxon = float("nan"), float("nan")
    if np.any(diff != 0):
        w_stat, p_wilcoxon = stats.wilcoxon(a, b, zero_method="wilcox")

    # One-tailed alternative: System B (DQN) scores higher than System A.
    mean_diff = float(diff.mean())
    p_one = float(p_two) / 2.0 if mean_diff > 0 else 1.0 - float(p_two) / 2.0

    return {
        "n": n,
        "t_stat": float(t_stat),
        "p_two_tailed": float(p_two),
        "p_one_tailed_better": p_one,
        "w_stat": float(w_stat),
        "p_wilcoxon_two_tailed": float(p_wilcoxon),
        "mean_diff": mean_diff,
        "significant_at_alpha": bool(float(p_two) < ALPHA),
    }


def build_stats_payload(
    prompt_rows: list[dict], training_rows: list[dict] | None = None
) -> dict:
    """Assemble the full statistics payload for one run."""
    training_rows = training_rows or []
    pairs = _clean_pairs(prompt_rows)

    per_system: dict[str, dict] = {}
    for system in ("A", "B"):
        rows = [r for r in prompt_rows if r.get("system") == system]
        metrics = {
            metric: _describe(
                [r[metric] for r in rows if r.get(metric) is not None]
            )
            for metric in METRICS
        }
        times = _describe(
            [
                v
                for r in rows
                for v in (r.get("total_time_s"),)
                if v is not None
            ]
        )
        tokens = _describe(
            [v for r in rows for v in (r.get("total_tokens"),) if v is not None]
        )
        k_counts = Counter(r["retrieved_k"] for r in rows if r.get("retrieved_k"))
        per_system[system] = {
            "prompt_count": len(rows),
            "metrics": metrics,
            "total_time_s": times,
            "total_tokens": tokens,
            "k_distribution": {str(k): v for k, v in sorted(k_counts.items())},
            "mean_k": (
                sum(k * n for k, n in k_counts.items()) / sum(k_counts.values())
                if k_counts
                else None
            ),
        }

    comparison = {metric: _paired_tests(*vals) for metric, vals in pairs.items()}

    # How many prompts both systems actually answered, regardless of whether the
    # judge scored them. This is the denominator the user compares against, so it
    # must come from the rows themselves rather than from any single metric -
    # a metric can be null on one system, and per-metric counts are reported
    # separately in compared_counts.
    ids_a = {r["prompt_id"] for r in prompt_rows if r.get("system") == "A"}
    ids_b = {r["prompt_id"] for r in prompt_rows if r.get("system") == "B"}
    paired_prompt_count = len(ids_a & ids_b)

    training_curve = []
    if training_rows:
        for row in training_rows:
            training_curve.append(
                {
                    "step": row.get("step"),
                    "k": row.get("k"),
                    "reward": row.get("reward"),
                    "loss": row.get("loss"),
                    "epsilon": row.get("epsilon"),
                    "q_values": row.get("q_values"),
                    "faithfulness": row.get("faithfulness"),
                }
            )

    rewards = [r["reward"] for r in training_rows if r.get("reward") is not None]

    return json_safe(
        {
            "schema_version": 1,
            "alpha": ALPHA,
            "metrics": list(METRICS),
            "per_system": per_system,
            "comparison": comparison,
            "training": {
                "steps": len(training_rows),
                "curve": training_curve,
                "reward": _describe(rewards),
                "final_epsilon": (
                    training_rows[-1].get("epsilon") if training_rows else None
                ),
            },
            "paired_prompt_count": paired_prompt_count,
            "compared_counts": {m: comp["n"] for m, comp in comparison.items()},
        }
    )