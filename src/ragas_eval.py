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
import time

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
        self._embeddings = OllamaEmbeddings(model=embed_model, base_url=base_url)
        # Sequential processing by construction (max_workers kept for parity).
        self.max_workers = max_workers

    # ------------------------------------------------------------------ infra
    def _complete(self, prompt: str, max_tokens: int = 400) -> str:
        last_error = None
        for attempt in range(self.max_retries + 1):
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
                resp = requests.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                    timeout=self.timeout,
                )
                resp.raise_for_status()
                return resp.json().get("response", "")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning("Judge request attempt %d failed: %s", attempt + 1, exc)
                if attempt >= self.max_retries:
                    raise
                time.sleep(2.0 * (attempt + 1))
        raise RuntimeError(f"unreachable: {last_error}")

    def _complete_json(self, prompt: str, max_tokens: int = 400) -> dict | None:
        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                text = self._complete(prompt, max_tokens=max_tokens)
                blob = _extract_json(text)
                if blob is None:
                    raise ValueError("no JSON object found in response")
                data = json.loads(blob)
                if isinstance(data, dict):
                    return data
                raise ValueError("JSON is not an object")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.debug("JSON completion attempt %d failed: %s", attempt + 1, exc)
        logger.warning("Judge returned unusable output after %d attempts: %s", self.max_retries + 1, last_error)
        return None

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
        result = self._as_list(self._complete_json(prompt, max_tokens=600), "statements")
        if not result:
            fallback = (
                "List every distinct factual claim in the following text as a separate item. "
                "Output as a JSON list of strings.\n"
                f"Text:\n{answer}\n"
                f'{JSON_HEADER}\n{{"statements": ["1. ...", "2. ..."]}}'
            )
            result = self._as_list(self._complete_json(fallback, max_tokens=600), "statements")
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
        data = self._complete_json(prompt, max_tokens=800)
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
        return self._as_list(self._complete_json(prompt), "questions")

    def _score_answer_relevancy(self, question: str, response: str) -> float | None:
        gen_questions = self._generated_questions(response, self.strictness)
        if not gen_questions:
            logger.warning("AnswerRelevancy: no questions generated; score = 0")
            return 0.0
        try:
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
        result = self._as_list(self._complete_json(prompt, max_tokens=600), "statements")
        if not result:
            fallback = (
                "List every distinct factual claim in the following text as a separate item. "
                "Output as a JSON list of strings.\n"
                f"Text:\n{reference}\n"
                f'{JSON_HEADER}\n{{"statements": ["1. ...", "2. ..."]}}'
            )
            result = self._as_list(self._complete_json(fallback, max_tokens=600), "statements")
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
        data = self._complete_json(prompt, max_tokens=800)
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
        return row

    def score(
        self,
        questions: list[str],
        responses: list[str],
        retrieved_contexts: list[list[str]],
        references: list[str] | None = None,
        metric_names: list[str] | None = None,
    ) -> list[dict[str, float | None]]:
        metric_names = metric_names or FULL_METRICS
        rows = []
        for i, (q, r, ctxs) in enumerate(zip(questions, responses, retrieved_contexts)):
            ref = references[i] if references else None
            rows.append(self._score_one(q, r, ctxs, ref, metric_names))
        return rows

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