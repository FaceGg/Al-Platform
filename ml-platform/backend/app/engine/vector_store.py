"""
High-performance vector store with HNSW-like ANN indexing,
metadata filtering, and hybrid (vector + keyword) retrieval.
"""
import numpy as np
import threading
from typing import Optional


class VectorStore:
    """High-performance vector store — HNSW-like index, metadata filtering, hybrid retrieval."""

    def __init__(self, dim: int = None, metric: str = "cosine", M: int = 16):
        self.dim = dim
        self.metric = metric
        self.M = M  # HNSW connection count
        self.vectors: list[np.ndarray] = []
        self.ids: list[str] = []
        self.metadata: list[dict] = []
        self._graph: dict[int, list[int]] = {}  # adjacency list (simplified HNSW)
        self._lock = threading.Lock()

    def add(self, ids: list[str], vectors: np.ndarray, metadata: list[dict] = None):
        """Batch-add vectors with incremental write support."""
        with self._lock:
            if self.dim is None:
                self.dim = vectors.shape[1]
            vectors = vectors.astype(np.float32)
            if self.metric == "cosine":
                norms = np.linalg.norm(vectors, axis=1, keepdims=True)
                norms[norms == 0] = 1e-10
                vectors = vectors / norms
            for i, vid in enumerate(ids):
                idx = len(self.vectors)
                self.ids.append(vid)
                self.vectors.append(vectors[i])
                self.metadata.append(metadata[i] if metadata else {})
                self._add_to_graph(idx)

    def _add_to_graph(self, idx: int):
        """Simplified HNSW graph construction."""
        self._graph[idx] = []
        if idx > 0:
            vec = self.vectors[idx]
            similarities = []
            for j in range(min(idx, 100)):
                sim = np.dot(vec, self.vectors[j])
                similarities.append((sim, j))
            similarities.sort(reverse=True)
            for sim, j in similarities[:self.M]:
                self._graph[idx].append(j)
                self._graph.setdefault(j, []).append(idx)

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
        metadata_filter: dict = None,
        keyword: str = None,
    ) -> list[dict]:
        """Hybrid retrieval: vector similarity + metadata filter + keyword matching."""
        with self._lock:
            query = query_vector.astype(np.float32).flatten()
            if self.metric == "cosine":
                query = query / (np.linalg.norm(query) or 1e-10)
            if not self.vectors:
                return []
            stack = np.stack(self.vectors)
            scores = np.dot(stack, query)
            if metadata_filter:
                for i, meta in enumerate(self.metadata):
                    if not self._match_filter(meta, metadata_filter):
                        scores[i] = -1e9
            if keyword:
                kw = keyword.lower()
                for i, meta in enumerate(self.metadata):
                    if scores[i] > -1e9:
                        text = str(meta.get("content", "")) + str(meta.get("name", ""))
                        if kw not in text.lower():
                            scores[i] *= 0.3  # downgrade, don't exclude
            top_indices = np.argsort(scores)[-top_k:][::-1]
            return [
                {"id": self.ids[i], "score": float(scores[i]), "metadata": self.metadata[i]}
                for i in top_indices
                if scores[i] > -1e8
            ]

    def _match_filter(self, meta: dict, filt: dict) -> bool:
        for k, v in filt.items():
            if k not in meta:
                return False
            if isinstance(v, list):
                if meta[k] not in v:
                    return False
            elif meta[k] != v:
                return False
        return True

    def update(self, id: str, vector: np.ndarray = None, metadata: dict = None):
        with self._lock:
            for i, vid in enumerate(self.ids):
                if vid == id:
                    if vector is not None:
                        vec = vector.astype(np.float32).flatten()
                        if self.metric == "cosine":
                            vec = vec / (np.linalg.norm(vec) or 1e-10)
                        self.vectors[i] = vec
                    if metadata is not None:
                        self.metadata[i] = metadata
                    return
            raise ValueError(f"ID not found: {id}")

    def delete(self, id: str):
        with self._lock:
            for i, vid in enumerate(self.ids):
                if vid == id:
                    self.ids.pop(i)
                    self.vectors.pop(i)
                    self.metadata.pop(i)
                    self._graph.pop(i, None)
                    return
            raise ValueError(f"ID not found: {id}")

    def delete_many(self, ids: list[str]):
        with self._lock:
            ids_set = set(ids)
            indices = [i for i, vid in enumerate(self.ids) if vid not in ids_set]
            self.ids = [self.ids[i] for i in indices]
            self.vectors = [self.vectors[i] for i in indices]
            self.metadata = [self.metadata[i] for i in indices]
            self._graph = {}

    def get_stats(self) -> dict:
        return {
            "total_vectors": len(self.vectors),
            "dimension": self.dim,
            "metric": self.metric,
            "memory_mb": round(
                sum(v.nbytes for v in self.vectors) / 1024 / 1024, 2
            ),
        }


# Global singleton
_vector_store_instance: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = VectorStore(dim=768, metric="cosine")
    return _vector_store_instance
