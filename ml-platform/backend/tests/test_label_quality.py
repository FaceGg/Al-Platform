"""S3 标注质量链（B2-05/06/G4/E15）：九策略选样、κ+仲裁+纯度门禁、伪标签
限量/降权/比较/凭证。

验收口径（技术方案 §8.4）：九策略单测+混合权重预算截断；分歧自动进仲裁；
低纯度群无法整簇提交；超限量候选被拒；凭证与库内一致。
"""
import unittest
import uuid

import numpy as np
import pandas as pd

from app.models.label_quality import (
    AnnotationBlindLabel,
    ConsistencyRound,
    LabelArbitration,
    PseudoLabelBatch,
)
from app.models.project import Project
from app.models.user import User
from app.services.active_learning import (
    SelectionError,
    _score_entropy,
    _score_least_confidence,
    _score_margin,
    record_selection,
    select_samples,
)
from app.services.consistency import (
    CLUSTER_PURITY_FLOOR,
    ConsistencyError,
    cohen_kappa,
    compute_kappa,
    decide_arbitration,
    label_quality_gate,
    open_round,
    submit_blind_label,
)


def _proba_frame(rows: int = 40) -> pd.DataFrame:
    rng = np.random.RandomState(11)
    frame = pd.DataFrame({
        "f1": rng.normal(size=rows),
        "f2": rng.normal(size=rows),
        "sample_key": [f"sk-{i}" for i in range(rows)],
    })
    return frame


class _Bundle:
    classes_ = np.array([0, 1])

    def __init__(self, frame: pd.DataFrame):
        self._frame = frame

    def predict_proba(self, matrix):
        scores = 1 / (1 + np.exp(-matrix[:, 0]))
        return np.stack([1 - scores, scores], axis=1)


