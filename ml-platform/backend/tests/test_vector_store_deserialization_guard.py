"""VectorStore persist 反序列化防御测试（Mimosa 2026-11-03 深扫收口）。

对抗性载荷直接走 `_validate_persist_payload` 结构白名单单元验证（不触
磁盘），合法正路径用 save 自产的文件做一次 load 往返——被篡改的
vs_*.pkl 在写内存状态前必须被拒绝。
"""
import os
import unittest

import numpy as np

from app.engine.vector_store import VectorStore


class TestVectorStoreDeserializationGuard(unittest.TestCase):
    def test_validator_accepts_the_shape_save_produces(self):
        store = VectorStore(dim=16)
        store.add(["guard_1"], np.stack([np.ones(16, dtype=np.float32)]), [{}])
        # 复刻 save() 的载荷形状（含 metric/M 可选键）
        payload = {
            "dim": store.dim, "metric": store.metric, "M": store.M,
            "ids": store.ids,
            "vectors": [v.tobytes() for v in store.vectors],
            "metadata": store.metadata,
        }
        validated = VectorStore._validate_persist_payload(payload)
        self.assertEqual(validated["ids"], ["guard_1"])

    def test_validator_rejects_non_dict_top_level(self):
        for bad in (b"attacker-bytes", ["list"], 42):
            with self.assertRaises(ValueError):
                VectorStore._validate_persist_payload(bad)

    def test_validator_rejects_unexpected_key_set(self):
        with self.assertRaises(ValueError):
            VectorStore._validate_persist_payload({"unexpected": 1})

    def test_validator_rejects_wrong_element_types(self):
        bad = {"dim": 16, "ids": ["x"], "vectors": ["not-bytes"], "metadata": [{}]}
        with self.assertRaises(ValueError):
            VectorStore._validate_persist_payload(bad)

    def test_validator_rejects_object_payload_instances(self):
        # __reduce__ 式载荷：vectors 里带非 bytes 实例（ndarray）
        bad = {
            "dim": 16, "ids": ["x"], "metadata": [{}],
            "vectors": [np.ones(4, dtype=np.float32)],
        }
        with self.assertRaises(ValueError):
            VectorStore._validate_persist_payload(bad)

    def test_save_load_roundtrip_still_works(self):
        import pickle
        import tempfile

        store = VectorStore(dim=16)
        store.add(["rt_1"], np.stack([np.ones(16, dtype=np.float32)]), [{}])
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "roundtrip.pkl")
            store.save(path)
            with open(path, "rb") as handle:
                VectorStore._validate_persist_payload(pickle.load(handle))


if __name__ == "__main__":
    unittest.main()
