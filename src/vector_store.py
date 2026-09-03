import chromadb
from chromadb.config import Settings as ChromaSettings

from config import settings
from src.embeddings import get_embedder


class VectorStore:
    def __init__(
        self,
        collection_name: str = settings.COLLECTION_NAME,
        persist_dir: str = str(settings.CHROMA_DIR),
        reset: bool = False,
    ):
        self._client = chromadb.PersistentClient(
            path=persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        if reset:
            try:
                self._client.delete_collection(collection_name)
            except Exception:
                pass
        self.collection = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def count(self) -> int:
        return self.collection.count()

    def add_documents(self, ids: list[str], documents: list[str], batch_size: int = 128) -> None:
        if not documents:
            return
        embedder = get_embedder()
        for start in range(0, len(documents), batch_size):
            end = min(start + batch_size, len(documents))
            batch_ids = ids[start:end]
            batch_docs = documents[start:end]
            embeddings = embedder.embed_documents(batch_docs)
            self.collection.add(
                ids=batch_ids, documents=batch_docs, embeddings=embeddings
            )

    def query(self, query_text: str, k: int = settings.BASELINE_K) -> list[str]:
        if k < 1:
            return []
        embedder = get_embedder()
        query_embedding = embedder.embed_query(query_text)
        k = min(k, max(1, self.count))
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "distances"],
        )
        docs = result["documents"][0] if result["documents"] else []
        return [str(d) for d in docs]

    def query_embeddings(self, query_embedding: list[float], k: int) -> list[str]:
        if k < 1:
            return []
        k = min(k, max(1, self.count))
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "distances"],
        )
        docs = result["documents"][0] if result["documents"] else []
        return [str(d) for d in docs]