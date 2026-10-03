"""Integration tests for the sidecar: full runs, no external services.

Every test drives `Runner` with `dry_run=True`, which substitutes in-process
fakes for ChromaDB, Ollama, the judge and the DQN. The orchestration, the event
protocol, the phase order and the statistics are all the real implementations -
only the leaves are fake.
"""

from __future__ import annotations

import io
import json

import pytest

from bench_bridge.events import EventEmitter, parse_envelope
from bench_bridge.run import RunSpec, Runner


def run_sidecar(**overrides) -> tuple[list, Runner]:
    """Execute a dry run and return the decoded events plus the runner."""
    options = {"dry_run": True, "no_judge": True, "limit": 3}
    options.update(overrides)
    spec = RunSpec(**options)
    stream = io.StringIO()
    emitter = EventEmitter(spec.run_id, stream=stream)
    runner = Runner(spec, emitter=emitter)
    code = runner.run_guarded()
    events = [
        parse_envelope(line) for line in stream.getvalue().strip().split("\n")
    ]
    assert code == 0, [e for e in events if e.type == "run_failed"]
    return events, runner


def types_of(events) -> list[str]:
    return [e.type for e in events]


def data_of(events, event_type: str) -> list[dict]:
    return [e.data for e in events if e.type == event_type]


class TestEventStreamShape:
    def test_emits_at_least_one_event(self):
        events, _ = run_sidecar()
        assert len(events) > 10

    def test_sequence_numbers_are_contiguous_from_one(self):
        events, _ = run_sidecar()
        assert [e.seq for e in events] == list(range(1, len(events) + 1))

    def test_every_event_carries_the_run_id(self):
        events, runner = run_sidecar()
        assert {e.run_id for e in events} == {runner.spec.run_id}

    def test_starts_with_run_started_and_ends_with_run_finished(self):
        events, _ = run_sidecar()
        assert types_of(events)[0] == "run_started"
        assert types_of(events)[-1] == "run_finished"

    def test_no_run_failed_event(self):
        events, _ = run_sidecar()
        assert "run_failed" not in types_of(events)

    def test_every_line_is_strict_json(self):
        """The Rust side parses with serde_json, which rejects bare NaN."""
        spec = RunSpec(dry_run=True, no_judge=True, limit=1)
        stream = io.StringIO()
        code = Runner(spec, EventEmitter(spec.run_id, stream=stream)).run_guarded()
        assert code == 0
        for line in stream.getvalue().strip().split("\n"):
            json.loads(line)


class TestPhaseOrder:
    def test_phases_appear_in_the_documented_order(self):
        events, _ = run_sidecar()
        phases = [e.data["phase"] for e in events if e.type == "phase"]
        expected = [
            "preflight", "projection", "system_a", "system_b_train",
            "system_b_infer", "stats", "done",
        ]
        assert phases == expected

    def test_projection_runs_after_indexing_not_before(self):
        """The 3D map is computed from the corpus embeddings."""
        events, _ = run_sidecar()
        phases = [e.data["phase"] for e in events if e.type == "phase"]
        assert phases.index("projection") > phases.index("preflight")
        assert phases.index("projection") < phases.index("system_a")

    def test_skip_projection_removes_the_phase(self):
        events, _ = run_sidecar(skip_projection=True)
        phases = [e.data["phase"] for e in events if e.type == "phase"]
        assert "projection" not in phases
        assert "system_a" in phases


