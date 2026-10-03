"""Tests for the run statistics payload."""

from __future__ import annotations

import json
import pytest

from bench_bridge.stats import METRICS, build_stats_payload, json_safe


def row(system, prompt_id, faith, relev, recall, k=3, time_s=1.0, tokens=100):
    return {
        "system": system,
        "prompt_id": prompt_id,
        "faithfulness": faith,
        "answer_relevancy": relev,
        "context_recall": recall,
        "retrieved_k": k,
        "total_time_s": time_s,
        "total_tokens": tokens,
        "retrieval_time_s": 0.2,
        "generation_time_s": 0.5,
        "judge_time_s": 0.3,
        "embedding_time_s": 0.1,
    }


def training_row(step, k, reward, loss=0.5, epsilon=1.0, q=None):
    return {
        "step": step,
        "k": k,
        "reward": reward,
        "loss": loss,
        "epsilon": epsilon,
        "q_values": q or [0.1, 0.2, 0.5, 0.3, 0.05],
        "faithfulness": 0.7,
    }


def paired(n=10, delta=0.1):
    """Rows for `n` prompts answered by both systems.

    System A is held exactly constant so the paired difference vector has zero
    variance around ``delta`` - the clean case for the tests. The scipy
    cancellation warning that produces is filtered in pytest.ini.
    """
    rows = []
    for i in range(n):
        rows.append(row("A", f"p{i}", 0.5, 0.5, 0.5, k=3))
        rows.append(row("B", f"p{i}", 0.5 + delta, 0.5 + delta, 0.5, k=4))
    return rows


class TestJsonSafe:
    def test_nan_and_inf_become_none(self):
        out = json_safe({"a": float("nan"), "b": [float("inf"), 1.0]})
        assert out == {"a": None, "b": [None, 1.0]}

    def test_payload_is_strictly_encodable(self):
        payload = build_stats_payload(paired())
        json.dumps(payload, allow_nan=False)


class TestDescribe:
    def test_per_system_descriptives(self):
        stats = build_stats_payload(paired(n=5, delta=0.2))
        a = stats["per_system"]["A"]["metrics"]["faithfulness"]
        assert a["n"] == 5
        assert a["mean"] == pytest.approx(0.5)
        assert a["std"] == pytest.approx(0.0)
        assert a["min"] == a["max"] == pytest.approx(0.5)

    def test_median_of_even_count(self):
        rows = [row("A", f"p{i}", float(i), None, None) for i in range(4)]
        stats = build_stats_payload(rows)
        assert stats["per_system"]["A"]["metrics"]["faithfulness"]["median"] == 1.5

    def test_median_of_odd_count(self):
        rows = [row("A", f"p{i}", float(i), None, None) for i in range(5)]
        stats = build_stats_payload(rows)
        assert stats["per_system"]["A"]["metrics"]["faithfulness"]["median"] == 2.0

    def test_sem_is_std_over_sqrt_n(self):
        stats = build_stats_payload(paired(n=10, delta=0.0))
        a = stats["per_system"]["A"]["metrics"]["faithfulness"]
        assert a["sem"] == pytest.approx(0.0)

    def test_empty_metric_yields_nulls_not_zeros(self):
        """A metric the judge never produced must read as null, not 0."""
        rows = [row("A", f"p{i}", None, None, None) for i in range(3)]
        stats = build_stats_payload(rows)
        m = stats["per_system"]["A"]["metrics"]["faithfulness"]
        assert m["n"] == 0
        assert m["mean"] is None

    def test_single_observation_has_zero_std(self):
        stats = build_stats_payload([row("A", "p0", 0.5, 0.5, 0.5)])
        assert stats["per_system"]["A"]["metrics"]["faithfulness"]["std"] == 0.0


class TestKDistribution:
    def test_counts_and_mean_k(self):
        rows = [row("A", "p0", 0.5, 0.5, 0.5, k=1), row("A", "p1", 0.5, 0.5, 0.5, k=5)]
        stats = build_stats_payload(rows)
        a = stats["per_system"]["A"]
        assert a["k_distribution"] == {"1": 1, "5": 1}
        assert a["mean_k"] == 3.0

    def test_keys_are_strings(self):
        """JSON object keys are always strings; the frontend indexes by k."""
        stats = build_stats_payload([row("A", "p0", 0.5, 0.5, 0.5, k=3)])
        assert stats["per_system"]["A"]["k_distribution"] == {"3": 1}


