"""轻量训练器 accuracy 口径对齐回归（点焊/拧紧双域实测踩坑）。

合同：accuracy 与 recall/precision/f1 同一布尔口径（1=少数类）。此前
accuracy_score(y_test, preds) 用原始 LabelEncoder 编码，当少数类编码为
0、多数类为 1（如拧紧 DECIDE："0"=不合格 20.3% 少数、"1"=合格 79.7%
多数）时 0/1 语义相反，accuracy 恒等于 1−真实值（实测 0.0046，
而 f1/precision/recall 均 0.98+——一组数学上不可能并存的指标）。
"""

import numpy as np
import pandas as pd
import unittest

from app.services.agent.executor import lightweight_trainer


class TestLightTrainerAccuracyAlignment(unittest.TestCase):
    def _make_frame(self, n_majority: int, n_minority: int) -> pd.DataFrame:
        # 两个强判别特征：少数类(1)取低值域、多数类(0)取高值域，模型可分
        rng = np.random.RandomState(7)
        rows = n_majority + n_minority
        frame = pd.DataFrame({
            "feat_a": np.concatenate([rng.normal(10, 1, n_majority), rng.normal(-10, 1, n_minority)]),
            "feat_b": np.concatenate([rng.normal(5, 1, n_majority), rng.normal(-5, 1, n_minority)]),
            "target": [1] * n_majority + [0] * n_minority,
        })
        return frame.sample(frac=1.0, random_state=7).reset_index(drop=True)

    def test_accuracy_aligns_with_boolean_metrics_when_minority_encoded_zero(self):
        # 少数类编码 0（"0"=不合格占 20.3%）、多数类编码 1（"1"=合格 79.7%）——
        # 修复前该形态下 accuracy 恒为 1−真实值
        frame = self._make_frame(n_majority=600, n_minority=200)
        result = lightweight_trainer(frame, frame["target"], hints={})
        metrics = result["metrics"]
        self.assertGreater(metrics["accuracy"], 0.9)
        self.assertGreater(metrics["f1"], 0.9)
        # 五指标同一量级（同一混淆矩阵推导得出）
        spread = max(metrics.values()) - min(
            v for k, v in metrics.items() if k != "roc_auc"
        )
        self.assertLess(spread, 0.15)

    def test_accuracy_aligns_when_minority_encoded_one(self):
        # 反向形态（少数类编码 1）同样正确
        frame = self._make_frame(n_majority=600, n_minority=200)
        frame["target"] = 1 - frame["target"]
        result = lightweight_trainer(frame, frame["target"], hints={})
        self.assertGreater(result["metrics"]["accuracy"], 0.9)


if __name__ == "__main__":
    unittest.main()
