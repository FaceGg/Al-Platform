"""S5 servitization tests (AutoML Agent plan, Task A3.3).

Contract under test (spec v0.9 §12.1/§12.6): draft semantics (loop created
passively, model API ``offline`` until the explicit approval switch),
defect-class derivation from target semantics, dry-run smoke with ZERO
backflow (negative control: a wet predict on the same config DOES write), and
the project-level mutex.
"""

import os
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("LLM_MASTER_KEY", __import__(
    "cryptography.fernet", fromlist=["Fernet"]
).Fernet.generate_key().decode("ascii"))

import joblib  # noqa: E402
from sklearn.linear_model import LogisticRegression  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.models.api_model import PlatformAPI  # noqa: E402
from app.models.demo_loop import DemoLoopConfig  # noqa: E402
from app.models.model_library import ModelLibrary  # noqa: E402
from app.models.model_registry import (  # noqa: E402
    InferenceDeployment,
    ModelVersion,
    RegisteredModel,
)
from app.models.project import Project  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.agent.servitize import (  # noqa: E402
    activate_servitize,
    derive_error_classes,
    servitize_lock,
    servitize_recipe,
)
from app.services.artifact_service import build_artifact_service  # noqa: E402
from tests.auth_test_support import ensure_admin  # noqa: E402

Base.metadata.create_all(bind=engine)

_RECIPE_CONTENT = {
    "domain": "tightening",
    "target_semantics": {"0": "不合格", "1": "合格"},
    "inputs": {"target_column": "DECIDE(判定结果)"},
    "feature_script": "def transform(df):\n    return df",
    "acceptance_gates": {"recall_minority": 0.90},
    "smoke_row": {"f1": 5.0, "f2": -1.0},
}


class TestDeriveErrorClasses(unittest.TestCase):
    def test_defect_semantics_derived(self):
        classes, ambiguous = derive_error_classes(
            {"0": "不合格", "1": "合格"}
        )
        self.assertEqual(classes, ["0"])
        self.assertEqual(ambiguous, ["1"])

    def test_no_match_falls_back_with_ambiguity(self):
        classes, ambiguous = derive_error_classes({"A": "类型甲", "B": "类型乙"})
        self.assertEqual(classes, ["A"])
        self.assertEqual(sorted(ambiguous), ["A", "B"])


