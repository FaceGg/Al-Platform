"""
High-performance vector store with HNSW-like ANN indexing,
metadata filtering, hybrid retrieval, persistence, and range queries.
"""
import numpy as np
import threading
import pickle
import os
from typing import Optional


class VectorStore:
    """HNSW-like vector store with persistence, metadata filtering, hybrid retrieval."""

    def __init__(self, dim: int = None, metric: str = "cosine", M: int = 16):
        self.dim = dim
        self.metric = metric
        self.M = M
        self.vectors: list[np.ndarray] = []
        self.ids: list[str] = []
        self.metadata: list[dict] = []
        self._graph: dict[int, list[int]] = {}
        self._lock = threading.Lock()

    # ── Core CRUD ──

    def add(self, ids: list[str], vectors: np.ndarray, metadata: list[dict] = None):
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
        self._graph[idx] = []
        if idx > 0:
            vec = self.vectors[idx]
            similarities = [(np.dot(vec, self.vectors[j]), j) for j in range(min(idx, 100))]
            similarities.sort(reverse=True)
            for sim, j in similarities[:self.M]:
                self._graph[idx].append(j)
                self._graph.setdefault(j, []).append(idx)

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
                    self.ids.pop(i); self.vectors.pop(i); self.metadata.pop(i)
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

    def get(self, id: str) -> Optional[dict]:
        with self._lock:
            for i, vid in enumerate(self.ids):
                if vid == id:
                    return {"id": vid, "vector": self.vectors[i].tolist(), "metadata": self.metadata[i]}
        return None

    def count(self, metadata_filter: dict = None) -> int:
        with self._lock:
            if not metadata_filter:
                return len(self.vectors)
            return sum(1 for m in self.metadata if self._match_filter(m, metadata_filter))

    # ── Search ──

    def search(self, query_vector: np.ndarray, top_k: int = 5,
               metadata_filter: dict = None, keyword: str = None) -> list[dict]:
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
                            scores[i] *= 0.3
            top = np.argsort(scores)[-top_k:][::-1]
            return [{"id": self.ids[i], "score": float(scores[i]), "metadata": self.metadata[i]}
                    for i in top if scores[i] > -1e8]

    def range_search(self, query_vector: np.ndarray, threshold: float = 0.7,
                     metadata_filter: dict = None) -> list[dict]:
        """Range query: return all vectors above similarity threshold."""
        with self._lock:
            query = query_vector.astype(np.float32).flatten()
            if self.metric == "cosine":
                query = query / (np.linalg.norm(query) or 1e-10)
            if not self.vectors:
                return []
            stack = np.stack(self.vectors)
            scores = np.dot(stack, query)
            results = []
            for i, score in enumerate(scores):
                if score < threshold:
                    continue
                if metadata_filter and not self._match_filter(self.metadata[i], metadata_filter):
                    continue
                results.append({"id": self.ids[i], "score": float(score), "metadata": self.metadata[i]})
            results.sort(key=lambda x: x["score"], reverse=True)
            return results

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

    # ── Persistence ──

    def save(self, path: str):
        with self._lock:
            data = {
                "dim": self.dim, "metric": self.metric, "M": self.M,
                "ids": self.ids,
                "vectors": [v.tobytes() for v in self.vectors],
                "metadata": self.metadata,
            }
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as f:
                pickle.dump(data, f)

    def load(self, path: str):
        with self._lock:
            if not os.path.exists(path):
                return False
            with open(path, "rb") as f:
                data = pickle.load(f)
            self.dim = data["dim"]
            self.metric = data.get("metric", "cosine")
            self.M = data.get("M", 16)
            self.ids = data["ids"]
            self.vectors = [np.frombuffer(b, dtype=np.float32) for b in data["vectors"]]
            self.metadata = data["metadata"]
            self._graph = {}
            for i in range(len(self.vectors)):
                self._add_to_graph(i)
            return True

    def export_kb(self, kb_id: str, path: str):
        """Export all vectors for a specific knowledge base."""
        with self._lock:
            indices = [i for i, m in enumerate(self.metadata) if m.get("kb_id") == kb_id]
            data = {
                "kb_id": kb_id, "count": len(indices),
                "ids": [self.ids[i] for i in indices],
                "vectors": [self.vectors[i].tobytes() for i in indices],
                "metadata": [self.metadata[i] for i in indices],
            }
            with open(path, "wb") as f:
                pickle.dump(data, f)

    # ── Stats ──

    def get_stats(self) -> dict:
        with self._lock:
            memory = sum(v.nbytes for v in self.vectors) / 1024 / 1024
            return {"total_vectors": len(self.vectors), "dimension": self.dim,
                    "metric": self.metric, "memory_mb": round(memory, 2),
                    "kb_count": len(set(m.get("kb_id","") for m in self.metadata))}


# Global singleton
_vector_store_instance: Optional[VectorStore] = None

def get_vector_store() -> VectorStore:
    global _vector_store_instance
    if _vector_store_instance is None:
        _vector_store_instance = VectorStore(dim=768, metric="cosine")
    return _vector_store_instance
