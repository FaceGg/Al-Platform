"""Vector Store unit and integration tests."""
import sys, os, unittest
import numpy as np
sys.path.insert(0, ".")

from app.engine.vector_store import VectorStore


class TestVectorStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = VectorStore(dim=128, metric="cosine")
        cls.test_vecs = []
        for i in range(10):
            vec = np.random.randn(128).astype(np.float32)
            vec = vec / (np.linalg.norm(vec) + 1e-8)
            cls.test_vecs.append(vec)
        cls.store.add(
            [f"id_{i}" for i in range(10)],
            np.stack(cls.test_vecs),
            [{"category": "test", "index": i} for i in range(10)]
        )

    def test_01_add_and_count(self):
        self.assertEqual(len(self.store.ids), 10)

    def test_02_search(self):
        query = self.test_vecs[0].copy()
        results = self.store.search(query, top_k=3)
        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "id_0")

    def test_03_search_metadata_filter(self):
        query = self.test_vecs[0].copy()
        results = self.store.search(query, top_k=5, metadata_filter={"category": "test"})
        self.assertGreaterEqual(len(results), 1)

    def test_04_delete(self):
        store = VectorStore(dim=64)
        v = np.stack([np.ones(64, dtype=np.float32)])
        store.add(["del_test"], v, [{}])
        store.delete("del_test")
        results = store.search(np.ones(64, dtype=np.float32), top_k=1)
        self.assertTrue(len(results) == 0 or results[0]["id"] != "del_test")

    def test_05_batch_add(self):
        store = VectorStore(dim=16)
        vecs = np.stack([np.random.randn(16).astype(np.float32) for _ in range(5)])
        store.add([f"batch_{i}" for i in range(5)], vecs, [{"batch": i} for i in range(5)])
        self.assertEqual(len(store.ids), 5)

    def test_06_get_nonexistent(self):
        self.assertIsNone(self.store.get("nonexistent_xyz"))

    def test_07_save_and_load(self):
        import tempfile, os
        store = VectorStore(dim=16)
        v = np.stack([np.ones(16, dtype=np.float32)])
        store.add(["sv_1"], v, [{}])
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pkl") as f:
            path = f.name
        try:
            store.save(path)
            store2 = VectorStore(dim=16)
            store2.load(path)
            self.assertEqual(len(store2.ids), 1)
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_08_search_empty(self):
        store = VectorStore(dim=64)
        results = store.search(np.ones(64, dtype=np.float32), top_k=5)
        self.assertEqual(len(results), 0)

    def test_09_get_stats(self):
        stats = self.store.get_stats()
        self.assertIn("total_vectors", stats)
        self.assertIn("dimension", stats)

    def test_10_batch_search(self):
        queries = np.stack([self.test_vecs[0], self.test_vecs[1]])
        results = self.store.batch_search(queries, top_k=3)
        self.assertEqual(len(results), 2)

    def test_11_range_search(self):
        query = self.test_vecs[0].copy()
        results = self.store.range_search(query, threshold=0.5)
        self.assertIsInstance(results, list)


if __name__ == "__main__":
    unittest.main()