class TestNineStrategies(unittest.TestCase):
    def setUp(self):
        self.frame = _proba_frame()
        self.bundle = _Bundle(self.frame)
        self.features = ["f1", "f2"]

    def test_uncertainty_scores_match_hand_vectors(self):
        proba = np.array([[0.5, 0.5], [0.99, 0.01], [0.8, 0.2]])
        entropy = _score_entropy(proba)
        margin = _score_margin(proba)
        least = _score_least_confidence(proba)
        # 均匀分布熵最大、最自信行熵最小
        self.assertEqual(int(np.argmax(entropy)), 0)
        self.assertEqual(int(np.argmin(entropy)), 1)
        # margin：最小置信差最大分；least：1-最大概率
        self.assertEqual(int(np.argmax(margin)), 0)
        self.assertAlmostEqual(least[1], 0.01, places=6)

    def test_each_strategy_returns_within_budget(self):
        for name, extra in (
            ("entropy", {}), ("margin", {}), ("least_confidence", {}),
            ("rarity", {}), ("diversity", {}), ("random", {"seed": 7}),
            ("cluster_diversity", {"cluster_column": "sample_key"}),
        ):
            with self.subTest(strategy=name):
                picks, stats = select_samples(
                    bundle=self.bundle, frame=self.frame,
                    feature_columns=self.features,
                    strategy={"name": name, **extra},
                    budget_initial=10, budget_per_round=10,
                )
                self.assertTrue(0 < len(picks) <= 10)
                self.assertEqual(list(stats.values())[0], len(picks))

    def test_hybrid_mixed_weights_respect_budget(self):
        picks, stats = select_samples(
            bundle=self.bundle, frame=self.frame,
            feature_columns=self.features,
            strategy={"name": "hybrid",
                      "weights": {"entropy": 0.6, "random": 0.4}},
            budget_initial=10, budget_per_round=10,
        )
        self.assertLessEqual(len(picks), 10)
        self.assertIn("entropy", stats)
        self.assertIn("random", stats)
        total = sum(stats.values())
        self.assertLessEqual(total, 12)

    def test_invalid_strategy_and_budget_rejected(self):
        with self.assertRaises(SelectionError):
            select_samples(bundle=self.bundle, frame=self.frame,
                           feature_columns=self.features,
                           strategy={"name": "nope"}, budget_initial=5, budget_per_round=5)
        with self.assertRaises(SelectionError):
            select_samples(bundle=self.bundle, frame=self.frame,
                           feature_columns=self.features,
                           strategy={"name": "entropy"}, budget_initial=0, budget_per_round=0)

    def test_selection_persisted_with_fingerprint(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.database import Base

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine, expire_on_commit=False)()
        try:
            user = User(username=f"al-{uuid.uuid4().hex[:6]}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="选样", owner_id=user.id)
            db.add(project)
            db.flush()
            picks, stats = select_samples(
                bundle=self.bundle, frame=self.frame, feature_columns=self.features,
                strategy={"name": "entropy"}, budget_initial=5, budget_per_round=5,
            )
            keys = [str(self.frame.iloc[i]["sample_key"]) for i in picks]
            row = record_selection(
                db, project_id=project.id, model_version_id=None,
                strategy={"name": "entropy"}, budget_initial=5, budget_per_round=5,
                selected_sample_ids=keys, strategy_stats=stats,
                created_by_id=user.id,
            )
            db.commit()
            self.assertEqual(len(row.selected_sample_ids), 5)
            self.assertTrue(row.fingerprint)
        finally:
            db.close()


class TestKappaAndArbitration(unittest.TestCase):
    def setUp(self):
        engine = __import__("sqlalchemy").create_engine(
            "sqlite://", connect_args={"check_same_thread": False},
            poolclass=__import__("sqlalchemy.pool", fromlist=["StaticPool"]).StaticPool,
        )
        from app.database import Base

        Base.metadata.create_all(engine)
        self.db = __import__("sqlalchemy.orm", fromlist=["sessionmaker"]).sessionmaker(
            bind=engine, expire_on_commit=False
        )()
        self.user = User(username=f"kappa-{uuid.uuid4().hex[:6]}", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="一致性", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_kappa_hand_vectors(self):
        self.assertAlmostEqual(cohen_kappa(["a"] * 10, ["a"] * 10), 1.0)
        self.assertLess(cohen_kappa(["a", "b", "a", "b"], ["b", "a", "b", "a"]), 0)
        self.assertGreater(cohen_kappa(["a", "a", "b", "b", "a", "b"], ["a", "a", "b", "b", "a", "a"]), 0.5)

    def test_disagreement_auto_enters_arbitration_and_decides(self):
        round_row = open_round(
            self.db, project_id=self.project.id,
            annotator_subject_ids=["s1", "s2"],
            sample_ids=["sm-1", "sm-2", "sm-3"],
            created_by_id=self.user.id,
        )
        self.db.commit()
        submit_blind_label(self.db, round_id=round_row.id, subject_id="s1",
                           sample_id="sm-1", values={"label": "ok"})
        submit_blind_label(self.db, round_id=round_row.id, subject_id="s1",
                           sample_id="sm-2", values={"label": "ok"})
        submit_blind_label(self.db, round_id=round_row.id, subject_id="s1",
                           sample_id="sm-3", values={"label": "ng"})
        submit_blind_label(self.db, round_id=round_row.id, subject_id="s2",
                           sample_id="sm-1", values={"label": "ok"})
        submit_blind_label(self.db, round_id=round_row.id, subject_id="s2",
                           sample_id="sm-2", values={"label": "ng"})
        submit_blind_label(self.db, round_id=round_row.id, subject_id="s2",
                           sample_id="sm-3", values={"label": "ng"})
        self.db.commit()
        computed = compute_kappa(self.db, round_id=round_row.id)
        self.assertIsNotNone(computed.kappa_average)
        disputes = self.db.query(LabelArbitration).filter(
            LabelArbitration.round_id == round_row.id
        ).all()
        self.assertEqual(len(disputes), 1, "仅 sm-2 分歧 → 自动进仲裁")
        self.assertEqual(disputes[0].sample_id, "sm-2")
        # 仲裁人=盲标人被拒
        with self.assertRaises(ConsistencyError) as caught:
            decide_arbitration(
                self.db, arbitration_id=disputes[0].id, arbiter_id="s1",
                decision_values={"label": "ok"},
            )
        self.assertEqual(caught.exception.code, "ARBITER_SAME_AS_BLIND_ANNOTATOR")
        decided = decide_arbitration(
            self.db, arbitration_id=disputes[0].id, arbiter_id=self.user.id,
            decision_values={"label": "ng"}, note="以证据区规格为准",
        )
        self.db.commit()
        self.assertEqual(decided.status, "decided")
        self.assertEqual(round_row.status, "arbitrated", "全部仲裁完成 → arbitrated")

    def test_purity_gate_blocks_low_purity_cluster(self):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.database import Base
        from app.models.labeling import AnnotationStrategyDecision
        from app.services.consistency import (
            cluster_purity,
            validate_cluster_submission,
        )

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                               poolclass=StaticPool)
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine, expire_on_commit=False)()
        try:
            artifact_id = uuid.uuid4()
            # 20 行簇：13 ok / 7 ng → 纯度 0.65 < 0.8
            for index in range(20):
                db.add(AnnotationStrategyDecision(
                    strategy_artifact_id=artifact_id, sample_id=f"s-{index}",
                    row_index=index, status="ready",
                    cluster_id="c-1", decision_hash=f"h-{index}",
                    values={"label": "ok" if index < 13 else "ng"},
                ))
            db.commit()
            stats = cluster_purity(db, strategy_artifact_id=artifact_id, cluster_id="c-1")
            self.assertLess(stats["purity"], CLUSTER_PURITY_FLOOR)
            with self.assertRaises(ConsistencyError) as caught:
                validate_cluster_submission(
                    db, strategy_artifact_id=artifact_id, cluster_id="c-1"
                )
            self.assertEqual(caught.exception.code, "CLUSTER_PURITY_BELOW_GATE")
        finally:
            db.close()

    def test_quality_gate_stops_training_on_low_kappa(self):
        round_row = open_round(
            self.db, project_id=self.project.id,
            annotator_subject_ids=["s1", "s2"],
            sample_ids=["sm-1", "sm-2", "sm-3", "sm-4"],
            kappa_threshold=0.9,
            created_by_id=self.user.id,
        )
        pairs = [("ok", "ok"), ("ok", "ng"), ("ng", "ng"), ("ok", "ng")]
        for index, (a, b) in enumerate(pairs):
            submit_blind_label(self.db, round_id=round_row.id, subject_id="s1",
                               sample_id=f"sm-{index + 1}", values={"label": a})
            submit_blind_label(self.db, round_id=round_row.id, subject_id="s2",
                               sample_id=f"sm-{index + 1}", values={"label": b})
        self.db.commit()
        compute_kappa(self.db, round_id=round_row.id)
        self.db.commit()
        gate = label_quality_gate(self.db, project_id=self.project.id)
        self.assertTrue(gate["stopped"])
        self.assertGreater(gate["pending_arbitrations"], 0)


