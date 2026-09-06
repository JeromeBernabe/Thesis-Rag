from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from config import settings

METRICS = ["faithfulness", "answer_relevancy", "context_recall"]
ALPHA = 0.05


def load_results(path=settings.RAGAS_RESULTS_PATH) -> pd.DataFrame:
    df = pd.read_csv(path)
    for metric in METRICS:
        df[metric] = pd.to_numeric(df[metric], errors="coerce")
    return df


def descriptive_stats(df: pd.DataFrame, metrics: list[str] | None = None) -> pd.DataFrame:
    metrics = metrics or METRICS
    rows = []
    for system_id in sorted(df["system_id"].unique()):
        sub = df[df["system_id"] == system_id]
        for metric in metrics:
            values = sub[metric].dropna()
            rows.append(
                {
                    "system_id": system_id,
                    "metric": metric,
                    "count": int(len(values)),
                    "mean": values.mean(),
                    "std": values.std(ddof=1) if len(values) > 1 else float("nan"),
                    "min": values.min(),
                    "max": values.max(),
                }
            )
    return pd.DataFrame(rows)


def _paired_test(df: pd.DataFrame, metric: str, alpha: float = ALPHA) -> dict:
    """Run paired t-test (two-tailed + one-tailed) and Wilcoxon signed-rank test."""
    pivot = df.pivot(index="prompt_id", columns="system_id", values=metric).dropna()
    if "A" not in pivot.columns or "B" not in pivot.columns:
        raise ValueError("Results must contain both system A and system B rows.")
    a = pivot["A"]
    b = pivot["B"]
    diffs = b - a
    n = len(a)
    mean_a = float(a.mean())
    mean_b = float(b.mean())
    mean_diff = float(diffs.mean())

    # -- Paired t-test (two-tailed) --
    t_stat, p_two = stats.ttest_rel(a, b)
    if t_stat != t_stat:
        t_stat, p_two = float("nan"), float("nan")

    # -- One-tailed p-value (B > A) --
    if t_stat == t_stat and n >= 2:
        p_one = float(p_two / 2) if t_stat > 0 else float(1 - p_two / 2)
    else:
        p_one = float("nan")

    # -- Wilcoxon signed-rank test (two-tailed) --
    try:
        if (diffs == 0).all():
            w_stat, p_wilcoxon_two = float("nan"), float("nan")
        else:
            w_stat, p_wilcoxon_two = stats.wilcoxon(a, b)
    except ValueError:
        w_stat, p_wilcoxon_two = float("nan"), float("nan")

    # -- Wilcoxon one-tailed (B > A) --
    if w_stat == w_stat and p_wilcoxon_two == p_wilcoxon_two:
        try:
            w_stat_one, p_wilcoxon_one = stats.wilcoxon(a, b, alternative="less")
        except TypeError:
            p_wilcoxon_one = float(p_wilcoxon_two / 2) if mean_diff > 0 else float(1 - p_wilcoxon_two / 2)
    else:
        p_wilcoxon_one = float("nan")

    # -- Effect size: Cohen's d for paired samples --
    std_diff = float(diffs.std(ddof=1)) if n > 1 else float("nan")
    cohen_d = mean_diff / std_diff if std_diff and std_diff > 0 else float("nan")

    # -- Confidence interval (95%) for mean difference --
    if n >= 2 and std_diff > 0:
        se = std_diff / np.sqrt(n)
        t_crit = stats.t.ppf(0.975, df=n - 1)
        ci_low = mean_diff - t_crit * se
        ci_high = mean_diff + t_crit * se
    else:
        ci_low, ci_high = float("nan"), float("nan")

    return {
        "metric": metric,
        "n_pairs": int(n),
        "mean_a": mean_a,
        "mean_b": mean_b,
        "mean_difference": mean_diff,
        "cohens_d": round(cohen_d, 4) if cohen_d == cohen_d else None,
        "ci_95_low": round(ci_low, 4) if ci_low == ci_low else None,
        "ci_95_high": round(ci_high, 4) if ci_high == ci_high else None,
        "t_statistic": round(float(t_stat), 4) if t_stat == t_stat else None,
        "p_two_tailed": round(float(p_two), 6) if p_two == p_two else None,
        "p_one_tailed": round(float(p_one), 6) if p_one == p_one else None,
        "sig_two_tailed": bool(p_two == p_two and p_two < alpha),
        "sig_one_tailed": bool(p_one == p_one and p_one < alpha),
        "wilcoxon_stat": round(float(w_stat), 4) if w_stat == w_stat else None,
        "wilcoxon_p_two": round(float(p_wilcoxon_two), 6) if p_wilcoxon_two == p_wilcoxon_two else None,
        "wilcoxon_p_one": round(float(p_wilcoxon_one), 6) if p_wilcoxon_one == p_wilcoxon_one else None,
        "wilcoxon_sig_one": bool(p_wilcoxon_one == p_wilcoxon_one and p_wilcoxon_one < alpha),
    }


def summarize(df: pd.DataFrame, metrics: list[str] | None = None) -> pd.DataFrame:
    metrics = metrics or METRICS
    rows = []
    for metric in metrics:
        rows.append(_paired_test(df, metric))
    return pd.DataFrame(rows)


def per_prompt_comparison(df: pd.DataFrame, metric: str = "faithfulness") -> pd.DataFrame:
    pivot = df.pivot(index="prompt_id", columns="system_id", values=metric)
    pivot = pivot.rename(columns={"A": f"A_{metric}", "B": f"B_{metric}"})
    pivot[f"B_minus_A"] = pivot[f"B_{metric}"] - pivot[f"A_{metric}"]
    return pivot.reset_index()


def report(df: pd.DataFrame, out_path=None) -> str:
    desc = descriptive_stats(df)
    ttable = summarize(df)
    lines = []
    lines.append("=" * 90)
    lines.append("DESCRIPTIVE STATISTICS PER SYSTEM")
    lines.append("=" * 90)
    lines.append(desc.to_string(index=False))
    lines.append("")
    lines.append("=" * 90)
    lines.append("STATISTICAL TESTS (System B - System A), alpha = 0.05")
    lines.append("=" * 90)
    lines.append(
        ttable[
            [
                "metric", "n_pairs", "mean_a", "mean_b", "mean_difference",
                "cohens_d", "ci_95_low", "ci_95_high",
                "t_statistic", "p_two_tailed", "p_one_tailed",
                "sig_two_tailed", "sig_one_tailed",
                "wilcoxon_stat", "wilcoxon_p_two", "wilcoxon_p_one", "wilcoxon_sig_one",
            ]
        ].to_string(index=False)
    )
    lines.append("")
    lines.append("Note: p_one_tailed tests H1: B > A (directional hypothesis).")
    lines.append("      wilcoxon_* are non-parametric Wilcoxon signed-rank tests.")
    lines.append("      CI 95% is for the mean difference (B - A).")
    text = "\n".join(lines)
    print(text)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    return text