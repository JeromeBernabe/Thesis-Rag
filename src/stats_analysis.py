from __future__ import annotations

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


def paired_ttest(df: pd.DataFrame, metric: str, alpha: float = ALPHA) -> dict:
    pivot = df.pivot(index="prompt_id", columns="system_id", values=metric).dropna()
    if "A" not in pivot.columns or "B" not in pivot.columns:
        raise ValueError("Results must contain both system A and system B rows.")
    a = pivot["A"]
    b = pivot["B"]
    t_stat, p_value = stats.ttest_rel(a, b)
    if t_stat != t_stat:  # NaN -> degenerate (zero variance or n<2)
        t_stat, p_value = float("nan"), float("nan")
    return {
        "metric": metric,
        "n_pairs": int(len(a)),
        "t_statistic": None if (t_stat != t_stat) else float(t_stat),
        "p_value": None if (p_value != p_value) else float(p_value),
        "mean_a": float(a.mean()),
        "mean_b": float(b.mean()),
        "mean_difference": float(b.mean() - a.mean()),
        "significant": bool(p_value == p_value and p_value < alpha),
    }


def summarize(df: pd.DataFrame, metrics: list[str] | None = None) -> pd.DataFrame:
    metrics = metrics or METRICS
    rows = []
    for metric in metrics:
        rows.append(paired_ttest(df, metric))
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
    lines.append("=" * 78)
    lines.append("DESCRIPTIVE STATISTICS PER SYSTEM")
    lines.append("=" * 78)
    lines.append(desc.to_string(index=False))
    lines.append("")
    lines.append("=" * 78)
    lines.append("PAIRED T-TESTS (System B - System A), alpha = 0.05")
    lines.append("=" * 78)
    lines.append(
        ttable[
            ["metric", "n_pairs", "t_statistic", "p_value",
             "mean_a", "mean_b", "mean_difference", "significant"]
        ].to_string(index=False)
    )
    text = "\n".join(lines)
    print(text)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
    return text