class TestPairedComparison:
    def test_pairs_are_matched_by_prompt_id(self):
        stats = build_stats_payload(paired(n=6, delta=0.1))
        assert stats["paired_prompt_count"] == 6
        assert stats["comparison"]["faithfulness"]["n"] == 6

    def test_mean_diff_is_b_minus_a(self):
        stats = build_stats_payload(paired(n=6, delta=0.1))
        assert stats["comparison"]["faithfulness"]["mean_diff"] == pytest.approx(0.1)

    def test_system_b_better_gives_a_small_one_tailed_p(self):
        stats = build_stats_payload(paired(n=30, delta=0.2))
        comp = stats["comparison"]["faithfulness"]
        assert comp["p_one_tailed_better"] == pytest.approx(comp["p_two_tailed"] / 2)
        assert comp["p_one_tailed_better"] < 0.05

    def test_system_b_worse_does_not_get_a_small_one_tailed_p(self):
        rows = []
        for i in range(30):
            rows.append(row("A", f"p{i}", 0.7, 0.7, 0.7, k=3))
            rows.append(row("B", f"p{i}", 0.5, 0.5, 0.5, k=4))
        comp = build_stats_payload(rows)["comparison"]["faithfulness"]
        assert comp["mean_diff"] < 0
        assert comp["p_one_tailed_better"] > 0.5

    def test_unpaired_rows_are_ignored(self):
        rows = [row("A", "p0", 0.5, 0.5, 0.5), row("B", "other", 0.9, 0.9, 0.9)]
        assert build_stats_payload(rows)["paired_prompt_count"] == 0

    def test_rows_missing_a_metric_are_dropped_not_zero_filled(self):
        rows = [row("A", f"p{i}", 0.5 if i else None, 0.5, 0.5) for i in range(4)]
        rows += [row("B", f"p{i}", 0.6, 0.6, 0.6) for i in range(4)]
        assert build_stats_payload(rows)["comparison"]["faithfulness"]["n"] == 3

    def test_single_pair_reports_that_it_cannot_test(self):
        stats = build_stats_payload(paired(n=1, delta=0.1))
        comp = stats["comparison"]["faithfulness"]
        assert comp["t_stat"] is None
        assert "at least 2" in comp["note"]

    def test_identical_values_give_null_statistics(self):
        """Zero variance makes t and Wilcoxon undefined; that is null, not 0."""
        comp = build_stats_payload(paired(n=5, delta=0.0))["comparison"][
            "faithfulness"
        ]
        assert comp["t_stat"] is None
        assert comp["w_stat"] is None
        assert comp["mean_diff"] == pytest.approx(0.0)

    def test_all_metrics_are_compared(self):
        stats = build_stats_payload(paired(n=5))
        assert set(stats["comparison"]) == set(METRICS)


class TestTrainingStats:
    def test_curve_is_preserved_in_order(self):
        training = [training_row(i + 1, 3, 0.5 * i) for i in range(5)]
        stats = build_stats_payload([], training)
        assert [p["step"] for p in stats["training"]["curve"]] == [1, 2, 3, 4, 5]
        assert stats["training"]["steps"] == 5

    def test_curve_keeps_q_values(self):
        training = [training_row(1, 3, 0.5, q=[0.1, 0.2, 0.9, 0.3, 0.05])]
        stats = build_stats_payload([], training)
        assert stats["training"]["curve"][0]["q_values"] == [0.1, 0.2, 0.9, 0.3, 0.05]

    def test_final_epsilon_is_reported(self):
        training = [training_row(1, 3, 0.5, epsilon=0.9), training_row(2, 3, 0.5, epsilon=0.81)]
        assert build_stats_payload([], training)["training"]["final_epsilon"] == 0.81

    def test_no_training_gives_empty_curve(self):
        stats = build_stats_payload(paired(n=2))
        assert stats["training"]["curve"] == []
        assert stats["training"]["steps"] == 0
        assert stats["training"]["final_epsilon"] is None

    def test_reward_descriptives(self):
        training = [training_row(i + 1, 3, float(i)) for i in range(5)]
        assert build_stats_payload([], training)["training"]["reward"]["mean"] == 2.0


class TestWholePayload:
    def test_empty_run_does_not_crash(self):
        stats = build_stats_payload([], [])
        assert stats["per_system"]["A"]["prompt_count"] == 0
        assert stats["paired_prompt_count"] == 0
        json.dumps(stats, allow_nan=False)

    def test_declares_its_schema_and_alpha(self):
        stats = build_stats_payload([])
        assert stats["schema_version"] == 1
        assert stats["alpha"] == 0.05
        assert stats["metrics"] == list(METRICS)

    def test_totals_are_reported_per_system(self):
        stats = build_stats_payload(paired(n=4, delta=0.1))
        for system in ("A", "B"):
            assert stats["per_system"][system]["prompt_count"] == 4
            assert stats["per_system"][system]["total_time_s"]["n"] == 4