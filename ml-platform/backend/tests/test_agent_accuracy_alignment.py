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


class TestLightTrainerEnsemble(unittest.TestCase):
    """集成学习（多模型加权投票）：guidance.modeling.ensemble 经 hints 传入。

    合同：启用后产出 ensemble 摘要（成员+权重+是否采纳）；冠军指标不低于
    最佳单模型（采纳条件 recall>=最佳单模型，持平取集成）；未启用时结果
    形状与旧版完全一致（无 ensemble 键）。
    """

    def _make_frame(self) -> pd.DataFrame:
        rng = np.random.RandomState(7)
        frame = pd.DataFrame({
            "feat_a": np.concatenate([rng.normal(10, 1, 600), rng.normal(-10, 1, 200)]),
            "feat_b": np.concatenate([rng.normal(5, 1, 600), rng.normal(-5, 1, 200)]),
            "target": [1] * 600 + [0] * 200,
        })
        return frame.sample(frac=1.0, random_state=7).reset_index(drop=True)

    def test_ensemble_disabled_keeps_legacy_shape(self):
        result = lightweight_trainer(self._make_frame(), self._make_frame()["target"], hints={})
        self.assertNotIn("ensemble", result)
        self.assertIn("recall_minority", result["metrics"])

    def test_ensemble_enabled_reports_members_and_never_loses_recall(self):
        frame = self._make_frame()
        result = lightweight_trainer(frame, frame["target"], hints={
            "ensemble": {"enabled": True, "top_k": 3},
        })
        ensemble = result["ensemble"]
        self.assertTrue(ensemble["enabled"])
        self.assertIn(ensemble["adopted"], (True, False))
        # 候选家族全部成功时成员=3，权重按召回比例归一
        self.assertEqual(len(ensemble["members"]), 3)
        self.assertAlmostEqual(sum(m["weight"] for m in ensemble["members"]), 1.0, places=2)
        # 冠军（集成或最佳单模型）recall >= 任何单模型候选
        best_single = max(item["recall_minority"] for item in result["topk_metrics"])
        self.assertGreaterEqual(result["metrics"]["recall_minority"], best_single)
        # 集成成员重要性加权平均产出非零重要性（RF 有 feature_importances_）
        self.assertTrue(result["importance"])

    def test_ensemble_top_k_limits_members(self):
        frame = self._make_frame()
        result = lightweight_trainer(frame, frame["target"], hints={
            "ensemble": {"enabled": True, "top_k": 2},
        })
        self.assertEqual(len(result["ensemble"]["members"]), 2)

    def test_ensemble_passes_reported_weights_into_voting(self):
        """展示的成员权重必须就是投票器实际使用的权重（此前只算不传）。"""
        from unittest import mock

        from sklearn.ensemble import VotingClassifier

        frame = self._make_frame()
        with mock.patch("sklearn.ensemble.VotingClassifier", wraps=VotingClassifier) as spy:
            result = lightweight_trainer(frame, frame["target"], hints={
                "ensemble": {"enabled": True, "top_k": 3},
            })
        used = spy.call_args.kwargs["weights"]
        reported = [member["weight"] for member in result["ensemble"]["members"]]
        self.assertEqual([round(w, 4) for w in used], reported)

    def test_ensemble_fit_failure_falls_back_without_crashing(self):
        """投票器拟合抛错：退回单模型冠军并记录原因，不得读未定义指标崩溃。"""
        from unittest import mock

        from sklearn.ensemble import VotingClassifier

        frame = self._make_frame()
        with mock.patch.object(VotingClassifier, "fit", side_effect=RuntimeError("boom")):
            result = lightweight_trainer(frame, frame["target"], hints={
                "ensemble": {"enabled": True, "top_k": 3},
            })
        self.assertFalse(result["ensemble"]["adopted"])
        self.assertEqual(result["ensemble"]["reason"], "ensemble_fit_failed")
        self.assertIn("recall_minority", result["metrics"])