class TestSystems:
    def test_runs_system_a_only_when_selected(self):
        events, runner = run_sidecar(systems=["A"])
        assert runner.prompt_rows
        assert {r["system"] for r in runner.prompt_rows} == {"A"}
        assert "system_b_train" not in [e.data["phase"] for e in events if e.type == "phase"]

    def test_runs_system_b_only_when_selected(self):
        events, runner = run_sidecar(systems=["B"])
        assert {r["system"] for r in runner.prompt_rows} == {"B"}
        assert runner.training_rows

    def test_system_b_produces_both_training_and_inference_rows(self):
        _, runner = run_sidecar(systems=["B"], limit=2)
        assert len(runner.training_rows) == 2
        assert len(runner.prompt_rows) == 2

    def test_trained_agent_is_reused_for_inference(self):
        """B.2 must run on the policy B.1 produced, not a fresh network.

        A fresh agent would restart epsilon at 1.0, so the epsilon reported by
        the inference decisions would be exactly 1.0 instead of the decayed
        value training ended on.
        """
        events, runner = run_sidecar(systems=["B"], limit=3)
        inference = [
            d for d in data_of(events, "decision") if d["phase"] == "system_b_infer"
        ]
        assert inference
        final_train_epsilon = runner.training_rows[-1]["epsilon"]
        assert final_train_epsilon < 1.0
        assert inference[0]["epsilon"] == pytest.approx(final_train_epsilon)

    def test_system_a_uses_the_configured_baseline_k(self):
        events, runner = run_sidecar(systems=["A"], limit=2)
        assert all(row["retrieved_k"] == 3 for row in runner.prompt_rows)

    def test_one_row_per_prompt_per_inference_system(self):
        _, runner = run_sidecar(limit=3)
        keys = [(r["system"], r["prompt_id"]) for r in runner.prompt_rows]
        assert len(keys) == len(set(keys))
        assert len(keys) == 6  # 3 prompts x {A, B-inference}


class TestPromptLifecycle:
    def test_each_prompt_emits_started_retrieval_and_completed(self):
        events, _ = run_sidecar(systems=["A"], limit=2)
        assert types_of(events).count("prompt_started") == 2
        assert types_of(events).count("retrieval") == 2
        assert types_of(events).count("generation") == 2
        assert types_of(events).count("prompt_completed") == 2

    def test_retrieval_reports_k_ids_and_distances(self):
        events, _ = run_sidecar(systems=["A"], limit=1)
        retrieval = data_of(events, "retrieval")[0]
        assert retrieval["k"] == 3
        assert len(retrieval["ids"]) == 3
        assert len(retrieval["distances"]) == 3
        assert len(retrieval["previews"]) == 3

    def test_retrieval_event_carries_the_ids_the_wrapper_returned(self):
        """Retrieval must not be re-queried just to build the event."""
        events, runner = run_sidecar(systems=["A"], limit=1)
        assert data_of(events, "retrieval")[0]["ids"] == (
            runner.prompt_rows[0]["retrieved_ids"]
        )

    def test_retrieved_ids_are_persisted_with_the_row(self):
        """The Results page re-uses them to place chunks on the 3D map."""
        _, runner = run_sidecar(systems=["A"], limit=1)
        row = runner.prompt_rows[0]
        assert len(row["retrieved_ids"]) == row["retrieved_k"]
        assert len(row["retrieved_distances"]) == row["retrieved_k"]

    def test_prompt_started_includes_the_total(self):
        events, _ = run_sidecar(systems=["A"], limit=3)
        started = data_of(events, "prompt_started")
        assert all(d["total"] == 3 for d in started)

    def test_training_emits_a_decision_with_q_values(self):
        events, _ = run_sidecar(systems=["B"], limit=2)
        decisions = data_of(events, "decision")
        assert len(decisions) == 4  # 2 training + 2 inference
        assert all(len(d["q_values"]) == 5 for d in decisions)

    def test_decision_reports_the_rank_of_the_chosen_action(self):
        events, _ = run_sidecar(systems=["B"], limit=2)
        decision = data_of(events, "decision")[0]
        assert decision["chosen_rank"] is not None
        q = decision["q_values"]
        expected = sorted(q, reverse=True).index(decision["q_values"][decision["action"]]) + 1
        assert decision["chosen_rank"] == expected


class TestJudge:
    def test_no_judge_suppresses_ragas_events(self):
        events, runner = run_sidecar(no_judge=True, limit=2)
        assert "ragas" not in types_of(events)
        assert all(r["faithfulness"] is None for r in runner.prompt_rows)

    def test_judge_enabled_emits_ragas_events_with_metrics(self):
        events, _ = run_sidecar(no_judge=False, limit=2)
        judged = data_of(events, "ragas")
        assert judged
        assert all(d["faithfulness"] is not None for d in judged)

    def test_judge_metadata_lands_on_the_row(self):
        _, runner = run_sidecar(no_judge=False, systems=["A"], limit=1)
        row = runner.prompt_rows[0]
        assert row["judge_prompt_tokens"] is not None
        assert row["judge_time_s"] is not None


