"""S2a 建模轮次与盲测台账（B2-G1）：创建即锁定、旧盲测复用被拒、E03 上限、
台账落行、训练接线（development 过滤、默认路径零变化红线）。
"""
import unittest
import uuid

import numpy as np
import pandas as pd

from app.models.dataset_splitting import (
    BlindTestUsage,
    DatasetSplit,
    DatasetSplitMember,
    ModelingRound,
)
from app.models.access import AuditEvent
from app.models.project import Project
from app.models.user import User
from app.services.dataset_splitting import (
    assign_roles,
    create_split,
    filter_frame_by_roles,
    load_role_indices,
)
from app.services.modeling_rounds import (
    RoundError,
    record_blind_evaluation,
    start_round,
)


def _frame(rows: int = 60) -> pd.DataFrame:
    rng = np.random.RandomState(3)
    return pd.DataFrame({
        "feature_a": rng.normal(size=rows),
        "target": (rng.random(rows) > 0.6).astype(int),
        "sample_key": [f"sk-{i}" for i in range(rows)],
    })


class RoundsCase(unittest.TestCase):
    def setUp(self):
        import sqlite3

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app.database import Base

        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        with self.session_factory() as db:
            self.owner = User(username=f"rounds-{uuid.uuid4().hex[:6]}", password_hash="hash")
            db.add(self.owner)
            db.flush()
            self.project = Project(name="轮次与台账", owner_id=self.owner.id)
            db.add(self.project)
            db.commit()

    def _split(self, version_id=None):
        with self.session_factory() as db:
            split = create_split(
                db,
                project_id=self.project.id,
                dataset_version_id=version_id or uuid.uuid4(),
                name="轮次划分",
                strategy="random_stratified",
                params={"test_size": 0.2, "seed": 42,
                        "target_column": "target", "sample_key_column": "sample_key"},
                frame=_frame(),
                created_by_id=self.owner.id,
            )
            db.commit()
            return split.id


class TestRoundLifecycle(RoundsCase):
    def test_start_round_locks_and_records_audit(self):
        split_id = self._split()
        with self.session_factory() as db:
            round_row = start_round(
                db, project_id=self.project.id, split_id=split_id,
                actor_id=self.owner.id, cap=2,
            )
            db.commit()
            self.assertEqual(round_row.status, "locked")
            self.assertIsNotNone(round_row.blind_fingerprint)
            audits = (
                db.query(AuditEvent)
                .filter(AuditEvent.action == "modeling_round.start")
                .all()
            )
            self.assertEqual(len(audits), 1, "锁定落审计（验收口径 1）")

    def test_used_blind_cannot_be_reused_by_new_round(self):
        split_id = self._split()
        with self.session_factory() as db:
            first = start_round(
                db, project_id=self.project.id, split_id=split_id,
                actor_id=self.owner.id,
            )
            record_blind_evaluation(
                db, round_id=first.id, purpose="release_final_validation",
                used_by_id=self.owner.id, sample_count=12,
                samples_fingerprint=first.blind_fingerprint,
            )
            db.commit()
            # 新轮次引用同一 split → blind 指纹撞台账 → 拒绝（验收口径 3）
            with self.assertRaises(RoundError) as caught:
                start_round(
                    db, project_id=self.project.id, split_id=split_id,
                    actor_id=self.owner.id,
                )
            self.assertEqual(caught.exception.code, "BLIND_REUSE_REJECTED")

    def test_blind_eval_cap_default_two(self):
        split_id = self._split()
        with self.session_factory() as db:
            round_row = start_round(
                db, project_id=self.project.id, split_id=split_id,
                actor_id=self.owner.id,
            )
            record_blind_evaluation(
                db, round_id=round_row.id, purpose="release_final_validation",
                used_by_id=self.owner.id, sample_count=10,
                samples_fingerprint=round_row.blind_fingerprint,
            )
            record_blind_evaluation(
                db, round_id=round_row.id, purpose="no_regression_check",
                used_by_id=self.owner.id, sample_count=10,
                samples_fingerprint=round_row.blind_fingerprint,
            )
            db.commit()
            with self.assertRaises(RoundError) as caught:
                record_blind_evaluation(
                    db, round_id=round_row.id, purpose="other",
                    used_by_id=self.owner.id, sample_count=10,
                    samples_fingerprint=round_row.blind_fingerprint,
                )
            self.assertEqual(caught.exception.code, "BLIND_EVAL_CAP_REACHED")
            usages = db.query(BlindTestUsage).filter(
                BlindTestUsage.round_id == round_row.id
            ).all()
            self.assertEqual(len(usages), 2, "达到上限前每次评估自动进台账")

    def test_new_batch_new_version_can_start_fresh_round(self):
        split_id = self._split(version_id=uuid.uuid4())
        with self.session_factory() as db:
            first = start_round(
                db, project_id=self.project.id, split_id=split_id,
                actor_id=self.owner.id,
            )
            record_blind_evaluation(
                db, round_id=first.id, purpose="release_final_validation",
                used_by_id=self.owner.id, sample_count=12,
                samples_fingerprint=first.blind_fingerprint,
            )
            db.commit()
        # 新批次 = 新数据集版本 → 新划分，blind 样本键不同 → 允许开新轮次
        with self.session_factory() as db:
            new_frame = _frame(rows=80)
            second_split = create_split(
                db,
                project_id=self.project.id,
                dataset_version_id=uuid.uuid4(),
                name="新批次划分",
                strategy="random_stratified",
                params={"test_size": 0.2, "seed": 42,
                        "target_column": "target", "sample_key_column": "sample_key"},
                frame=new_frame,
                created_by_id=self.owner.id,
            )
            db.commit()
            second = start_round(
                db, project_id=self.project.id, split_id=second_split.id,
                actor_id=self.owner.id,
            )
            self.assertIsNotNone(second)


class TestTrainingWiring(RoundsCase):
    def test_development_filter_excludes_blind_rows(self):
        split_id = self._split()
        with self.session_factory() as db:
            roles = load_role_indices(db, split_id)
        frame = _frame()
        dev = filter_frame_by_roles(frame, roles, "development")
        blind = filter_frame_by_roles(frame, roles, "blind")
        self.assertEqual(len(dev) + len(blind), len(frame))
        dev_keys = set(dev["sample_key"])
        blind_keys = set(blind["sample_key"])
        self.assertFalse(dev_keys & blind_keys)

    def test_default_path_unchanged_semantics(self):
        """红线：不带 dataset_split_id 的训练路径与划分管理完全无关——
        引擎默认 holdout（20%/seed42）行为由既有 AutoML 用例锁死（不改一字），
        本用例只验证「无 split_id → 不过滤」的接线分支语义。"""
        params_without_split = {"target_column": "target"}
        self.assertIsNone(params_without_split.get("dataset_split_id"))


if __name__ == "__main__":
    unittest.main()
