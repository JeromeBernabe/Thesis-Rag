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
    pivot = df.pivot(index="prompt_id", columns="system_id", values=metric)
    if "A" not in pivot.columns or "B" not in pivot.columns:
        raise ValueError("Results must contain both system A and system B rows.")
    # `.dropna()` is what makes the pairing correct, but it is also what makes
    # rows disappear without a trace: a NULL from one system silently shrinks
    # `n`, and the report then quotes an `n` the reader cannot reconcile with
    # the prompt count. Which prompts were dropped, and which system was
    # missing, is recorded so it can be stated in the output instead.
    unpaired = pivot[pivot.isna().any(axis=1)]
    paired = pivot.dropna()
    a = paired["A"]
    b = paired["B"]
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
    #
    # The direction comes from `mean_diff`, never from the sign of `t_stat`.
    # `stats.ttest_rel(a, b)` reports `t` for the contrast *a minus b*, so a
    # positive `t` means A beat B - i.e. B did worse - and halving the p-value on
    # `t > 0` returns the probability of B being worse while labelling it "B > A".
    # The two are opposites, so the bug is invisible on any dataset where the
    # result happens not to be near significance and catastrophic on one where it
    # is: it reports a large p-value as evidence of improvement.
    #
    # `bench_bridge.stats._paired_tests` keys off `mean_diff` for the same reason,
    # and that is the implementation that produced the committed report.
    if t_stat == t_stat and n >= 2:
        p_one = float(p_two / 2) if mean_diff > 0 else float(1 - p_two / 2)
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
    # `alternative="less"` is scipy asking whether the *first* sample tends to be
    # smaller, so with (a, b) ordered as passed that is the B > A tail. Unlike the
    # t-test above, the ordering argument here is already the one that encodes the
    # direction, which is why no sign correction is needed.
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
        "n_prompts": int(pivot.shape[0]),
        "n_dropped": int(unpaired.shape[0]),
        "dropped_prompt_ids": sorted(unpaired.index.tolist()),
        "dropped_missing": {
            str(idx): [c for c in ("A", "B") if pd.isna(row[c])]
            for idx, row in unpaired.iterrows()
        },
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

    # The paired `n` is per metric and is smaller than the prompt count wherever
    # a judge returned NULL, so state the gap rather than leaving the reader to
    # reconcile `n_pairs` against the 50 prompts in the CSV.
    dropped = ttable[ttable["n_dropped"] > 0]
    lines.append("")
    if dropped.empty:
        lines.append("Data completeness: every prompt scored under both systems for all metrics.")
    else:
        lines.append("DATA COMPLETENESS - prompts excluded from a paired test because a judge")
        lines.append("returned no score. `n_pairs` below is smaller than the prompt count for these:")
        for _, row in dropped.iterrows():
            missing = row["dropped_missing"]
            detail = "; ".join(
                f"{pid} (missing {', '.join(systems)})" for pid, systems in missing.items()
            )
            lines.append(
                f"  - {row['metric']}: {row['n_dropped']} of {row['n_prompts']} prompts dropped"
                f" -> n_pairs={row['n_pairs']} | {detail}"
            )
        lines.append("These are excluded pairwise, not imputed. Treat the affected")
        lines.append("metric's n_pairs as its sample size.")
    text = "\n".join(lines)
    print(text)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    return text