class TestServitize(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ensure_admin()
        db = SessionLocal()
        try:
            admin = db.query(User).filter(User.username == "admin").one()
            project = Project(name="s5-%s" % uuid4().hex[:8], owner_id=admin.id)
            db.add(project)
            db.flush()
            service = build_artifact_service(db)
            model = LogisticRegression().fit(
                [[0.0, 1.0], [0.2, 1.1], [5.0, -1.0], [5.2, -1.2]],
                [0, 0, 1, 1],
            )
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "s5-model.joblib"
                joblib.dump(model, path)
                artifact = service.create_from_file(
                    project.id, path, "s5-model", "model"
                )
            artifact_id = uuid.UUID(str(artifact.id))
            registered = RegisteredModel(
                project_id=project.id,
                name="s5-model-%s" % uuid4().hex[:6],
                created_by_id=admin.id,
            )
            db.add(registered)
            db.flush()
            library = ModelLibrary(
                name="s5-lib-%s" % uuid4().hex[:6],
                project_id=project.id,
                owner_id=admin.id,
                status="completed",
                framework="sklearn",
                model_artifact_id=artifact_id,
                file_size=1,
                format="joblib",
            )
            db.add(library)
            db.flush()
            version = ModelVersion(
                registered_model_id=registered.id,
                version_number=1,
                source_kind="platform_joblib",
                source_artifact_id=artifact_id,
                onnx_artifact_id=artifact_id,
                approval_status="approved",
                source_model_library_id=library.id,
                created_by_id=admin.id,
            )
            db.add(version)
            db.flush()
            deployment = InferenceDeployment(
                project_id=project.id,
                name="s5-deploy-%s" % uuid4().hex[:6],
                model_version_id=version.id,
                created_by_id=admin.id,
            )
            db.add(deployment)
            db.commit()
            cls.project_id = project.id
            cls.deployment_id = str(deployment.id)
            cls.admin_id = admin.id
        finally:
            db.close()

    def setUp(self):
        # Shared deployment across tests: clear servitize state so each test
        # starts from an unpublished project.
        with SessionLocal() as db:
            from app.models.demo_loop import DemoLoopEvent

            db.query(PlatformAPI).filter(
                PlatformAPI.source_kind == "servitize"
            ).delete()
            db.query(DemoLoopEvent).delete()
            db.query(DemoLoopConfig).delete()
            db.commit()

    def servitize(self, **overrides):
        with SessionLocal() as db:
            return servitize_recipe(
                db,
                project_id=self.project_id,
                actor_id=self.admin_id,
                deployment_id=self.deployment_id,
                recipe_content=dict(_RECIPE_CONTENT),
                **overrides,
            )

    def test_draft_semantics_loop_passive_api_offline(self):
        draft = self.servitize(model_api_name="s5-draft-%s" % uuid4().hex[:6])
        self.assertFalse(draft.activated)
        with SessionLocal() as db:
            api = db.get(PlatformAPI, uuid.UUID(draft.model_api_id))
            loop = db.get(DemoLoopConfig, uuid.UUID(draft.loop_config_id))
        self.assertEqual(api.status, "offline")
        self.assertEqual(api.source_kind, "servitize")
        self.assertIsNotNone(loop)
        self.assertEqual(loop.error_classes, ["0"])
        self.assertEqual(loop.feature_engineering_mode, "script")
        # A draft loop has seen zero traffic.
        self.assertEqual(int(loop.total_count or 0), 0)

    def test_smoke_is_dry_run_with_zero_backflow(self):
        draft = self.servitize(model_api_name="s5-smoke-%s" % uuid4().hex[:6])
        self.assertTrue(draft.smoke.get("dry_run"))
        self.assertEqual(draft.smoke.get("appended"), False)
        with SessionLocal() as db:
            loop = db.get(DemoLoopConfig, uuid.UUID(draft.loop_config_id))
            total_after_smoke = int(loop.total_count or 0)
            errors_after_smoke = int(loop.error_count or 0)
        self.assertEqual(total_after_smoke, 0)
        self.assertEqual(errors_after_smoke, 0)

        # Negative control: a wet predict on the SAME config writes state —
        # proving the zero-backflow assertion above can detect pollution.
        with SessionLocal() as db:
            loop = db.get(DemoLoopConfig, uuid.UUID(draft.loop_config_id))
            from app.services.demo_loop import DemoLoopService

            DemoLoopService(db).predict(
                loop, {"f1": 5.0, "f2": -1.0}, self.admin_id
            )
            db.refresh(loop)
            self.assertGreaterEqual(int(loop.total_count or 0), 1)

    def test_activation_flips_offline_to_published(self):
        draft = self.servitize(model_api_name="s5-act-%s" % uuid4().hex[:6])
        with SessionLocal() as db:
            api = activate_servitize(
                db, model_api_id=draft.model_api_id, actor_id=self.admin_id
            )
            self.assertEqual(api.status, "published")
            self.assertIsNotNone(api.published_at)
            with self.assertRaises(ValueError):
                activate_servitize(
                    db, model_api_id=draft.model_api_id, actor_id=self.admin_id
                )

    def test_reservitize_reuses_draft_and_bumps_version(self):
        # platform_apis is unique per (source_kind, source_id, version): a
        # second servitize call on the SAME deployment must reuse the offline
        # draft row (and its loop config), bumping the entry version (§12.4).
        base = "s5-reuse-%s" % uuid4().hex[:6]
        first = self.servitize(model_api_name=base)
        second = self.servitize(model_api_name=base)
        self.assertEqual(first.model_api_id, second.model_api_id)
        self.assertEqual(first.loop_config_id, second.loop_config_id)
        with SessionLocal() as db:
            api = db.get(PlatformAPI, uuid.UUID(second.model_api_id))
            self.assertEqual(api.version, "v2")
            self.assertEqual(api.status, "offline")

    def test_project_mutex_serializes_servitize(self):
        order = []

        def worker():
            with servitize_lock(self.project_id):
                order.append("enter")
                order.append("exit")

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        # Strict alternation proves mutual exclusion: never enter,enter.
        for index in range(0, len(order) - 2, 2):
            self.assertEqual(order[index], "enter")
            self.assertEqual(order[index + 1], "exit")
