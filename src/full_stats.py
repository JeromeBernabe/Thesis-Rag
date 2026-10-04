"""Recompute every published statistic from the per-prompt result CSVs.

`results/full_stats.json` and the numbers quoted in `results/analysis_report.md`
were assembled by hand and then left behind while the CSVs moved on. Concretely:
the faithfulness block for hotpot described 49 prompts while the CSV holds 50,
and the token/latency block matched no column of any result file. Nothing
recorded which run a number came from, so a stale figure was indistinguishable
from a fresh one.

Everything here is therefore derived, never entered, and each dataset records
the file it came from plus that file's SHA-256. If the CSV changes, the JSON
changes with it and the provenance line stops matching.

Column mapping for the non-metric fields, which is what the old hand-assembled
file did not state:

    ta/tb      mean `completion_tokens`      - tokens from the answering model
    jta/jtb    mean `judge_completion_tokens` - tokens from the judge model
    ret_a/b    mean `retrieval_time_s`
    gt_a/b     mean `generation_time_s`
    jd_a/b     mean `judge_time_s`
    eff_a/b    mean faithfulness per 1k generation tokens (0 when undefined)

`ga`/`gb` (a "groundedness" figure present in the old file) are deliberately not
reproduced: no result CSV carries that column, so the number had no source and
cannot be regenerated or defended. It is dropped rather than carried forward.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings
from src.stats_analysis import METRICS, _paired_test

# Metric keys in the published file, so existing readers keep working. Named
# explicitly rather than addressed by position: the original hand-assembled file
# gave faithfulness no two-tailed p-value, so the tuples were ragged and
# positional lookup read off the end of the shortest one.
METRIC_KEYS = {
    "faithfulness": {
        "a": "fa", "b": "fb", "diff": "f_diff", "pct": "f_pct",
        "t": "f_t", "p_one": "f_p_one", "p_two": "f_p_two", "d": "f_d", "w_p": "f_w_p",
    },
    "answer_relevancy": {
        "a": "ara", "b": "arb", "diff": "ar_diff", "pct": "ar_pct",
        "t": "ar_t", "p_one": "ar_p_one", "p_two": "ar_p_two", "d": "ar_d", "w_p": "ar_w_p",
    },
    "context_recall": {
        "a": "cra", "b": "crb", "diff": "cr_diff", "pct": "cr_pct",
        "t": "cr_t", "p_one": "cr_p_one", "p_two": "cr_p_two", "d": "cr_d", "w_p": "cr_w_p",
    },
}

# k-selection lives on system B (the DQN picks k); A is the fixed baseline.
NUMERIC_COLUMNS = [
    "retrieved_k", "prompt_tokens", "completion_tokens", "total_tokens",
    "judge_prompt_tokens", "judge_completion_tokens",
    "retrieval_time_s", "generation_time_s", "judge_time_s", "total_time_s",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def load_dataset(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    for col in NUMERIC_COLUMNS + METRICS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _pct(b: float, a: float) -> float:
    return float((b - a) / a * 100) if a else float("nan")


def _mean(df: pd.DataFrame, system: str, col: str) -> float:
    sub = df[df["system_id"] == system]
    if col not in sub.columns or sub.empty:
        return float("nan")
    value = sub[col].mean()
    return float(value) if value == value else float("nan")


def _clean(value):
    """JSON has no NaN; emit null so a reader cannot mistake it for a number."""
    if value is None:
        return None
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if value == value else None
    return value


def judge_columns_are_duplicates(df: pd.DataFrame) -> bool:
    """Whether `completion_tokens`/`prompt_tokens` are really judge counts.

    The runners used to log the judge's token counts into the generator's
    columns, so in the historical files `completion_tokens` is not the
    answering model's output - it is the judge's, duplicated. That is provable
    rather than suspected: `judge_completion_tokens == completion_tokens` in
    every row.

    It matters because these columns are not merely mislabelled, they are the
    *only* token figures in the file. Once they are known to be judge counts,
    neither the judge's cost nor the generator's can be recovered, and anything
    derived from them - including tokens-per-unit-faithfulness - has to be
    withheld rather than reported under a label that is merely wrong.
    """
    for jc, gc in (
        ("judge_completion_tokens", "completion_tokens"),
        ("judge_prompt_tokens", "prompt_tokens"),
    ):
        if jc in df.columns and gc in df.columns:
            both = df[[jc, gc]].dropna()
            if not both.empty and (both[jc] == both[gc]).all():
                return True
    return False


def validate(df: pd.DataFrame) -> list[str]:
    """Flag columns that cannot be taken at face value.

    These are checks on the instrumentation, not on the results, and every one
    of them is currently true. Publishing the affected figures without saying so
    is how the previous file ended up quoting a judge cost of 5,258 tokens that
    no column can produce.
    """
    warnings: list[str] = []
    dupes = df.duplicated(subset=["prompt_id", "system_id"]).sum()
    if dupes:
        warnings.append(f"{dupes} duplicated (prompt_id, system_id) rows")

    for jc, gc in (
        ("judge_completion_tokens", "completion_tokens"),
        ("judge_prompt_tokens", "prompt_tokens"),
    ):
        if jc in df.columns and gc in df.columns:
            both = df[[jc, gc]].dropna()
            if not both.empty and (both[jc] == both[gc]).all():
                warnings.append(
                    f"{jc} is identical to {gc} in every row, so judge token usage was never "
                    f"recorded separately; the judge cost cannot be reported from this file"
                )

    if judge_columns_are_duplicates(df):
        warnings.append(
            "prompt_tokens and completion_tokens hold the judge's counts (see above), so "
            "neither the judge's nor the generator's token usage is recoverable from this "
            "file; ta, tb and the tokens-per-faithfulness figures are withheld rather than "
            "reported under a label that is merely wrong"
        )

    if {"total_tokens", "prompt_tokens", "completion_tokens"} <= set(df.columns):
        expected = df["prompt_tokens"] + df["completion_tokens"]
        actual = df["total_tokens"]
        both = pd.DataFrame({"e": expected, "a": actual}).dropna()
        if not both.empty and not (both["e"] == both["a"]).all():
            warnings.append(
                "total_tokens is not prompt_tokens + completion_tokens, so it is measuring "
                "something other than the request total; do not sum it with the other columns"
            )

    if "retrieved_k" in df.columns and df["retrieved_k"].isna().any():
        warnings.append(f"{int(df['retrieved_k'].isna().sum())} rows have no retrieved_k")
    return warnings


def build_dataset(df: pd.DataFrame, source: Path) -> dict:
    out: dict = {}
    out["n_prompts"] = int(df["prompt_id"].nunique())
    out["n_rows"] = int(len(df))

    ks = df[df["system_id"] == "B"]["retrieved_k"].dropna()
    out["k_dist"] = {str(int(k)): int(c) for k, c in ks.value_counts().sort_index().items()}

    # Completeness, before any test drops a pair.
    completeness = {}
    for metric in METRICS:
        nulls = df[df[metric].isna()]
        completeness[metric] = {
            "null_cells": int(len(nulls)),
            "null_system_ids": sorted(nulls["system_id"].unique().tolist()),
            "prompt_ids": sorted(nulls["prompt_id"].unique().tolist()),
        }
    out["data_completeness"] = completeness

    for metric in METRICS:
        row = _paired_test(df, metric)
        keys = METRIC_KEYS[metric]
        out[keys["a"]] = row["mean_a"]
        out[keys["b"]] = row["mean_b"]
        out[keys["diff"]] = row["mean_difference"]
        out[keys["pct"]] = _pct(row["mean_b"], row["mean_a"])
        out[keys["t"]] = row["t_statistic"]
        out[keys["p_one"]] = row["p_one_tailed"]
        out[keys["p_two"]] = row["p_two_tailed"]
        out[keys["d"]] = row["cohens_d"]
        out[keys["w_p"]] = row["wilcoxon_p_one"]
        out[f"{metric}_n_pairs"] = row["n_pairs"]
        out[f"{metric}_n_dropped"] = row["n_dropped"]
        out[f"{metric}_dropped_prompt_ids"] = row["dropped_prompt_ids"]

    out["data_warnings"] = validate(df)

    # Tokens and latency.
    #
    # `completion_tokens` is only the generator's output when the file does not
    # predating the logging fix. Where the judge columns duplicate it, that column
    # holds judge tokens, so the generator's output is unknown and *no* token
    # figure can be published - reporting it under the wrong label is not a
    # smaller mistake than reporting none.
    tokens_are_generator = not judge_columns_are_duplicates(df)
    for system, suffix in (("A", "a"), ("B", "b")):
        tokens = _mean(df, system, "completion_tokens") if tokens_are_generator else None
        faith = out[METRIC_KEYS["faithfulness"][suffix]]
        out[f"t{suffix}"] = tokens
        out[f"ret_{suffix}"] = _mean(df, system, "retrieval_time_s")
        out[f"gt_{suffix}"] = _mean(df, system, "generation_time_s")
        out[f"jd_{suffix}"] = _mean(df, system, "judge_time_s")
        out[f"tt_{suffix}"] = _mean(df, system, "total_time_s")
        out[f"eff_{suffix}"] = (
            (faith / (tokens / 1000))
            if tokens and tokens > 0 and faith == faith
            else None
        )

    # Judge tokens are deliberately absent: `validate` reports the judge token
    # columns as copies of the generation columns, so a number here would be the
    # generator's cost wearing the judge's label. Judge wall-clock below is real.
    out["t_pct"] = _pct(out["tb"], out["ta"])

    out["provenance"] = {
        "source_csv": source.name,
        "source_sha256": sha256(source),
        "rows": int(len(df)),
    }
    return {k: _clean(v) if not isinstance(v, dict) else v for k, v in out.items()}


def build(results_dir: Path | None = None) -> dict:
    results_dir = Path(results_dir or settings.RESULTS_DIR)
    stats: dict = {}
    for dataset in settings.VALID_DATASETS:
        source = results_dir / f"ragas_results_{dataset}_logged.csv"
        if not source.exists():
            raise FileNotFoundError(
                f"missing {source}. Run run_experiment_logged.py for {dataset} first."
            )
        stats[dataset] = build_dataset(load_dataset(source), source)

    stats["_provenance"] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "src/full_stats.py",
        "note": "Derived from the per-prompt CSVs named above. Do not hand-edit.",
    }
    return stats


def write(results_dir: Path | None = None, out_path: Path | None = None) -> Path:
    import json

    results_dir = Path(results_dir or settings.RESULTS_DIR)
    stats = build(results_dir)
    out_path = Path(out_path or results_dir / "full_stats.json")
    tmp = out_path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, sort_keys=False)
        f.write("\n")
    tmp.replace(out_path)
    return out_path


if __name__ == "__main__":
    import sys

    target = write(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
    print(f"wrote {target}")