class TestTrainingRows:
    def test_step_numbers_are_one_based_and_contiguous(self):
        _, runner = run_sidecar(systems=["B"], limit=3)
        assert [r["step"] for r in runner.training_rows] == [1, 2, 3]

    def test_rows_carry_the_training_csv_columns(self):
        from run_experiment_logged import TRAINING_CSV_COLUMNS

        _, runner = run_sidecar(systems=["B"], limit=1)
        row = runner.training_rows[0]
        # q_values is expanded by the runner; step is supplied here.
        for column in TRAINING_CSV_COLUMNS:
            if column.startswith("q_values_k"):
                continue
            assert column in row, f"training row is missing {column}"

    def test_train_step_events_are_emitted(self):
        events, _ = run_sidecar(systems=["B"], limit=3)
        steps = data_of(events, "train_step")
        assert [s["step"] for s in steps] == [1, 2, 3]

    def test_train_step_carries_the_q_values(self):
        """The Results page plots one line per action, which needs the Q-values.

        This is the payload the Rust store expands into ``q_values_k1``..``_k5``, so
        a missing or truncated list would plot five empty series without anything
        looking broken.
        """
        events, _ = run_sidecar(systems=["B"], limit=2)
        for step in data_of(events, "train_step"):
            assert len(step["q_values"]) == 5
            assert all(isinstance(value, float) for value in step["q_values"])

    def test_train_step_carries_the_row_fields_the_store_persists(self):
        events, runner = run_sidecar(systems=["B"], limit=1)
        step = data_of(events, "train_step")[0]
        stored = runner.training_rows[0]
        # The event is flat, so it must agree with the row the CSV writer uses.
        assert step["step"] == stored["step"]
        assert step["reward"] == stored["reward"]
        assert step["loss"] == stored["loss"]
        assert step["epsilon"] == stored["epsilon"]
        assert step["k"] == stored["k"]

    def test_loss_is_none_until_the_buffer_fills(self):
        """Below batch_size the agent skips the update; that must not crash."""
        _, runner = run_sidecar(systems=["B"], limit=3)
        assert runner.training_rows[0]["loss"] is None
        assert runner.training_rows[-1]["loss"] is not None


class TestCompletedRowPayload:
    """`prompt_completed` carries the row so the app can store it live."""

    def test_prompt_completed_carries_a_public_row(self):
        events, runner = run_sidecar(systems=["A"], limit=1)
        completed = data_of(events, "prompt_completed")
        assert len(completed) == 1
        row = completed[0]["row"]
        assert row["system"] == "A"
        assert row["question"]
        assert row["answer"]

    def test_prompt_completed_row_matches_the_stored_row(self):
        # The event and the CSV must not be able to drift, because the live Results
        # view is built from the event while the CSVs are written from the row. The
        # event row is the public subset, so compare against the stored row with
        # the stripped keys removed.
        events, runner = run_sidecar(systems=["A"], limit=1)
        stored = dict(runner.prompt_rows[0])
        for internal_only in ("contexts", "system_id", "index"):
            stored.pop(internal_only, None)
        assert data_of(events, "prompt_completed")[0]["row"] == stored

    def test_prompt_completed_row_omits_the_context_payload(self):
        """Contexts are multi-megabyte; the event must not carry them per prompt."""
        events, _ = run_sidecar(systems=["A"], limit=1)
        row = data_of(events, "prompt_completed")[0]["row"]
        assert "contexts" not in row
        # `system_id` and the duplicated `index` are storage keys, not results.
        assert "system_id" not in row

    def test_system_b_rows_are_completed_too(self):
        events, _ = run_sidecar(systems=["B"], limit=1)
        completed = data_of(events, "prompt_completed")
        # One inference row; training steps are not prompt completions.
        assert len(completed) == 1
        assert completed[0]["row"]["system"] == "B"
        assert completed[0]["row"]["retrieved_k"] is not None


