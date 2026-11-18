"""无监督训练器缺席族回归（2026-11-18 任务 193923b7 连续崩溃）。

白名单显式点名 autoencoder 而当前环境无 torch 时，family.build 抛
AlgorithmUnavailable——此前直接崩整任务（resume 再拉起同处再崩，连续
四次）。修复后：缺席族跳过记 unavailable、其余族继续；全部缺席显式报错。
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, ".")

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import pandas as pd  # noqa: E402

from app.services.agent.anomaly_trainer import anomaly_trainer  # noqa: E402
from app.services.automl_catalog import AlgorithmUnavailable  # noqa: E402


def _frame(rows: int = 240) -> pd.DataFrame:
    return pd.DataFrame({
        "f1": [float(i) for i in range(rows)],
        "f2": [float(i) * 0.5 + 1.0 for i in range(rows)],
    })


class TestAnomalyTrainerUnavailable(unittest.TestCase):
    def _hints(self, whitelist: list[str]) -> dict:
        return {
            "task_type": "anomaly",
            "algorithm_whitelist": whitelist,
            "contamination": 0.05,
            "full_data": True,
        }

    def test_unavailable_family_skipped_others_continue(self):
        good_family = SimpleNamespace(id="iforest")
        bad_family = SimpleNamespace(id="autoencoder")

        def build(task, params):
            # 只有 good_family 的 build 会被冠军复用调用；bad 在循环内直接抛
            from sklearn.ensemble import IsolationForest
            from sklearn.preprocessing import StandardScaler
            from sklearn.pipeline import Pipeline

            return Pipeline([
                ("scaler", StandardScaler()),
                ("detector", IsolationForest(n_estimators=10, random_state=0)),
            ])

        good_family.build = build
        bad_family.build = lambda task, params: (_ for _ in ()).throw(
            AlgorithmUnavailable("autoencoder")
        )
        with patch(
            "app.services.agent.anomaly_trainer.resolve_algorithm_families",
            return_value=[bad_family, good_family],
        ):
            result = anomaly_trainer(_frame(), None, self._hints(["iforest", "autoencoder"]))
        # 冠军由可用族产出；缺席族记录在 topk/scored 之外不参与排名
        self.assertIn("metrics", result)
        self.assertTrue(result["metrics"].get("synthetic_auc") is not None)
        self.assertTrue(all(
            item.get("synthetic_auc") is not None for item in result["topk_metrics"]
        ))

    def test_all_families_unavailable_raises_explicitly(self):
        bad_family = SimpleNamespace(
            id="autoencoder",
            build=lambda task, params: (_ for _ in ()).throw(
                AlgorithmUnavailable("autoencoder")
            ),
        )
        with patch(
            "app.services.agent.anomaly_trainer.resolve_algorithm_families",
            return_value=[bad_family],
        ):
            with self.assertRaises(RuntimeError) as ctx:
                anomaly_trainer(_frame(), None, self._hints(["autoencoder"]))
        self.assertIn("无可用异常检测算法族", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