class TestPseudoLabels(unittest.TestCase):
    def setUp(self):
        import sqlalchemy as sa

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.database import Base

        self.engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False},
                                       poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.user = User(username=f"pseudo-{uuid.uuid4().hex[:6]}", password_hash="hash")
        self.db.add(self.user)
        self.db.flush()
        self.project = Project(name="伪标签", owner_id=self.user.id)
        self.db.add(self.project)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_quota_threshold_and_downweight(self):
        from app.services.pseudo_labels import (
            credential_rows,
            record_pseudo_batch_from_candidates,
        )

        candidates = [
            {"sample_key": f"sk-{i}", "label": "ok", "confidence": 0.95}
            for i in range(8)
        ] + [
            {"sample_key": f"ng-{i}", "label": "ng", "confidence": 0.92}
            for i in range(3)
        ] + [{"sample_key": "low", "label": "ok", "confidence": 0.80}]
        batch = record_pseudo_batch_from_candidates(
            self.db, project_id=self.project.id,
            candidates=candidates, threshold=0.9, quota_multiplier=0.5,
            labeled_counts={"ok": 10, "ng": 2},
            created_by_id=self.user.id,
        )
        self.db.commit()
        selected = batch.selected
        self.assertEqual(sum(1 for s in selected if s["label"] == "ok"), 5,
                         "ok 类限量 = 10×0.5 = 5（超量候选被拒）")
        self.assertEqual(sum(1 for s in selected if s["label"] == "ng"), 1,
                         "ng 类限量 = max(1, 2×0.5) = 1")
        self.assertNotIn("low", [s["sample_key"] for s in selected],
                         "低于阈值候选被滤")
        for item in selected:
            self.assertAlmostEqual(item["weight"], round(item["confidence"] ** 2, 6),
                                   msg="降权 = 置信度平方")
        rows = credential_rows(batch)
        self.assertEqual(len(rows), len(selected))
        self.assertEqual(rows[0]["training_fold"], "pseudo")

    def test_comparison_requires_weighted_to_win(self):
        from app.services.pseudo_labels import (
            compare_on_dev_validation,
            record_pseudo_batch_from_candidates,
        )

        batch = record_pseudo_batch_from_candidates(
            self.db, project_id=self.project.id,
            candidates=[{"sample_key": "a", "label": "ok", "confidence": 0.99}],
            threshold=0.9, quota_multiplier=1.0, labeled_counts={"ok": 5},
        )
        self.db.commit()
        lost = compare_on_dev_validation(
            self.db, batch_id=batch.id,
            baseline_metrics={"f1": 0.9}, weighted_metrics={"f1": 0.8},
        )
        self.assertEqual(lost.winner, 0, "未胜出不选用")
        won = compare_on_dev_validation(
            self.db, batch_id=batch.id,
            baseline_metrics={"f1": 0.8}, weighted_metrics={"f1": 0.85},
        )
        self.assertEqual(won.winner, 1)
        self.assertEqual(won.dev_comparison["verdict"], "weighted_wins")


if __name__ == "__main__":
    unittest.main()