class TestTiming:
    def test_every_row_has_a_positive_total_time(self):
        _, runner = run_sidecar(limit=2)
        assert all(r["total_time_s"] > 0 for r in runner.prompt_rows)

    def test_total_time_is_the_sum_of_the_phases(self):
        _, runner = run_sidecar(limit=2, systems=["A"])
        for row in runner.prompt_rows:
            total = (
                (row["retrieval_time_s"] or 0.0)
                + (row["generation_time_s"] or 0.0)
                + (row["judge_time_s"] or 0.0)
            )
            assert row["total_time_s"] == pytest.approx(total)

    def test_system_b_inference_includes_embedding_time(self):
        _, runner = run_sidecar(limit=2, systems=["B"])
        for row in runner.prompt_rows:
            total = (
                (row["embedding_time_s"] or 0.0)
                + (row["retrieval_time_s"] or 0.0)
                + (row["generation_time_s"] or 0.0)
                + (row["judge_time_s"] or 0.0)
            )
            assert row["total_time_s"] == pytest.approx(total)


class TestStatsEvent:
    def test_stats_event_is_emitted_before_run_finished(self):
        events, _ = run_sidecar()
        types = types_of(events)
        assert types.index("stats") < types.index("run_finished")

    def test_stats_payload_is_json_encodable(self):
        events, _ = run_sidecar()
        payload = data_of(events, "stats")[0]
        json.dumps(payload, allow_nan=False)

    def test_stats_cover_both_systems(self):
        events, _ = run_sidecar(limit=2)
        stats = data_of(events, "stats")[0]
        assert set(stats["per_system"]) == {"A", "B"}

    def test_run_finished_summarises_the_run(self):
        events, runner = run_sidecar(limit=2)
        summary = data_of(events, "run_finished")[0]
        assert summary["prompt_count"] == 2
        assert summary["prompt_rows"] == 4  # A + B inference
        assert summary["training_rows"] == 2
        assert summary["dry_run"] is True

    def test_dry_run_is_flagged_in_the_summary(self):
        """A fake run must never be mistakable for a measurement."""
        events, _ = run_sidecar()
        assert data_of(events, "run_started")[0]["dry_run"] is True
        assert data_of(events, "run_finished")[0]["dry_run"] is True


class TestFailureHandling:
    def test_unknown_dataset_fails_with_a_run_failed_event(self):
        spec = RunSpec(dataset="not-a-dataset", dry_run=True, limit=1)
        stream = io.StringIO()
        code = Runner(spec, EventEmitter(spec.run_id, stream=stream)).run_guarded()
        events = [parse_envelope(line) for line in stream.getvalue().strip().split("\n")]
        assert code == 1
        failure = [e for e in events if e.type == "run_failed"]
        assert failure and "unknown dataset" in failure[0].data["error"]
        assert "Traceback" in failure[0].data["traceback"]

    def test_empty_system_selection_is_rejected(self):
        with pytest.raises(ValueError, match="at least one system"):
            RunSpec(systems=[], dry_run=True).validate(("hotpot",))

    def test_bad_limit_is_rejected(self):
        with pytest.raises(ValueError, match="limit must be"):
            RunSpec(limit=0, dry_run=True).validate(("hotpot",))


class TestRunSpec:
    def test_from_json_round_trips(self):
        spec = RunSpec(dataset="math", limit=7, no_judge=True, dry_run=True)
        assert RunSpec.from_json(json.dumps(spec.to_dict())) == spec

    def test_from_json_ignores_unknown_keys(self):
        """The app may send extra fields; they must not crash the sidecar."""
        restored = RunSpec.from_json(
            json.dumps({"dataset": "math", "limit": 2, "future_field": True})
        )
        assert restored.dataset == "math"

    def test_generates_a_run_id_by_default(self):
        assert len(RunSpec().run_id) == 32

    def test_run_ids_are_unique(self):
        assert RunSpec().run_id != RunSpec().run_id