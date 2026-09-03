from config import settings
from src.generator import get_generator
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

    def answer(self, question: str) -> dict:
        contexts = self.retrieve(question)
        response = self.generator.answer(question, contexts)
        return {"answer": response, "contexts": contexts, "k": self.k}