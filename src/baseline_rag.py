import time

from config import settings
from src.generator import get_generator
from src.result_shapes import canonical_answer
from src.vector_store import VectorStore


class BaselineRAG:
    """System A: fixed retrieval depth k, no learning."""

    def __init__(self, vector_store: VectorStore, k: int = settings.BASELINE_K, dataset: str = "math"):
        self.vector_store = vector_store
        self.k = k
        self.dataset = dataset
        self.generator = get_generator(dataset)

    def retrieve(self, question: str) -> list[str]:
        return self.vector_store.query(question, k=self.k)

    def retrieve_detailed(self, question: str) -> dict:
        """Same retrieval as :meth:`retrieve` but keeps ids and distances.

        Used by the desktop app's embedding-space visualisation, which needs
        document ids to line retrieved chunks up with their 3D coordinates.
        """
        return self.vector_store.query_detailed(question, k=self.k)

    def answer(self, question: str) -> dict:
        t0 = time.perf_counter()
        contexts = self.retrieve(question)
        retrieval_time_s = time.perf_counter() - t0

        result = canonical_answer(self.generator.answer(question, contexts))
        result["contexts"] = contexts
        result["k"] = self.k
        result["retrieval_time_s"] = retrieval_time_s
        return result

    def answer_detailed(self, question: str) -> dict:
        """`answer`, plus the ids and distances of the retrieved chunks.

        Retrieval is performed exactly once and shared with the answer. The
        desktop app needs the ids to place the retrieved chunks on the 3D
        embedding map and the distances to colour them by similarity; issuing a
        second `query` would double the cost of every prompt for no reason.
        """
        t0 = time.perf_counter()
        detailed = self.retrieve_detailed(question)
        retrieval_time_s = time.perf_counter() - t0

        contexts = detailed["documents"]
        result = canonical_answer(self.generator.answer(question, contexts))
        result["contexts"] = contexts
        result["k"] = self.k
        result["retrieved_ids"] = detailed["ids"]
        result["retrieved_distances"] = detailed["distances"]
        result["retrieval_time_s"] = retrieval_time_s
        return result