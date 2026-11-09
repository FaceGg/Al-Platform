"""服务化铸造特征列推导（_numeric_feature_columns）单测。

回归：全 NaN 数值列（dtype=float64）必须剔除——否则引擎
dropna(subset=全部特征列) 把全部行清零，报误导性的
「AutoML requires numeric features and at least ten rows」
（任务 866642c5 部署实测：spotinf/weldgun/tdressset 三列全空）。
"""
import os
import sys
import unittest

sys.path.insert(0, ".")

import pandas as pd

from app.api.agent_extras import _numeric_feature_columns


class TestNumericFeatureColumns(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "sch": ["a", "b", "c"],                # 字符串列 → 剔除
            "wld1c": [1.0, 2.0, 3.0],              # 正常数值 → 保留
            "spotinf": [float("nan")] * 3,         # 全 NaN 数值列 → 剔除
            "partial": [1.0, None, 3.0],           # 部分缺失数值列 → 保留
            "fault": [0, 1, 0],                    # 目标列 → 剔除
        })

    def test_drops_all_nan_numeric_column(self):
        out = _numeric_feature_columns(self.frame, "fault")
        self.assertNotIn("spotinf", out)
        self.assertIn("wld1c", out)
        self.assertIn("partial", out)

    def test_drops_target_and_non_numeric(self):
        out = _numeric_feature_columns(self.frame, "fault")
        self.assertNotIn("fault", out)
        self.assertNotIn("sch", out)

    def test_drop_set_respected(self):
        out = _numeric_feature_columns(self.frame, "fault", drop_set={"wld1c"})
        self.assertNotIn("wld1c", out)
        self.assertIn("partial", out)

    def test_empty_input_list_when_all_features_nan(self):
        frame = pd.DataFrame({
            "fault": [0, 1],
            "a": [float("nan")] * 2,
            "b": [float("nan")] * 2,
        })
        self.assertEqual(_numeric_feature_columns(frame, "fault"), [])


if __name__ == "__main__":
    unittest.main()
