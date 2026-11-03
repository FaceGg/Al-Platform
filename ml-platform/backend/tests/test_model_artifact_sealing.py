"""模型工件密封合同测试（Mimosa 2026-11-03 "不安全反序列化"收口）。

写入侧：ArtifactService.create_from_file 对 model 类工件自动打 HMAC 密封。
加载侧：LoadModelArtifactOperator 无有效 seal 即拒绝反序列化——自助上传
的裸 joblib 无法借编排节点触发服务端代码执行。
"""
import io
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, ".")

import joblib  # noqa: E402
from sklearn.dummy import DummyClassifier  # noqa: E402

from app.services.model_artifact_sealing import (  # noqa: E402
    compute_model_seal,
    model_seal_metadata,
    seal_is_valid,
)


class TestSealPrimitives(unittest.TestCase):
    def test_seal_binds_content_hash_and_verifies(self):
        seal = compute_model_seal("a" * 64)
        self.assertEqual(seal, compute_model_seal("a" * 64))
        self.assertNotEqual(seal, compute_model_seal("b" * 64))
        self.assertTrue(seal_is_valid({"model_seal": seal}, "a" * 64))
        self.assertFalse(seal_is_valid({"model_seal": seal}, "b" * 64))

    def test_missing_or_malformed_seal_is_rejected(self):
        self.assertFalse(seal_is_valid(None, "a" * 64))
        self.assertFalse(seal_is_valid({}, "a" * 64))
        self.assertFalse(seal_is_valid({"model_seal": ""}, "a" * 64))
        self.assertFalse(seal_is_valid({"model_seal": 12345}, "a" * 64))
        # 篡改位翻转（常量时间比较下仍应拒绝）
        good = model_seal_metadata("a" * 64)["model_seal"]
        self.assertFalse(seal_is_valid({"model_seal": "0" + good[1:]}, "a" * 64))


class TestCreateFromFileSealsModelArtifacts(unittest.TestCase):
    def test_model_artifact_gets_seal_and_dataset_does_not(self):
        from app.database import Base, SessionLocal, engine  # noqa: E402
        from app.models.user import User  # noqa: E402
        from app.models.project import Project  # noqa: E402
        from app.services.artifact_service import build_artifact_service  # noqa: E402

        Base.metadata.create_all(bind=engine)
        with tempfile.TemporaryDirectory() as tmp:
            model_path = Path(tmp) / "model.joblib"
            joblib.dump(DummyClassifier(strategy="most_frequent"), model_path)
            dataset_path = Path(tmp) / "rows.csv"
            dataset_path.write_text("a,b\n1,2\n", encoding="utf-8")

            with SessionLocal() as db:
                owner = User(username=f"seal-{uuid.uuid4().hex[:8]}", password_hash="hash")
                db.add(owner)
                db.flush()
                project = Project(name="seal-project", owner_id=owner.id)
                db.add(project)
                db.flush()
                service = build_artifact_service(db)
                model_artifact = service.create_from_file(
                    project.id, model_path, "sealed-model", "model",
                )
                dataset_artifact = service.create_from_file(
                    project.id, dataset_path, "plain-dataset", "dataset",
                )
                db.commit()

                model_meta = model_artifact.metadata_ or {}
                self.assertIn("model_seal", model_meta)
                self.assertTrue(seal_is_valid(model_meta, model_meta["sha256"]))
                dataset_meta = dataset_artifact.metadata_ or {}
                self.assertNotIn("model_seal", dataset_meta)


if __name__ == "__main__":
    unittest.main()
