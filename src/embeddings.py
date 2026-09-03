from langchain_ollama import OllamaEmbeddings

from config import settings


class Embedder:
    def __init__(self, model: str = settings.EMBED_MODEL, base_url: str = settings.OLLAMA_BASE_URL):
        self.model = model
        self._embeddings = OllamaEmbeddings(model=model, base_url=base_url)

    @property
    def dim(self) -> int:
        return settings.EMBEDDING_DIM

    def embed_query(self, text: str) -> list[float]:
        vec = self._embeddings.embed_query(text)
        return list(vec)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [list(v) for v in self._embeddings.embed_documents(texts)]


_default_embedder: Embedder | None = None


def get_embedder() -> Embedder:
    global _default_embedder
    if _default_embedder is None:
        _default_embedder = Embedder()
    return _default_embedder