"""Contract tests for the shared result-shape helpers."""

from __future__ import annotations

import math

import pytest

from src.result_shapes import (
    ANSWER_KEYS,
    GENERATION_KEYS,
    canonical_answer,
    canonical_judge,
)


class TestCanonicalAnswer:
    def test_accepts_bare_string(self):
        """The pre-token-accounting generator shape must keep working."""
        out = canonical_answer("hello")
        assert out["answer"] == "hello"
        assert out["total_tokens"] == 0
        assert set(out) == set(GENERATION_KEYS)

    def test_accepts_current_dict_shape(self):
        out = canonical_answer(
            {
                "answer": "an answer",
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "generation_time_s": 2.5,
            }
        )
        assert out == {
            "answer": "an answer",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "generation_time_s": 2.5,
        }

    def test_rejects_other_types(self):
        with pytest.raises(TypeError, match="must be str or dict"):
            canonical_answer(42)

    def test_missing_answer_becomes_empty_string(self):
        """run_experiment.py indexes result["answer"]; it must never be absent."""
        assert canonical_answer({})["answer"] == ""

    @pytest.mark.parametrize(
        "raw,expected",
        [("3", 3), (3.9, 3), (None, 0), ("nonsense", 0)],
    )
    def test_token_coercion(self, raw, expected):
        assert canonical_answer({"answer": "x", "prompt_tokens": raw})[
            "prompt_tokens"
        ] == expected

    def test_total_tokens_falls_back_to_sum(self):
        out = canonical_answer(
            {"answer": "x", "prompt_tokens": 7, "completion_tokens": 3}
        )
        assert out["total_tokens"] == 10

    def test_explicit_total_tokens_wins_over_sum(self):
        """An inconsistent total must be reported, not silently recomputed."""
        out = canonical_answer(
            {
                "answer": "x",
                "prompt_tokens": 7,
                "completion_tokens": 3,
                "total_tokens": 99,
            }
        )
        assert out["total_tokens"] == 99

    def test_explicit_none_total_falls_back_to_sum(self):
        out = canonical_answer(
            {"answer": "x", "prompt_tokens": 7, "completion_tokens": 3, "total_tokens": None}
        )
        assert out["total_tokens"] == 10

    def test_nan_timing_becomes_zero(self):
        out = canonical_answer({"answer": "x", "generation_time_s": float("nan")})
        assert out["generation_time_s"] == 0.0
        assert not math.isnan(out["generation_time_s"])


class TestCanonicalJudge:
    def test_passes_metrics_through_including_none(self):
        """A missing verdict must stay None, not become 0.0.

        Zero is a *real* RAGAS score and the thesis compares means; silently
        substituting it would bias every aggregate.
        """
        out = canonical_judge(
            {"faithfulness": 0.5, "answer_relevancy": None, "context_recall": 0.7}
        )
        assert out["faithfulness"] == 0.5
        assert out["answer_relevancy"] is None
        assert out["context_recall"] == 0.7

    def test_none_input_yields_none_metrics(self):
        out = canonical_judge(None)
        assert out["faithfulness"] is None
        assert out["answer_relevancy"] is None
        assert out["context_recall"] is None

    def test_empty_dict_yields_none_metrics(self):
        assert canonical_judge({})["faithfulness"] is None

    def test_judge_metadata_is_coerced(self):
        out = canonical_judge(
            {
                "faithfulness": 1.0,
                "judge_prompt_tokens": "11",
                "judge_completion_tokens": 7.9,
                "judge_time_s": "1.25",
            }
        )
        assert out["judge_prompt_tokens"] == 11
        assert out["judge_completion_tokens"] == 7
        assert out["judge_time_s"] == 1.25

    def test_absent_judge_metadata_defaults_to_zero(self):
        out = canonical_judge({"faithfulness": 0.5})
        assert out["judge_prompt_tokens"] == 0
        assert out["judge_completion_tokens"] == 0
        assert out["judge_time_s"] == 0.0

    def test_nan_judge_time_becomes_zero(self):
        out = canonical_judge({"faithfulness": 0.5, "judge_time_s": float("nan")})
        assert out["judge_time_s"] == 0.0


def test_answer_keys_are_a_superset_of_generation_keys():
    """The canonical set must stay a subset of what wrappers must expose."""
    assert set(GENERATION_KEYS).issubset(set(ANSWER_KEYS))