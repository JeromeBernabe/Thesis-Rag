"""Contract tests for the two RAG wrappers.

These are the tests that pin the bug that stopped `run_experiment.py`: the
generator returns a dict, and before `src/result_shapes.py` existed the
wrappers handed that dict straight to a runner expecting a string. Every test
here asserts on *keys the runners actually index*, imported from the runners
themselves, so a future column rename fails here rather than 40 minutes into a
benchmark.
"""

from __future__ import annotations

import pytest

from run_experiment_logged import TRAINING_CSV_COLUMNS

from bench_bridge.tests.conftest import FakeAgent, FakeScorer
from src.baseline_rag import BaselineRAG
from src.dqn_rag import DQNRAG

# Keys the runners actually index on a wrapper result. Derived from
# run_experiment.py:67-72,136-142 and run_experiment_logged.py:93-98,139-158.
#
# `retrieved_k` and `total_time_s` are deliberately absent: the runner derives
# them (from settings.BASELINE_K / ks[i], and by summing the phase timings), so
# demanding them from the wrapper would encode a contract that does not exist.
ANSWER_RESULT_KEYS = (
    "answer",
    "contexts",
    "total_tokens",
    "generation_time_s",
    "retrieval_time_s",
)

DQN_ANSWER_RESULT_KEYS = ANSWER_RESULT_KEYS + ("k",)

# run_experiment_logged.py fills `step` and `q_values_k1..k5` itself (it calls
# its own get_q_values so it can format them), so the episode dict owes every
# other training column.
RUNNER_SUPPLIED_TRAINING_KEYS = {
    "step",
    "q_values_k1",
    "q_values_k2",
    "q_values_k3",
    "q_values_k4",
    "q_values_k5",
}


# ------------------------------------------------------------- System A tests


class TestBaselineRAG:
    @pytest.fixture
    def system(self, vector_store, generator):
        # `generator` must be requested first: BaselineRAG calls get_generator()
        # in __init__, so the double has to be installed before construction.
        return BaselineRAG(vector_store=vector_store, k=3, dataset="hotpot")

    def test_answer_is_a_string(self, system):
        """The original bug: result["answer"] was a dict."""
        assert isinstance(system.answer("q?")["answer"], str)

    def test_exposes_every_key_the_runner_indexes(self, system):
        missing = [c for c in ANSWER_RESULT_KEYS if c not in system.answer("q?")]
        assert missing == [], f"BaselineRAG.answer() is missing {missing}"

    def test_reports_the_fixed_k(self, system):
        assert system.answer("q?")["k"] == 3

    def test_contexts_are_returned(self, system):
        result = system.answer("q?")
        assert result["contexts"] == ["chunk 0 for q?", "chunk 1 for q?", "chunk 2 for q?"]

    def test_retrieval_time_is_measured(self, system):
        assert system.answer("q?")["retrieval_time_s"] >= 0.0

    def test_token_counts_come_from_the_generator(self, system, generator):
        """The runner records result["total_tokens"] as the generation cost."""
        result = system.answer("q?")
        expected = generator.answer("q?", result["contexts"])["total_tokens"]
        assert result["total_tokens"] == expected

    def test_detailed_retrieval_exposes_ids_and_distances(self, system):
        detailed = system.retrieve_detailed("q?")
        assert set(detailed) == {"ids", "documents", "distances"}
        assert len(detailed["ids"]) == 3
        assert detailed["distances"] == [1.0, 0.9, 0.8]

    def test_retrieve_and_retrieve_detailed_agree(self, system):
        assert system.retrieve("q?") == system.retrieve_detailed("q?")["documents"]

    def test_does_not_call_the_judge(self, vector_store):
        """System A must never be judged during a normal (no-judge) run."""
        store, scorer = vector_store, FakeScorer()
        BaselineRAG(vector_store=store, dataset="hotpot").answer("q?")
        assert scorer.calls == []


# ------------------------------------------------------------- System B tests