class TestTrainerWhitelistHardConstraint(unittest.TestCase):
    """算法白名单硬约束智能体训练族（用户要求"必须使用勾选的"；
    真机 43e908e7：勾了 8 族却出现未勾选的 logistic）。"""

    def _make_frame(self) -> pd.DataFrame:
        rng = np.random.RandomState(7)
        frame = pd.DataFrame({
            "feat_a": np.concatenate([rng.normal(10, 1, 300), rng.normal(-10, 1, 100)]),
            "feat_b": np.concatenate([rng.normal(5, 1, 300), rng.normal(-5, 1, 100)]),
            "target": [1] * 300 + [0] * 100,
        })
        return frame.sample(frac=1.0, random_state=7).reset_index(drop=True)

    def _trained_names(self, whitelist) -> set:
        frame = self._make_frame()
        result = lightweight_trainer(frame, frame["target"], hints={
            "ensemble": {"enabled": True, "top_k": 5},
            "algorithm_whitelist": whitelist,
        })
        members = (result.get("ensemble") or {}).get("members") or []
        return {member["name"] for member in members}

    def test_only_checked_families_train(self):
        names = self._trained_names(["random_forest", "hist_gradient_boosting"])
        self.assertEqual(names, {"random_forest", "hist_gb"})

    def test_single_family_whitelist_trains_exactly_one(self):
        # 单族白名单：只训练勾选的那一族（不足 2 个候选 → 不组集成，reason 如实记录）
        frame = self._make_frame()
        result = lightweight_trainer(frame, frame["target"], hints={
            "ensemble": {"enabled": True, "top_k": 5},
            "algorithm_whitelist": ["mlp"],
        })
        self.assertEqual(len(result["topk_metrics"]), 1)
        self.assertEqual(result["ensemble"]["reason"], "fewer_than_2_candidates")

    def test_unchecked_families_never_appear(self):
        names = self._trained_names(["catboost", "lightgbm"])
        self.assertEqual(names, {"catboost", "lightgbm"})
        self.assertNotIn("logistic", names)
        self.assertNotIn("random_forest", names)

    def test_empty_whitelist_trains_builtin_trio_including_logistic(self):
        names = self._trained_names([])
        self.assertIn("logistic", names)
        self.assertTrue({"random_forest", "hist_gb"}.issubset(names))


class TestDataFidelityContract(unittest.TestCase):
    """全量训练合同（2026-11-08 用户定稿）：默认百分百全量；抽样上限仅
    在用户显式关闭 full_data 时启用，且保真度事实随指标返回——抽样子集
    结果绝不假装全量。"""

    @staticmethod
    def _frame(rows: int):
        rng = np.random.RandomState(7)
        signal = rng.rand(rows)
        frame = pd.DataFrame({"f1": signal, "f2": rng.rand(rows)})
        labels = (signal > 0.8).astype(int)  # 少数类 ~20%
        return frame, labels

    def test_default_full_data_never_samples(self):
        """默认（full_data 缺省=True）：3 万行也全量训练，fidelity 如实标注。"""
        frame, labels = self._frame(30000)
        result = lightweight_trainer(frame, labels, {})
        fidelity = result.get("data_fidelity") or {}
        self.assertTrue(fidelity.get("full_data"))
        self.assertEqual(fidelity.get("total_rows"), 30000)
        self.assertNotIn("sampled_rows", fidelity)  # 无抽样事实
        self.assertTrue(result.get("metrics"))

    def test_sampling_only_when_user_opted_out(self):
        """显式 full_data=False：>2 万行触发分层抽样，fidelity 标注行数+警示。"""
        frame, labels = self._frame(30000)
        result = lightweight_trainer(frame, labels, {"full_data": False})
        fidelity = result.get("data_fidelity") or {}
        self.assertFalse(fidelity.get("full_data"))
        self.assertEqual(fidelity.get("sampled_rows"), 20000)
        self.assertIn("非全量", fidelity.get("note", ""))

    def test_small_dataset_identical_both_modes(self):
        """小数据集（<2 万行）两模式行为一致（无抽样事实）。"""
        frame, labels = self._frame(500)
        full = lightweight_trainer(frame, labels, {"full_data": True})
        sampled_mode = lightweight_trainer(frame, labels, {"full_data": False})
        self.assertEqual(
            full["metrics"]["recall_minority"],
            sampled_mode["metrics"]["recall_minority"],
        )


if __name__ == "__main__":
    unittest.main()
