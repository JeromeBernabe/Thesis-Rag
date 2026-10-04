"""RAGAS-metric-compatible scoring run against a local Ollama judge.

Implements the exact RAGAS 0.4 metric definitions (faithfulness, answer
relevancy, context recall) using a compact, judge-friendly JSON protocol that
small local models like llama3.2 can reliably follow:

  - faithfulness    = (statements in the answer supported by context) / total
  - answer relevancy= mean cosine similarity (nomic-embed-text) between the
                      question and {strictness} questions generated from the answer
  - context recall  = (reference statements attributed to retrieved context) / total

The output interface mirrors ragas: score()/score_single() return per-sample
dicts keyed by metric name, with None where a score could not be computed.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from langchain_ollama import OllamaEmbeddings

from config import settings

logger = logging.getLogger(__name__)

FULL_METRICS = ["faithfulness", "answer_relevancy", "context_recall"]
REWARD_METRICS = ["faithfulness", "answer_relevancy"]

JSON_HEADER = "Return ONLY a single JSON object. Do not add any text before or after the JSON."


def _extract_json(text: str) -> str | None:
    """Return the first balanced JSON object substring, or None."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


class RagasScorer:
    def __init__(
        self,
        judge_model: str = settings.JUDGE_MODEL,
        embed_model: str = settings.EMBED_MODEL,
        base_url: str = settings.OLLAMA_BASE_URL,
        max_workers: int = settings.RAGAS_MAX_WORKERS,
        timeout: int = settings.RAGAS_TIMEOUT,
        strictness: int = 3,
        max_retries: int = 5,
    ):
        self.judge_model = judge_model
        self.embed_model = embed_model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.strictness = strictness
        self.max_retries = max_retries
        # Cleared at runtime if the local Ollama build rejects the field.
        self._think_supported = True
        self._embeddings = OllamaEmbeddings(model=embed_model, base_url=base_url)
        self.max_workers = max_workers

        # --- concurrency safety ---
        #
        # `score()` may run several prompts at once, and three pieces of state
        # here are shared across calls:
        #
        # - The judge token/time counters were plain attributes, reset at the top
        #   of `_score_one` and accumulated by every metric helper. Run two
        #   prompts concurrently and each one's counters absorb the other's
        #   judge calls, so the per-row `judge_*` columns stop belonging to that
        #   row - and a fast prompt finishing late would leave a stale total on
        #   the next one. They are now per-thread, which is sufficient because a
        #   task never migrates between threads inside the pool.
        # - `_think_supported` is capability state discovered at runtime. Two
        #   threads hitting a 400 at once could both decide to drop the field,
        #   and one could observe it mid-update, so it is read and written under
        #   a lock.
        # - The embedding client is serialised. `OllamaEmbeddings` wraps a
        #   client whose thread safety is not something we have verified, and
        #   answer relevancy needs one embedding round-trip per scored prompt.
        #   Serialising it costs little next to a 50-80s judge call and removes
        #   the question entirely.
        self._counters = threading.local()
        self._state_lock = threading.Lock()
        self._embed_lock = threading.Lock()

    # ------------------------------------------------------------------ infra
    def _complete(self, prompt: str, max_tokens: int = 400) -> tuple[str, dict]:
        # `attempt` counts genuine judge failures only. Negotiating away the
        # `think` field is capability discovery, not a transient error, so it
        # must not consume the retry budget - otherwise a single 400 can
        # exhaust the retries and fail a run that would otherwise have succeeded.
        attempt = 0
        while True:
            try:
                payload = {
                    "model": self.judge_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": 0.0,
                    },
                }
                # Thinking must be off for a judge. Reasoning models (qwen3 and
                # friends) emit a scratchpad first, and it is billed against
                # `num_predict`, so the JSON never finishes: a 279-token reply
                # that was 41 tokens without it arrived as the bare text
                # "{\n\n}", and every faithfulness and context-recall call
                # failed after six retries with "no JSON object found". It cost
                # four times the latency to return nothing.
                #
                # Sent as `think: false` rather than by filtering the model name,
                # because the field is authoritative. A model that does not
                # support it may reject the request outright, so the flag is
                # dropped for good once that is seen.
                if self._think_supported:
                    payload["think"] = False
                t0 = time.perf_counter()
                resp = requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=self.timeout,
                )
                elapsed = time.perf_counter() - t0
                if resp.status_code == 400 and self._think_supported:
                    # Older Ollama builds reject the unknown field outright
                    # rather than ignoring it. Stop sending it.
                    with self._state_lock:
                        self._think_supported = False
                    logger.info(
                        "Judge %s rejected think=false; continuing without it.",
                        self.judge_model,
                    )
                    continue
                resp.raise_for_status()
                data = resp.json()
                meta = {
                    "judge_prompt_tokens": data.get("prompt_eval_count", 0) or 0,
                    "judge_completion_tokens": data.get("eval_count", 0) or 0,
                    "judge_time_s": elapsed,
                }
                return data.get("response", ""), meta
            except Exception as exc:  # noqa: BLE001
                attempt += 1
                logger.warning("Judge request attempt %d failed: %s", attempt, exc)
                if attempt > self.max_retries:
                    raise
                time.sleep(2.0 * attempt)

    def _complete_json(self, prompt: str, max_tokens: int = 400) -> tuple[dict | None, dict]:
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                text, meta = self._complete(prompt, max_tokens=max_tokens)
                blob = _extract_json(text)
                if blob is None:
                    raise ValueError("no JSON object found in response")
                data = json.loads(blob)
                if isinstance(data, dict):
                    return data, meta
                raise ValueError("JSON is not an object")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.debug("JSON completion attempt %d failed: %s", attempt + 1, exc)
        logger.warning("Judge returned unusable output after %d attempts: %s", self.max_retries + 1, last_error)
        return None, {"judge_prompt_tokens": 0, "judge_completion_tokens": 0, "judge_time_s": 0.0}

    @staticmethod
    def _as_list(data: dict | None, key: str) -> list[str]:
        if not data or not isinstance(data.get(key), list):
            return []
        return [str(x).strip() for x in data[key] if str(x).strip()]

    @staticmethod
    def _safe_ratio(numerator: int, denominator: int) -> float | None:
        if denominator <= 0:
            return None
        return numerator / denominator

    def _reset_counters(self) -> dict:
        """Fresh counters for the calling thread. See the note in `__init__`."""
        counters = {"judge_prompt_tokens": 0, "judge_completion_tokens": 0, "judge_time_s": 0.0}
        self._counters.state = counters
        return counters

    def _current_counters(self) -> dict:
        counters = getattr(self._counters, "state", None)
        if counters is None:
            counters = self._reset_counters()
        return counters

    def _accumulate_judge_meta(self, meta: dict) -> None:
        counters = self._current_counters()
        counters["judge_prompt_tokens"] += meta.get("judge_prompt_tokens", 0)
        counters["judge_completion_tokens"] += meta.get("judge_completion_tokens", 0)
        counters["judge_time_s"] += meta.get("judge_time_s", 0.0)

    @staticmethod
    def _verdict_value(item: dict, key: str) -> int:
        v = item.get(key)
        if isinstance(v, bool):
            return 1 if v else 0
        if isinstance(v, (int, float)):
            return 1 if float(v) >= 0.5 else 0
        if isinstance(v, str):
            return 1 if v.strip().lower() in ("1", "true", "yes", "y") else 0
        return 0

    def _align_verdicts(
        self, statements: list[str], items: list[dict], verdict_key: str
    ) -> list[int] | None:
        """Align judge verdict items to statements (by text match, else by index)."""
        if not items:
            return None
        items = [i for i in items if isinstance(i, dict)]
        if not items:
            return None
        if len(items) == len(statements):
            return [self._verdict_value(item, verdict_key) for item in items]
        matched: dict[int, int] = {}
        used: set[int] = set()
        for item in items:
            label = str(item.get("statement", "")).strip()
            if not label:
                continue
            for i, statement in enumerate(statements):
                if i in used:
                    continue
                if label == statement or (
                    len(label) >= 6 and len(statement) >= 6
                    and (label in statement or statement in label)
                ):
                    matched[i] = self._verdict_value(item, verdict_key)
                    used.add(i)
                    break
        if len(matched) == len(statements):
            return [matched[i] for i in range(len(statements))]
        if len(items) >= len(statements):
            return [
                self._verdict_value(item, verdict_key) for item in items[: len(statements)]
            ]
        for i in range(len(statements)):
            if i not in matched:
                matched[i] = 0
        return [matched[i] for i in range(len(statements))]

    # ------------------------------------------------------------ faithfulness
    def _answer_statements(self, answer: str) -> list[str]:
        prompt = (
            "Break the following answer into short, standalone factual statements. "
            "Do not use pronouns; every statement must be fully understandable on its own.\n"
            f"Answer:\n{answer}\n"
            f'{JSON_HEADER}\n{{"statements": ["statement 1", "statement 2", ...]}}'
        )
        data, meta = self._complete_json(prompt, max_tokens=600)
        self._accumulate_judge_meta(meta)
        result = self._as_list(data, "statements")
        if not result:
            fallback = (
                "List every distinct factual claim in the following text as a separate item. "
                "Output as a JSON list of strings.\n"
                f"Text:\n{answer}\n"
                f'{JSON_HEADER}\n{{"statements": ["1. ...", "2. ..."]}}'
            )
            data2, meta2 = self._complete_json(fallback, max_tokens=600)
            self._accumulate_judge_meta(meta2)
            result = self._as_list(data2, "statements")
        return result

    def _nli_verdicts(self, statements: list[str], context: str) -> list[int] | None:
        context_trunc = context[:8000]
        stmts_json = json.dumps(statements)
        prompt = (
            "Determine whether each statement is supported by the context. "
            "Use verdict 1 if the context supports the statement, otherwise 0. "
            "Return exactly one verdict per statement, using the exact statement text.\n"
            f"Context:\n{context_trunc}\n\n"
            f"Statements:\n{stmts_json}\n"
            f'{JSON_HEADER}\n{{"verdicts": [{{"statement": "...", "verdict": 0}}]}}'
        )
        data, meta = self._complete_json(prompt, max_tokens=800)
        self._accumulate_judge_meta(meta)
        if not data or not isinstance(data.get("verdicts"), list):
            return None
        verdicts = [v for v in data["verdicts"] if isinstance(v, dict)]
        if not verdicts:
            return None
        return self._align_verdicts(statements, verdicts, "verdict")

    def _score_faithfulness(self, question: str, response: str, contexts: list[str]) -> float | None:
        statements = self._answer_statements(response)
        if not statements:
            logger.warning("Faithfulness: no statements extracted from answer; score = NaN")
            return None
        context = "\n\n".join(contexts)
        verdicts = self._nli_verdicts(statements, context)
        if verdicts is None:
            logger.warning("Faithfulness: verdicts could not be aligned to statements")
            return None
        return self._safe_ratio(sum(verdicts), len(verdicts))

    # --------------------------------------------------------- answer relevancy
    def _generated_questions(self, answer: str, n: int) -> list[str]:
        prompt = (
            f"Generate {n} different questions that the following answer could be the "
            "answer to. The questions must be answerable using the answer alone.\n"
            f"Answer:\n{answer}\n"
            f'{JSON_HEADER}\n{{"questions": ["question 1", ...]}}'
        )
        data, meta = self._complete_json(prompt)
        self._accumulate_judge_meta(meta)
        return self._as_list(data, "questions")

    def _score_answer_relevancy(self, question: str, response: str) -> float | None:
        gen_questions = self._generated_questions(response, self.strictness)
        if not gen_questions:
            logger.warning("AnswerRelevancy: no questions generated; score = 0")
            return 0.0
        try:
            # Serialised: the client is shared and its thread safety is not
            # verified. See the note in `__init__`.
            with self._embed_lock:
                q_vec = np.asarray(self._embeddings.embed_query(question), dtype=np.float64).reshape(1, -1)
                gen_vec = np.asarray(self._embeddings.embed_documents(gen_questions), dtype=np.float64)
            gen_vec = gen_vec.reshape(len(gen_questions), -1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AnswerRelevancy: embedding failed: %s", exc)
            return None
        q_norm = np.linalg.norm(q_vec, axis=1)
        g_norm = np.linalg.norm(gen_vec, axis=1)
        denom = q_norm * g_norm
        denom[denom == 0] = np.nan
        sims = np.dot(gen_vec, q_vec.T).reshape(-1) / denom
        sims = sims[~np.isnan(sims)]
        if len(sims) == 0:
            return None
        return float(np.mean(sims))

    # ----------------------------------------------------------- context recall
    def _reference_statements(self, reference: str) -> list[str]:
        prompt = (
            "Break the following reference answer into short, standalone factual "
            "statements. Do not use pronouns; every statement must be fully "
            "understandable on its own.\n"
            f"Reference answer:\n{reference}\n"
            f'{JSON_HEADER}\n{{"statements": ["statement 1", "statement 2", ...]}}'
        )
        data, meta = self._complete_json(prompt, max_tokens=600)
        self._accumulate_judge_meta(meta)
        result = self._as_list(data, "statements")
        if not result:
            fallback = (
                "List every distinct factual claim in the following text as a separate item. "
                "Output as a JSON list of strings.\n"
                f"Text:\n{reference}\n"
                f'{JSON_HEADER}\n{{"statements": ["1. ...", "2. ..."]}}'
            )
            data2, meta2 = self._complete_json(fallback, max_tokens=600)
            self._accumulate_judge_meta(meta2)
            result = self._as_list(data2, "statements")
        return result

    def _attribution_verdicts(self, statements: list[str], context: str) -> list[int] | None:
        context_trunc = context[:8000]
        stmts_json = json.dumps(statements)
        prompt = (
            "Given the context, classify whether each statement can be attributed to "
            "(i.e. is supported by) the context. Use 1 if yes, otherwise 0. "
            "Return exactly one verdict per statement, using the exact statement text.\n"
            f"Context:\n{context_trunc}\n\n"
            f"Statements:\n{stmts_json}\n"
            f'{JSON_HEADER}\n{{"verdicts": [{{"statement": "...", "attributed": 1}}]}}'
        )
        data, meta = self._complete_json(prompt, max_tokens=800)
        self._accumulate_judge_meta(meta)
        if not data or not isinstance(data.get("verdicts"), list):
            return None
        verdicts = [v for v in data["verdicts"] if isinstance(v, dict)]
        if not verdicts:
            return None
        key = "attributed"
        if verdicts and not any("attributed" in v for v in verdicts):
            for alt in ("verdict", "supported", "is_supported", "can_be_attributed"):
                if any(alt in v for v in verdicts):
                    key = alt
                    break
        return self._align_verdicts(statements, verdicts, key)

    def _score_context_recall(
        self, question: str, response: str, contexts: list[str], reference: str
    ) -> float | None:
        statements = self._reference_statements(reference)
        if not statements:
            logger.warning("ContextRecall: no statements extracted from reference; score = NaN")
            return None
        context = "\n\n".join(contexts)
        verdicts = self._attribution_verdicts(statements, context)
        if verdicts is None:
            logger.warning("ContextRecall: verdicts could not be aligned to statements")
            return None
        return self._safe_ratio(sum(verdicts), len(verdicts))

    # ------------------------------------------------------------- public API
    def _score_one(
        self,
        question: str,
        response: str,
        contexts: list[str],
        reference: str | None,
        metric_names: list[str],
    ) -> dict[str, float | None]:
        counters = self._reset_counters()
        row: dict[str, float | None] = {}
        if "faithfulness" in metric_names:
            row["faithfulness"] = self._score_faithfulness(question, response, contexts)
        if "answer_relevancy" in metric_names:
            row["answer_relevancy"] = self._score_answer_relevancy(question, response)
        if "context_recall" in metric_names:
            if reference is None:
                logger.warning("ContextRecall requires a ground-truth reference; score = NaN")
                row["context_recall"] = None
            else:
                row["context_recall"] = self._score_context_recall(
                    question, response, contexts, reference
                )
        row["judge_prompt_tokens"] = counters["judge_prompt_tokens"]
        row["judge_completion_tokens"] = counters["judge_completion_tokens"]
        row["judge_time_s"] = counters["judge_time_s"]
        return row

    def close(self) -> None:
        """Release the embedding client's connections.

        A run creates a scorer per system and the desktop app creates one per
        benchmark, each holding an HTTP client. Without this they are only
        reclaimed by the garbage collector, which under a warning-as-error
        policy shows up as an unraisable ResourceWarning rather than at the
        call site that caused it.
        """
        client = getattr(self._embeddings, "client", None)
        closer = getattr(client, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception as exc:  # noqa: BLE001 - teardown is best effort
                logger.debug("closing embedding client failed: %s", exc)

    def __enter__(self) -> "RagasScorer":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def score(
        self,
        questions: list[str],
        responses: list[str],
        retrieved_contexts: list[list[str]],
        references: list[str] | None = None,
        metric_names: list[str] | None = None,
    ) -> list[dict[str, float | None]]:
        """Score every prompt, optionally several at a time.

        Concurrency is bounded by `max_workers` and results are returned in
        input order regardless of completion order, so the CSV a run writes is
        byte-identical to the sequential one. `max_workers=1` takes the original
        loop unchanged.

        Failures are not swallowed. If one prompt exhausts the judge's retries
        the exception propagates, exactly as it does sequentially - a run that
        silently dropped half its prompts is the failure mode this whole area
        of the code was rewritten to prevent.
        """
        metric_names = metric_names or FULL_METRICS
        pairs = list(zip(questions, responses, retrieved_contexts))
        refs = list(references) if references else [None] * len(pairs)

        workers = max(1, min(int(self.max_workers or 1), len(pairs) or 1))
        if workers == 1:
            return [self._score_one(q, r, ctxs, refs[i], metric_names)
                    for i, (q, r, ctxs) in enumerate(pairs)]

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ragas") as pool:
            futures = [
                pool.submit(self._score_one, q, r, ctxs, refs[i], metric_names)
                for i, (q, r, ctxs) in enumerate(pairs)
            ]
            # Collected in submission order, not completion order.
            #
            # Every future is drained even after one raises. Re-raising on the
            # first failure without touching the rest leaves their exceptions
            # unretrieved, which Python reports as "exception was never
            # retrieved" - noisy at best during a 50-prompt run, and an error
            # under this repo's `filterwarnings = error`.
            rows: list[dict[str, float | None] | None] = []
            first_error: BaseException | None = None
            for future in futures:
                try:
                    rows.append(future.result())
                except BaseException as exc:  # noqa: BLE001 - re-raised below
                    rows.append(None)
                    if first_error is None:
                        first_error = exc
        if first_error is not None:
            raise first_error
        return rows  # type: ignore[return-value]

    def score_single(
        self,
        question: str,
        response: str,
        retrieved_contexts: list[str],
        reference: str | None = None,
        metric_names: list[str] | None = None,
    ) -> dict[str, float | None]:
        rows = self.score(
            [question],
            [response],
            [retrieved_contexts],
            [reference] if reference is not None else None,
            metric_names=metric_names,
        )
        return rows[0]


_default_scorer: RagasScorer | None = None


def get_scorer() -> RagasScorer:
    global _default_scorer
    if _default_scorer is None:
        _default_scorer = RagasScorer()
    return _default_scorer