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

    @staticmethod
    def _flatten(result: dict) -> dict:
        """Reduce a single-query Chroma result to flat lists.

        Chroma returns nested lists (one entry per query embedding); the project
        only ever issues single-query lookups, so the first row is unwrapped.
        Missing lists come back empty rather than ``None`` so callers never have
        to re-check the shape.
        """
        docs = result.get("documents") or []
        ids = result.get("ids") or []
        dists = result.get("distances") or []
        return {
            "documents": [str(d) for d in (docs[0] if docs else [])],
            "ids": [str(i) for i in (ids[0] if ids else [])],
            "distances": [float(x) for x in (dists[0] if dists else [])],
        }

    def query(self, query_text: str, k: int = settings.BASELINE_K) -> list[str]:
        if k < 1:
            return []
        embedder = get_embedder()
        query_embedding = embedder.embed_query(query_text)
        return self.query_embeddings(query_embedding, k)

    def query_embeddings(self, query_embedding: list[float], k: int) -> list[str]:
        return self.query_embeddings_detailed(query_embedding, k)["documents"]

    def query_detailed(self, query_text: str, k: int = settings.BASELINE_K) -> dict:
        """Text query returning documents plus ids and cosine distances.

        Additive variant of :meth:`query`; the existing methods keep their
        original signatures and behaviour. The desktop app needs ids to match
        retrieved chunks against their precomputed 3D coordinates and
        distances to colour the embedding-space view.
        """
        if k < 1:
            return {"documents": [], "ids": [], "distances": []}
        embedder = get_embedder()
        query_embedding = embedder.embed_query(query_text)
        return self.query_embeddings_detailed(query_embedding, k)

    def query_embeddings_detailed(self, query_embedding: list[float], k: int) -> dict:
        """Embedding query returning documents plus ids and cosine distances."""
        if k < 1:
            return {"documents": [], "ids": [], "distances": []}
        k = min(k, max(1, self.count))
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
            include=["documents", "distances"],
        )
        return self._flatten(result)