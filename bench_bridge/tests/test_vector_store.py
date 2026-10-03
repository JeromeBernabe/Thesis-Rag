"""Tests for `src.vector_store`, specifically the detailed-query additions.

`VectorStore.__init__` opens a persistent ChromaDB directory and embeds through
Ollama, neither of which a unit test may touch. These tests therefore build the
instance with `object.__new__` and inject a fake collection plus a fake
embedder, which exercises the real `_flatten` / `query_*` logic - the part that
actually changed - without any I/O.
"""

from __future__ import annotations

import pytest

from bench_bridge.tests.conftest import FakeEmbedder
from src.vector_store import VectorStore


class FakeCollection:
    """Mimics the slice of the Chroma collection API the store uses."""

    def __init__(self, n: int = 5, include_distances: bool = True):
        self.n = n
        self.include_distances = include_distances
        self.last_call = None

    def count(self) -> int:
        return self.n

    def query(self, query_embeddings, n_results, include):
        self.last_call = {
            "query_embeddings": query_embeddings,
            "n_results": n_results,
            "include": include,
        }
        ids = [[f"doc-{i}" for i in range(n_results)]]
        docs = [[f"text {i}" for i in range(n_results)]]
        out = {"ids": ids, "documents": docs}
        if "distances" in include and self.include_distances:
            out["distances"] = [[1.0 - i * 0.05 for i in range(n_results)]]
        return out


@pytest.fixture
def store(monkeypatch):
    """A VectorStore with a fake collection, bypassing __init__'s I/O."""
    instance = object.__new__(VectorStore)
    instance.collection = FakeCollection(n=5)
    import src.vector_store as module

    monkeypatch.setattr(module, "get_embedder", lambda: FakeEmbedder())
    return instance


class TestFlatten:
    def test_unwraps_the_single_query_nesting(self):
        result = {
            "ids": [["a", "b"]],
            "documents": [["ta", "tb"]],
            "distances": [[0.1, 0.2]],
        }
        assert VectorStore._flatten(result) == {
            "ids": ["a", "b"],
            "documents": ["ta", "tb"],
            "distances": [0.1, 0.2],
        }

    def test_missing_lists_become_empty(self):
        """Chroma omits a key entirely when nothing matched."""
        assert VectorStore._flatten({}) == {
            "ids": [],
            "documents": [],
            "distances": [],
        }

    def test_explicit_none_becomes_empty(self):
        assert VectorStore._flatten(
            {"ids": None, "documents": None, "distances": None}
        ) == {"ids": [], "documents": [], "distances": []}

    def test_empty_nested_list_is_flat(self):
        assert VectorStore._flatten({"documents": [[]]})["documents"] == []


class TestQueryEmbeddingsDetailed:
    def test_returns_flat_documents_ids_distances(self, store):
        out = store.query_embeddings_detailed([0.0] * 8, k=3)
        assert out == {
            "ids": ["doc-0", "doc-1", "doc-2"],
            "documents": ["text 0", "text 1", "text 2"],
            "distances": [1.0, 0.95, 0.9],
        }

    def test_requests_documents_and_distances(self, store):
        store.query_embeddings_detailed([0.0] * 8, k=2)
        assert store.collection.last_call["include"] == ["documents", "distances"]

    def test_sends_a_single_query_embedding(self, store):
        store.query_embeddings_detailed([0.1, 0.2], k=1)
        assert store.collection.last_call["query_embeddings"] == [[0.1, 0.2]]

    def test_k_below_one_never_queries_chroma(self, store):
        assert store.query_embeddings_detailed([0.0] * 8, k=0) == {
            "ids": [],
            "documents": [],
            "distances": [],
        }
        assert store.collection.last_call is None

    def test_k_is_clamped_to_the_corpus_size(self, store):
        """Chroma errors if n_results exceeds the collection; k=99 on 5 docs must clamp."""
        out = store.query_embeddings_detailed([0.0] * 8, k=99)
        assert len(out["documents"]) == 5

    def test_k_is_clamped_to_at_least_one(self, store):
        store.collection.n = 0
        out = store.query_embeddings_detailed([0.0] * 8, k=3)
        assert store.collection.last_call["n_results"] == 1


class TestBackwardsCompatibility:
    def test_query_embeddings_still_returns_documents(self, store):
        """`query_embeddings` is the pre-existing API; the refactor must not change it."""
        assert store.query_embeddings([0.0] * 8, k=3) == ["text 0", "text 1", "text 2"]

    def test_query_text_embeds_once_then_reuses(self, store, monkeypatch):
        """`query` delegates rather than embedding twice."""
        embedder = FakeEmbedder()
        import src.vector_store as module

        monkeypatch.setattr(module, "get_embedder", lambda: embedder)
        store.query("what is VHDL?")
        assert embedder.calls == ["what is VHDL?"]

    def test_query_text_agrees_with_detailed(self, store):
        assert store.query("q", k=2) == store.query_detailed("q", k=2)["documents"]

    def test_query_text_k_below_one_returns_empty(self, store):
        assert store.query("q", k=0) == []
        assert store.query_detailed("q", k=0) == {
            "documents": [],
            "ids": [],
            "distances": [],
        }


class TestAddDocuments:
    def test_no_documents_is_a_no_op(self, store):
        store.add_documents([], [])
        assert store.collection.last_call is None