"""Shared fixtures and test doubles.

Everything in this suite is hermetic: no ChromaDB, no Ollama, no network, and
no GPU work. The RAG wrappers are constructed with injected doubles, so the
tests exercise the real `src.baseline_rag` / `src.dqn_rag` / `src.vector_store`
logic without the 2.4 GB corpus or the 80-190 s judge round trip.

`torch` *is* imported, because `config/settings.py` resolves `DEVICE` at import
time - that costs ~15 s on first import and is cached by pytest for the rest of
the session. Nothing here allocates a tensor on that device.

`src.dqn_agent.DQNAgent` cannot be injected through the wrapper constructor
alone (it is built internally when `agent=None`, which would construct a
`QNetwork` on CUDA), so `install_dqn_stub()` replaces the class with a fake
having the same surface. Tests that care about real DQN optimisation belong in
the torch-dependent integration suite, not here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# --------------------------------------------------------------------- doubles


class FakeEmbedder:
    """Deterministic stand-in for `src.embeddings.OllamaEmbeddings`.

    Produces a fixed-dimension vector derived from a hash of the text so the same
    question always yields the same "embedding" - needed for the PCA and
    retrieval assertions to be reproducible.
    """

    def __init__(self, dim: int = 8, calls: list[str] | None = None):
        self.dim = dim
        self.calls = calls if calls is not None else []

    def embed_query(self, text: str) -> list[float]:
        self.calls.append(text)
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        import hashlib

        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[i] / 255.0 for i in range(self.dim)]


class FakeVectorStore:
    """In-memory stand-in for `src.vector_store.VectorStore`."""

    def __init__(self, docs_per_query: int = 4):
        self.docs_per_query = docs_per_query
        self.queries: list[tuple[str, int]] = []

    def _hits(self, question: str, k: int) -> list[tuple[str, str, float]]:
        return [
            (f"doc-{question[:4]}-{i}", f"chunk {i} for {question}", 1.0 - i * 0.1)
            for i in range(min(k, self.docs_per_query))
        ]

    def query(self, question: str, k: int = 3) -> list[str]:
        self.queries.append((question, k))
        return [doc for _, doc, _ in self._hits(question, k)]

    def query_detailed(self, question: str, k: int = 3) -> dict:
        self.queries.append((question, k))
        hits = self._hits(question, k)
        # Mirrors VectorStore._flatten exactly - see test_vector_store.py, which
        # asserts the real implementation produces this same shape.
        return {
            "ids": [i for i, _, _ in hits],
            "documents": [d for _, d, _ in hits],
            "distances": [dist for _, _, dist in hits],
        }

    def query_embeddings(self, embedding, k: int = 3) -> list[str]:
        self.queries.append(("<embedding>", k))
        return [f"ctx-{i}" for i in range(min(k, self.docs_per_query))]

    def query_embeddings_detailed(self, embedding, k: int = 3) -> dict:
        self.queries.append(("<embedding>", k))
        n = min(k, self.docs_per_query)
        return {
            "ids": [f"doc-emb-{i}" for i in range(n)],
            "documents": [f"ctx-{i}" for i in range(n)],
            "distances": [1.0 - i * 0.1 for i in range(n)],
        }


class FakeGenerator:
    """Returns the current dict shape that `src.generator.Generator` produces."""

    def __init__(self, answer: str = "generated answer"):
        self.answer_text = answer
        self.calls: list[tuple[str, list[str]]] = []

    def answer(self, question: str, contexts: list[str]) -> dict:
        self.calls.append((question, contexts))
        prompt_tokens = sum(len(text.split()) for text in contexts) + len(
            question.split()
        )
        completion_tokens = len(self.answer_text.split())
        return {
            "answer": self.answer_text,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "generation_time_s": 0.5,
        }


class FakeScorer:
    """Stand-in for `RagasScorer`; returns fixed metrics plus judge metadata."""

    def __init__(
        self,
        faithfulness: float | None = 0.8,
        answer_relevancy: float | None = 0.9,
        context_recall: float | None = None,
    ):
        self.faithfulness = faithfulness
        self.answer_relevancy = answer_relevancy
        self.context_recall = context_recall
        self.calls: list[dict] = []

    def score_single(
        self,
        question: str,
        response: str,
        retrieved_contexts: list[str],
        reference: str | None = None,
        metric_names: list[str] | None = None,
    ) -> dict:
        self.calls.append(
            {
                "question": question,
                "response": response,
                "retrieved_contexts": retrieved_contexts,
                "reference": reference,
                "metric_names": metric_names,
            }
        )
        return {
            "faithfulness": self.faithfulness,
            "answer_relevancy": self.answer_relevancy,
            "context_recall": self.context_recall,
            "judge_prompt_tokens": 11,
            "judge_completion_tokens": 7,
            "judge_time_s": 1.25,
        }


class FakeReplayBuffer:
    """Minimal stand-in: `src.dqn_rag` logs `len(buffer)` when a train step is skipped."""

    def __init__(self, length: int = 3):
        self._length = length

    def __len__(self) -> int:
        return self._length


class FakeAgent:
    """Double for `DQNAgent` with the same public surface."""

    def __init__(self, action: int = 2, q_values: list[float] | None = None):
        self.action = action
        self.q_values_values = q_values or [0.1, 0.2, 0.5, 0.3, 0.05]
        self.epsilon = 1.0
        self.batch_size = 8
        self.replay_buffer = FakeReplayBuffer(3)
        self.stored: list[tuple] = []
        self.trained = 0
        self.decayed = 0
        self.saved: list = []
        self.loaded: list = []

    def select_action(self, state) -> int:
        return self.action

    def greedy_action(self, state) -> int:
        return self.action

    def q_values(self, state) -> list[float]:
        return list(self.q_values_values)

    def store(self, state, action, reward) -> None:
        self.stored.append((state, action, reward))

    def train_step(self) -> float | None:
        self.trained += 1
        return 0.42

    def decay_epsilon(self) -> None:
        self.decayed += 1

    def save(self, path=None) -> None:
        self.saved.append(path)

    def load(self, path=None) -> None:
        self.loaded.append(path)


# --------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def _dqn_stub(monkeypatch):
    """Swap DQNAgent for FakeAgent so no torch import happens.

    Autouse because *every* test module transitively imports
    `src.baseline_rag` -> `config.settings` -> torch, or `src.dqn_rag` ->
    `src.dqn_agent` -> torch. Installing the stub once keeps the whole suite
    fast and CPU-only.
    """
    import src.dqn_rag as dqn_rag_module

    monkeypatch.setattr(dqn_rag_module, "DQNAgent", FakeAgent, raising=False)
    yield


@pytest.fixture
def vector_store() -> FakeVectorStore:
    return FakeVectorStore()


@pytest.fixture
def generator(monkeypatch) -> FakeGenerator:
    fake = FakeGenerator()
    import src.baseline_rag as baseline_rag_module
    import src.dqn_rag as dqn_rag_module

    monkeypatch.setattr(baseline_rag_module, "get_generator", lambda *_: fake)
    monkeypatch.setattr(dqn_rag_module, "get_generator", lambda *_: fake)
    return fake


@pytest.fixture
def embedder(monkeypatch) -> FakeEmbedder:
    fake = FakeEmbedder()
    import src.dqn_rag as dqn_rag_module

    monkeypatch.setattr(dqn_rag_module, "get_embedder", lambda: fake, raising=False)
    return fake


@pytest.fixture
def scorer() -> FakeScorer:
    return FakeScorer()

