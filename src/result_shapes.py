"""Canonical result shapes shared by the RAG wrappers.

`src.generator.Generator.answer` returns a dict carrying the generated text,
token counts and the generation wall time. The wrappers in
`src.baseline_rag` and `src.dqn_rag` hand that payload on to the runners in
`run_experiment.py` / `run_experiment_logged.py`, which expect the *text* plus a
flat set of token/timing keys.

These helpers normalise both shapes so every wrapper can expose one canonical
result dict regardless of whether the generator returned a bare string or a
dict. Keeping the logic here avoids duplicating the unwrapping in both
wrappers and gives the desktop app a single definition to rely on.
"""

from __future__ import annotations

__all__ = [
    "ANSWER_KEYS",
    "GENERATION_KEYS",
    "TIMING_KEYS",
    "JUDGE_KEYS",
    "canonical_answer",
    "canonical_judge",
]


#: Keys every `answer()` implementation must expose.
ANSWER_KEYS = ("answer", "contexts", "k", "prompt_tokens", "completion_tokens", "total_tokens", "retrieval_time_s", "generation_time_s")

#: Keys produced by `canonical_answer` before the wrapper adds its own.
GENERATION_KEYS = ("answer", "prompt_tokens", "completion_tokens", "total_tokens", "generation_time_s")

#: Wall-clock keys that must always be non-negative floats.
TIMING_KEYS = ("retrieval_time_s", "generation_time_s")

#: Keys copied out of a RAGAS score dict.
JUDGE_KEYS = ("judge_prompt_tokens", "judge_completion_tokens", "judge_time_s")


def _as_float(value, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out:  # NaN
        return default
    return out


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def canonical_answer(response) -> dict:
    """Normalise a generator response into the canonical generation dict.

    Accepts either a bare ``str`` (the pre-token-accounting generator shape) or
    the current dict shape, and always returns exactly the
    :data:`GENERATION_KEYS` with non-negative timings and integer token counts.

    Missing token metadata is reported as ``0`` rather than guessed, so the
    distinction between "the generator said zero" and "the generator was not
    measured" stays visible in the caller's logs rather than being invented.
    """
    if isinstance(response, str):
        return {
            "answer": response,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "generation_time_s": 0.0,
        }

    if not isinstance(response, dict):
        raise TypeError(f"generator response must be str or dict, got {type(response)!r}")

    prompt_tokens = _as_int(response.get("prompt_tokens"))
    completion_tokens = _as_int(response.get("completion_tokens"))
    total_tokens = _as_int(response.get("total_tokens"), prompt_tokens + completion_tokens)

    return {
        "answer": str(response.get("answer", "")),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "generation_time_s": _as_float(response.get("generation_time_s")),
    }


def canonical_judge(scores) -> dict:
    """Extract the token/timing metadata from a RAGAS score dict.

    ``scores`` may be ``None`` (no judge was run) or a dict from
    ``RagasScorer.score_single``. The three RAGAS metrics are passed through
    untouched, including ``None``, because a missing score means "the judge
    produced no usable verdict" and must not be coerced to zero.
    """
    scores = scores or {}
    return {
        "faithfulness": scores.get("faithfulness"),
        "answer_relevancy": scores.get("answer_relevancy"),
        "context_recall": scores.get("context_recall"),
        "judge_prompt_tokens": _as_int(scores.get("judge_prompt_tokens")),
        "judge_completion_tokens": _as_int(scores.get("judge_completion_tokens")),
        "judge_time_s": _as_float(scores.get("judge_time_s")),
    }