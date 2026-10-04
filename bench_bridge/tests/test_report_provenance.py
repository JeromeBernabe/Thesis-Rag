"""`results/full_stats.json` must be reproducible from the CSVs it cites.

The file it guards was assembled by hand, which is how it ended up describing
49 hotpot prompts while the CSV held 50, and quoting a judge cost of 5,258
tokens that no column of any result file can produce. Nothing recorded which run
a number came from, so a stale figure looked exactly like a fresh one.

These tests recompute from `results/ragas_results_<dataset>_logged.csv` and
require the stored JSON to agree, and require the stored source hash to still
match the CSV on disk. Regenerate with `python -c "from src.full_stats import
write; write()"`, or the suite fails - which is the intended behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.full_stats import build, load_dataset, sha256

DATASETS = ["fintech", "hotpot", "math", "ragtruth"]
STATS_PATH = Path("results/full_stats.json")


@pytest.fixture(scope="module")
def stored() -> dict:
    if not STATS_PATH.exists():
        pytest.fail(f"{STATS_PATH} is missing; regenerate it")
    return json.loads(STATS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fresh() -> dict:
    return build()


@pytest.mark.parametrize("dataset", DATASETS)
def test_stored_stats_match_a_fresh_build(dataset, stored, fresh):
    """Every published number must be one the CSVs still produce."""
    assert dataset in stored, f"{dataset} missing from full_stats.json"
    for key, expected in fresh[dataset].items():
        if key == "provenance":
            continue
        assert stored[dataset].get(key) == expected, (
            f"{dataset}.{key} is {stored[dataset].get(key)!r} but the CSV gives {expected!r}. "
            f"The report has drifted from the data; regenerate full_stats.json."
        )


@pytest.mark.parametrize("dataset", DATASETS)
def test_recorded_source_hash_still_matches_the_csv(dataset, stored):
    """The provenance line is only useful if it is checked against the file."""
    source = Path("results") / f"ragas_results_{dataset}_logged.csv"
    assert source.exists(), f"{source} is gone; the stats can no longer be verified"
    recorded = stored[dataset]["provenance"]
    assert recorded["source_csv"] == source.name
    assert recorded["source_sha256"] == sha256(source), (
        f"{source} has changed since full_stats.json was generated; regenerate it"
    )


@pytest.mark.parametrize("dataset", DATASETS)
def test_no_hand_entered_groundedness(dataset, stored):
    """`ga`/`gb` were in the old file with no column anywhere to derive them.

    They were carried into the report as if measured. If they reappear, whatever
    produced them needs to be committed alongside.
    """
    for key in ("ga", "gb", "g_pct"):
        assert key not in stored[dataset], (
            f"{dataset}.{key} reappeared with no source column; do not report it"
        )


@pytest.mark.parametrize("dataset", DATASETS)
def test_prompt_count_and_per_metric_n_are_reported_separately(dataset, stored, fresh):
    """`n` used to be a single ambiguous number per dataset.

    For hotpot it was 49 - the context-recall pair count - quoted next to a
    50-prompt run, which is exactly the kind of thing that reads as a bug in the
    analysis rather than a gap in the instrumentation.
    """
    stats = stored[dataset]
    df = load_dataset(Path("results") / f"ragas_results_{dataset}_logged.csv")
    assert stats["n_prompts"] == int(df["prompt_id"].nunique())

    for metric in ("faithfulness", "answer_relevancy", "context_recall"):
        key = f"{metric}_n_pairs"
        assert key in stats, f"{dataset} does not report {key}"
        assert stats[key] == fresh[dataset][key]
        assert stats[key] <= stats["n_prompts"]


def test_dropped_prompts_are_named(stored, fresh):
    """A judge that returns NULL must cost a prompt visibly, not silently."""
    for dataset in DATASETS:
        for metric in ("faithfulness", "answer_relevancy", "context_recall"):
            dropped = stored[dataset][f"{metric}_n_dropped"]
            ids = stored[dataset][f"{metric}_dropped_prompt_ids"]
            assert dropped == len(ids), f"{dataset}/{metric}: count and ids disagree"
            assert dropped == fresh[dataset][f"{metric}_n_dropped"]

    # The two known gaps, pinned so they cannot quietly change.
    assert stored["hotpot"]["context_recall_n_dropped"] == 1
    assert stored["hotpot"]["context_recall_dropped_prompt_ids"] == ["5ae2057b554299234fd043a5"]
    assert stored["math"]["faithfulness_n_dropped"] == 1
    assert stored["math"]["faithfulness_dropped_prompt_ids"] == ["Math-Test-1016"]


def test_hotpot_faithfulness_uses_all_fifty_prompts(stored):
    """The specific staleness that motivated regenerating the file.

    The report described 49 paired prompts and an 8.31% faithfulness gain from a
    50-prompt run that had since gained a prompt.
    """
    assert stored["hotpot"]["faithfulness_n_pairs"] == 50
    assert stored["hotpot"]["fa"] == pytest.approx(0.5984444444444444)
    assert stored["hotpot"]["fb"] == pytest.approx(0.6509999999999999)
    assert stored["hotpot"]["f_pct"] == pytest.approx(8.782027478648333)
    assert stored["hotpot"]["f_p_one"] == pytest.approx(0.234014)


@pytest.mark.parametrize("dataset", DATASETS)
def test_known_corrupt_token_columns_are_flagged_not_averaged(dataset, stored):
    """Token columns in the committed CSVs hold the judge's numbers.

    The runners wrote `scores["judge_prompt_tokens"]` into `prompt_tokens`, so
    the generator's real counts were discarded and the two columns are equal in
    every row. The code is fixed; these CSVs predate the fix and cannot be
    repaired without re-running, so the file must say so instead of publishing
    the duplicate as a token measurement.
    """
    warnings = stored[dataset]["data_warnings"]
    assert any("judge_completion_tokens is identical" in w for w in warnings), (
        f"{dataset}: expected the duplicated judge token column to be flagged"
    )
    assert any("judge_prompt_tokens is identical" in w for w in warnings)


def test_no_token_figure_is_published_while_the_columns_are_duplicates(stored):
    """Nothing derived from the corrupt columns may reach the JSON.

    Two directions, both of which have already gone wrong here:

    - `jta`/`jtb` must be *absent*; publishing them would reintroduce the exact
      confusion being fixed.
    - `ta`/`tb`/`eff_*`/`t_pct` must be *null* rather than carrying the judge
      counts. Reporting a number under the wrong label is not a smaller mistake
      than reporting none, and the file previously did exactly that - it warned
      about the duplicated columns while still averaging `completion_tokens`
      into "generation tokens".
    """
    for dataset in DATASETS:
        for key in ("jta", "jtb", "ja_pct"):
            assert key not in stored[dataset], (
                f"{dataset}.{key} is published while the judge token columns are copies "
                f"of the generator's"
            )
        for key in ("ta", "tb", "eff_a", "eff_b", "t_pct"):
            assert stored[dataset][key] is None, (
                f"{dataset}.{key} = {stored[dataset][key]!r}, but the token columns hold "
                f"the judge's counts, so this figure cannot be recovered from these CSVs"
            )


def test_json_is_free_of_nan(stored):
    """NaN is not valid JSON; a reader in another language would choke."""
    text = STATS_PATH.read_text(encoding="utf-8")
    assert "NaN" not in text, "full_stats.json contains a bare NaN; nulls are required"
    json.loads(text)  # would raise on invalid JSON


def test_generated_values_really_come_from_the_csvs(stored):
    """Spot-check a mean against a direct recomputation, not against the builder."""
    df = load_dataset(Path("results") / "ragas_results_fintech_logged.csv")
    a = df[(df["system_id"] == "A")]["faithfulness"].dropna()
    assert stored["fintech"]["fa"] == pytest.approx(float(a.mean()))