class TestDQNRAG:
    @pytest.fixture
    def agent(self):
        return FakeAgent(action=2)

    @pytest.fixture
    def system(self, vector_store, scorer, agent, generator):
        return DQNRAG(
            vector_store=vector_store,
            scorer=scorer,
            agent=agent,
            dataset="hotpot",
            checkpoint_path=None,
        )

    def test_action_maps_to_k_via_action_min(self, system, agent):
        """action index + ACTION_MIN_K == k; index 2 must be k=3."""
        result = system.answer("q?")
        assert result["action"] == agent.action
        assert result["k"] == result["action"] + 1

    def test_dqn_answer_exposes_every_key_the_runner_indexes(self, system):
        result = system.answer("q?")
        missing = [c for c in DQN_ANSWER_RESULT_KEYS if c not in result]
        assert missing == [], f"DQNRAG.answer() is missing {missing}"
        assert isinstance(result["answer"], str)

    def test_answer_exposes_q_values_for_the_decision_view(self, system):
        assert system.answer("q?")["q_values"] == [0.1, 0.2, 0.5, 0.3, 0.05]

    def test_answer_uses_the_greedy_policy(self, vector_store, scorer, monkeypatch):
        agent = FakeAgent(action=1)
        calls = []
        monkeypatch.setattr(
            type(agent),
            "greedy_action",
            lambda self, state: calls.append("greedy") or 1,
        )
        system = DQNRAG(vector_store, scorer, agent=agent, dataset="hotpot")
        system.answer("q?")
        assert calls == ["greedy"], "inference must not explore"


class TestDQNRAGTraining:
    @pytest.fixture
    def agent(self):
        return FakeAgent(action=3)

    @pytest.fixture
    def system(self, vector_store, scorer, agent, generator):
        return DQNRAG(
            vector_store=vector_store,
            scorer=scorer,
            agent=agent,
            dataset="hotpot",
            checkpoint_path=None,
        )

    def test_exposes_every_training_column_it_owes(self, system):
        """run_experiment_logged.py logs exactly these keys per step."""
        result = system.train_episode("q?", ground_truth="truth")
        owed = [c for c in TRAINING_CSV_COLUMNS if c not in RUNNER_SUPPLIED_TRAINING_KEYS]
        missing = [c for c in owed if c not in result]
        assert missing == [], f"train_episode() is missing {missing}"

    def test_passes_ground_truth_to_the_judge(self, system, scorer):
        system.train_episode("q?", ground_truth="the truth")
        assert scorer.calls[0]["reference"] == "the truth"

    def test_requests_all_three_metrics(self, system, scorer):
        system.train_episode("q?", ground_truth="t")
        assert scorer.calls[0]["metric_names"] == [
            "faithfulness",
            "answer_relevancy",
            "context_recall",
        ]

    def test_stores_the_transition_and_trains(self, system, agent):
        system.train_episode("q?")
        assert len(agent.stored) == 1
        _, action, _ = agent.stored[0]
        assert action == agent.action
        assert agent.trained == 1

    def test_decays_epsilon_and_saves_a_checkpoint(self, system, agent):
        system.train_episode("q?")
        assert agent.decayed == 1
        assert len(agent.saved) == 1

    def test_reward_is_computed_and_recorded(self, system, scorer):
        result = system.train_episode("q?", ground_truth="t")
        assert isinstance(result["reward"], float)
        assert result["reward"] == pytest.approx(
            0.35 * scorer.faithfulness + 0.35 * scorer.answer_relevancy
        )

    def test_total_time_is_the_sum_of_all_four_phases(self, system):
        r = system.train_episode("q?")
        assert r["total_time_s"] == pytest.approx(
            r["embedding_time_s"]
            + r["retrieval_time_s"]
            + r["generation_time_s"]
            + r["judge_time_s"]
        )

    def test_records_embedding_and_retrieval_time_separately(self, system):
        r = system.train_episode("q?")
        assert r["embedding_time_s"] >= 0.0
        assert r["retrieval_time_s"] >= 0.0

    def test_missing_reference_leaves_context_recall_none(self, vector_store, agent):
        """RAGAS needs a reference for context_recall; without one it is None."""
        scorer = FakeScorer(faithfulness=0.6, answer_relevancy=0.7, context_recall=None)
        system = DQNRAG(vector_store, scorer, agent=agent, dataset="hotpot")
        result = system.train_episode("q?")
        assert result["context_recall"] is None

    def test_train_step_returning_none_is_tolerated(self, vector_store, scorer, monkeypatch):
        """The buffer holds fewer than batch_size early on; that is not an error."""
        agent = FakeAgent()
        monkeypatch.setattr(type(agent), "train_step", lambda self: None)
        system = DQNRAG(vector_store, scorer, agent=agent, dataset="hotpot")
        assert system.train_episode("q?")["loss"] is None
