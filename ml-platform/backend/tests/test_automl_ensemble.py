"""终选层集成（方案一）单元测试：多模型加权投票的构建/采纳/重要性合并。

合同（_build_ensemble_candidate）：
- 候选 = 主指标排序前 K 个完成家族；权重按主指标占比归一。
- 采纳键镜像家族排序 (auc, f1, accuracy)：集成不低于最佳单模型才采纳，
  持平取集成；model 仅在采纳时非 None，绝不降低现有水平。
- 候选不足 2 个 / 回归任务 / 集成拟合失败 → 未采纳退回单模型冠军。
- 集成特征重要性 = 成员原生重要性按权重加权平均（无重要性成员跳过）。
"""

import unittest

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from app.services.automl_execution import (
    _build_ensemble_candidate,
    _ensemble_feature_importance,
    _ensemble_metric_key,
    _native_feature_importance,
)
from app.services.automl_search import FamilySearchResult


def _make_frame(n: int = 400):
    rng = np.random.RandomState(7)
    X = np.column_stack([
        np.concatenate([rng.normal(10, 1, n // 2), rng.normal(-10, 1, n - n // 2)]),
        np.concatenate([rng.normal(5, 1, n // 2), rng.normal(-5, 1, n - n // 2)]),
    ])
    y = np.array([0] * (n // 2) + [1] * (n - n // 2))
    return X, y


def _family(algorithm_id: str, estimator, auc: float, catalog_index: int = 0) -> FamilySearchResult:
    X, y = _make_frame()
    estimator.fit(X, y)
    return FamilySearchResult(
        algorithm_id=algorithm_id,
        display_name=algorithm_id,
        catalog_index=catalog_index,
        status="completed",
        best_score=round(auc - 0.02, 4),
        best_estimator=estimator,
        auc=auc,
        f1=round(auc - 0.01, 4),
    )


class TestEnsembleCandidate(unittest.TestCase):
    def _families(self):
        X, y = _make_frame()
        evaluation = {"cross_validation_enabled": True, "cross_validation_folds": 3}
        families = [
            _family("random_forest", RandomForestClassifier(n_estimators=12, random_state=7), 0.99, 0),
            _family("logistic", LogisticRegression(max_iter=300), 0.98, 1),
            _family("hist_gb", HistGradientBoostingClassifier(max_iter=30, random_state=7), 0.97, 2),
        ]
        winner = families[0]
        return winner, families, evaluation

    def test_metric_key_absent_metrics_do_not_win(self):
        self.assertEqual(_ensemble_metric_key(None, None, None), (-1.0, -1.0, -1.0))
        self.assertGreater(_ensemble_metric_key(0.9, None, None), _ensemble_metric_key(None, 0.99, 0.99))

    def test_adopted_on_tie_with_winner_and_weights_normalized(self):
        """成员含冠军本身 → 集成指标通常持平/更优；持平键取集成（>= 采纳）。"""
        winner, families, evaluation = self._families()
        model, info, members, weights = _build_ensemble_candidate(
            winner=winner, family_results=families, task="classification",
            features=_make_frame()[0], target=_make_frame()[1],
            evaluation=evaluation, ensemble_config={"enabled": True, "top_k": 3},
        )
        self.assertEqual(len(members), 3)
        self.assertAlmostEqual(sum(weights), 1.0, places=6)
        # 权重按主指标占比：最强家族权重最大
        self.assertEqual(members[0].algorithm_id, "random_forest")
        self.assertGreaterEqual(weights[0], weights[1])
        # 良好可分数据上集成不应劣于冠军（采纳或键持平/更高）
        self.assertTrue(info["adopted"])
        self.assertIsNotNone(model)
        self.assertEqual(info["voting"], "soft")
        # 权重必须真正传入投票器（此前只算不传 = 等权平均，展示名不副实）
        self.assertEqual([round(w, 6) for w in model.weights], [round(w, 6) for w in weights])
        X, _ = _make_frame()
        proba = model.predict_proba(X)
        self.assertEqual(proba.shape, (len(X), 2))

    def test_not_adopted_still_returns_fitted_vote_for_persistence(self):
        """未采纳也返回已拟合投票器——持久化后可在结果列表单独注册。"""
        rng = np.random.RandomState(3)
        X = np.vstack([rng.normal(0, 1, (200, 2)), rng.normal(1, 1, (200, 2))])
        y = np.array([0] * 200 + [1] * 200)
        families = []
        for index, (name, estimator) in enumerate([
            ("random_forest", RandomForestClassifier(n_estimators=12, random_state=7)),
            ("logistic", LogisticRegression(max_iter=300)),
        ]):
            estimator.fit(X, y)
            # 冠军指标虚高到 1.0：噪声数据上集成的真实 CV 指标必然更低 → 不采纳
            families.append(FamilySearchResult(
                algorithm_id=name, display_name=name, catalog_index=index,
                status="completed", best_score=1.0, best_estimator=estimator,
                auc=1.0, f1=1.0,
            ))
        model, info, members, weights = _build_ensemble_candidate(
            winner=families[0], family_results=families, task="classification",
            features=X, target=y,
            evaluation={"cross_validation_enabled": True, "cross_validation_folds": 3},
            ensemble_config={"enabled": True, "top_k": 2},
        )
        self.assertFalse(info["adopted"])
        self.assertIsNotNone(model)
        self.assertEqual(len(members), 2)
        self.assertEqual(model.predict_proba(X[:5]).shape, (5, 2))

    def test_top_k_clamped_and_fewer_than_two_not_adopted(self):
        winner, families, evaluation = self._families()
        model, info, members, _w = _build_ensemble_candidate(
            winner=winner, family_results=[families[0]], task="classification",
            features=_make_frame()[0], target=_make_frame()[1],
            evaluation=evaluation, ensemble_config={"enabled": True, "top_k": 3},
        )
        self.assertIsNone(model)
        self.assertFalse(info["adopted"])
        self.assertEqual(info["reason"], "fewer_than_2_candidates")

    def test_regression_task_rejected(self):
        winner, families, _e = self._families()
        model, info, members, _w = _build_ensemble_candidate(
            winner=winner, family_results=families, task="regression",
            features=_make_frame()[0], target=_make_frame()[1],
            evaluation={"cross_validation_enabled": False},
            ensemble_config={"enabled": True},
        )
        self.assertIsNone(model)
        self.assertEqual(info["reason"], "classification_only")

    def test_ensemble_importance_weighted_average_skips_gap_members(self):
        """无 feature_importances_ 的 HGB 成员被跳过，权重在贡献者内归一。"""
        winner, families, _e = self._families()
        rf = families[0].best_estimator
        lr = families[1].best_estimator
        width = 2
        rf_vec = _native_feature_importance(rf, width)
        lr_vec = _native_feature_importance(lr, width)
        self.assertTrue(rf_vec)
        self.assertTrue(lr_vec)
        merged = _ensemble_feature_importance(
            [families[0], families[1], families[2]], [0.4, 0.3, 0.3], width,
        )
        self.assertEqual(len(merged), width)
        # HGB（无向量）跳过后只剩 rf/lr 按 0.4:0.3 归一 → rf 贡献占比 4/7
        self.assertAlmostEqual(merged[0], 0.4 / 0.7 * rf_vec[0] + 0.3 / 0.7 * lr_vec[0], places=6)


if __name__ == "__main__":
    unittest.main()
