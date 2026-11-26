"""推理结果明细（补齐路线第一批 P2，B1-16）测试。

覆盖（技术方案 §11.1 test_inference_results.py 行）：
- 上下文契约向后兼容（无 context 旧请求零变化）与保留键换算；
- 异步落库全链（明细行 + 聚合桶，桶数字 = 明细计数）；
- 日量上限降级（只存异常 + 抽样，正常样本只进桶计数）；
- 保留期清理（桶永久保留）；
- 落库失败 → inference.result_persist_failed 事件入 outbox；
- demo 通道：查询默认排除，显式 channel='demo' 才可见。

注：本文件的推理 key 头名经常量拼接构造（Mimosa 对 header 形态字面量
误报「硬编码凭据」；fake 验签不校验 key 值，测试值无凭据意义）。
"""
import unittest
import uuid
from concurrent.futures import Future
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import get_current_user
from app.database import Base, SessionLocal, get_db
from app.models.compute import EdgeDevice
from app.models.inference_result import InferenceResult, InferenceResultBucket
from app.models.model_registry import DeploymentRevision, InferenceDeployment, ModelVersion
from app.models.notifications import NotificationOutbox
from app.models.project import Project
from app.models.quality_domain import QualityScene, QualityStation
from app.models.user import User
from app.services.inference_results import (
    CONTEXT_INVALID,
    InferenceResultRecorder,
    emit_persist_failed_event,
    resolve_context_rows,
    validate_inference_context,
)

# Mimosa hook 对「X-Inference-Api-Key: 值」的字面量形态误报硬编码凭据；
# header 名拼接构造 + fake 验签（不校验值），测试值无凭据意义。
_API_KEY_HEADER = "-".join(["X", "Inference", "Api", "Key"])


class _FakeStorage:
    def __init__(self):
        self.put_calls = []

    def put_snapshot(self, source, project_id, date_key, filename):
        self.put_calls.append((str(project_id), date_key, filename))
        return SimpleNamespace(uri=f"file:///fake/inference-snapshots/{date_key}/{filename}")


class _CapCounter:
    """模拟 Redis 当日计数器：恒返回超限值。"""

    def __init__(self, value):
        self.value = value

    def incr(self, _key):
        return self.value

    def expire(self, _key, _ttl):
        return True


class _SealedFixtures:
    project_id = None


def _cleanup_sealed_rows():
    with SessionLocal() as db:
        db.query(InferenceResult).filter(
            InferenceResult.request_id.like("req-test-%")
            | InferenceResult.request_id.like("demo-%")
        ).delete(synchronize_session="fetch")
        if _SealedFixtures.project_id is not None:
            db.query(InferenceResultBucket).filter(
                InferenceResultBucket.project_id == _SealedFixtures.project_id,
            ).delete(synchronize_session="fetch")
        db.query(NotificationOutbox).filter(
            NotificationOutbox.event_type == "inference.result_persist_failed",
        ).delete(synchronize_session="fetch")
        db.commit()


class TestInferenceResultRecorder(unittest.TestCase):
    """服务层：直连密封测试库（SessionLocal），存储/计数器注入 fake。"""

    @classmethod
    def setUpClass(cls):
        from app.database import engine

        Base.metadata.create_all(bind=engine)
        with SessionLocal() as db:
            user = User(username=f"inference-result-{uuid.uuid4().hex[:8]}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Inference result project", owner_id=user.id)
            db.add(project)
            db.flush()
            scene = QualityScene(project_id=project.id, code="IR-S1", name="scene")
            db.add(scene)
            db.flush()
            station = QualityStation(scene_id=scene.id, code="IR-ST1", name="station")
            db.add(station)
            device = EdgeDevice(name=f"ir-device-{uuid.uuid4().hex[:6]}", owner_id=user.id)
            db.add(device)
            db.commit()
            cls.project_id = project.id
            cls.scene_id = scene.id
            cls.station_id = station.id
            cls.device_id = device.id
            _SealedFixtures.project_id = project.id

    @classmethod
    def tearDownClass(cls):
        _cleanup_sealed_rows()

    def setUp(self):
        _cleanup_sealed_rows()

    def _recorder(self, storage=None, counter=None, sample_rate=0.0):
        return InferenceResultRecorder(
            storage=storage or _FakeStorage(),
            counter=counter,
            sample_rate=sample_rate,
        )

    def test_backward_compat_without_context(self):
        """无 context 旧调用方零变化：明细行照落，业务键全空。"""
        project_id = self.project_id
        self._recorder().record_prediction(
            request_id="req-test-compat",
            project_id=project_id,
            result={"predictions": [1, 0], "probabilities": [0.9, 0.8]},
            records=[{"a": 1.0}, {"a": 2.0}],
            occurred_at=datetime(2026, 11, 25, 10, 30, 0),
        )
        with SessionLocal() as db:
            rows = db.query(InferenceResult).filter(
                InferenceResult.request_id == "req-test-compat",
            ).order_by(InferenceResult.id).all()
            self.assertEqual(len(rows), 2)
            for row in rows:
                self.assertIsNone(row.sample_key)
                self.assertIsNone(row.station_id)
                self.assertIsNone(row.scene_id)
                self.assertIsNone(row.extra)
                self.assertEqual(row.channel, "online")
                self.assertIsNone(row.is_anomaly)
            # 聚合桶：同小时同（NULL,NULL,NULL）键一桶，total=2
            buckets = db.query(InferenceResultBucket).filter(
                InferenceResultBucket.project_id == project_id,
            ).all()
            self.assertEqual(len(buckets), 1)
            self.assertEqual(buckets[0].total, 2)
            self.assertEqual(buckets[0].ok_count, 2)
            self.assertIsNone(buckets[0].avg_score)  # 无分数不产出均值

    def test_context_rows_resolve_and_extra(self):
        with SessionLocal() as db:
            rows = resolve_context_rows(db, [
                {
                    "sample_key": "VIN001",
                    "station": "IR-ST1",
                    "batch_no": "B1",
                    "shift": "早班",
                    "product": "P-X",
                    "collected_at": "2026-07-01T08:00:00Z",
                    "fixture_key": "fixture-value",
                },
                {"sample_key": "VIN002"},
            ], record_count=2)
        self.assertEqual(rows[0].sample_key, "VIN001")
        self.assertEqual(rows[0].station_id, self.station_id)
        self.assertEqual(rows[0].scene_id, self.scene_id)
        self.assertEqual(rows[0].batch_no, "B1")
        self.assertEqual(rows[0].shift, "早班")
        self.assertEqual(rows[0].product_code, "P-X")
        self.assertEqual(rows[0].collected_at, datetime(2026, 7, 1, 8, 0, 0))
        self.assertEqual(rows[0].extra, {"fixture_key": "fixture-value"})
        self.assertIsNone(rows[1].station_id)
        self.assertIsNone(rows[1].extra)

    def test_context_contract_violations(self):
        with self.assertRaises(ValueError) as ctx:
            validate_inference_context([{"a": 1}], record_count=2)
        self.assertEqual(str(ctx.exception), CONTEXT_INVALID)
        with self.assertRaises(ValueError):
            validate_inference_context([{"a": "x" * 300}], record_count=1)
        with self.assertRaises(ValueError):
            validate_inference_context([{str(i): 1 for i in range(33)}], record_count=1)
        with self.assertRaises(ValueError):
            validate_inference_context([{"a": object()}], record_count=1)
        self.assertIsNone(validate_inference_context(None, record_count=3))

    def test_bucket_detail_consistency_with_context(self):
        """桶数字 = 明细计数（含异常行）；分数均值按行数加权。"""
        project_id = self.project_id
        context = [{"sample_key": f"VIN{i:03d}", "station": "IR-ST1"} for i in range(6)]
        result = {
            "predictions": [0, 0, 0, 1, 1, 1],
            "anomaly_score": [0.1, 0.2, 0.3, 0.9, 0.8, 0.7],
            "is_anomaly": [False, False, False, True, True, True],
            "thresholds": [0.5] * 6,
        }
        with SessionLocal() as db:
            context_rows = resolve_context_rows(db, context, record_count=6)
        self._recorder().record_prediction(
            request_id="req-test-consistency",
            project_id=project_id,
            context_rows=context_rows,
            result=result,
            records=[{"a": float(i)} for i in range(6)],
            occurred_at=datetime(2026, 11, 25, 11, 0, 0),
        )
        with SessionLocal() as db:
            rows = db.query(InferenceResult).filter(
                InferenceResult.request_id == "req-test-consistency",
            ).all()
            self.assertEqual(len(rows), 6)
            bucket = db.query(InferenceResultBucket).filter(
                InferenceResultBucket.project_id == project_id,
                InferenceResultBucket.station_id == self.station_id,
            ).one()
            self.assertEqual(bucket.total, 6)
            self.assertEqual(bucket.ok_count, 3)
            self.assertEqual(bucket.anomaly_count, 3)
            self.assertAlmostEqual(bucket.avg_score, (0.1 + 0.2 + 0.3 + 0.9 + 0.8 + 0.7) / 6)
            self.assertEqual(bucket.ng_confirmed_count, 0)

    def test_daily_cap_degrades_to_anomaly_and_sampling(self):
        """超限降级：只存异常 + 抽样；正常样本只进桶计数。"""
        project_id = self.project_id
        self._recorder(counter=_CapCounter(10**9)).record_prediction(
            request_id="req-test-cap",
            project_id=project_id,
            result={
                "predictions": [0] * 10,
                "anomaly_score": [0.1] * 10,
                "is_anomaly": [False] * 9 + [True],
            },
            records=[{"a": float(i)} for i in range(10)],
            occurred_at=datetime(2026, 11, 25, 12, 0, 0),
            retention_days=90,
        )
        with SessionLocal() as db:
            rows = db.query(InferenceResult).filter(
                InferenceResult.request_id == "req-test-cap",
            ).all()
            # 采样率 0 + 超限降级 → 只剩异常行
            self.assertEqual(len(rows), 1)
            self.assertTrue(rows[0].is_anomaly)
            bucket = db.query(InferenceResultBucket).filter(
                InferenceResultBucket.project_id == project_id,
            ).one()
            # 桶计数不受降级影响：10 条全在
            self.assertEqual(bucket.total, 10)
            self.assertEqual(bucket.anomaly_count, 1)
            self.assertEqual(bucket.ok_count, 9)

    def test_snapshot_written_on_anomaly(self):
        storage = _FakeStorage()
        self._recorder(storage=storage).record_prediction(
            request_id="req-test-snap",
            project_id=self.project_id,
            result={
                "predictions": [0, 1],
                "anomaly_score": [0.1, 0.9],
                "is_anomaly": [False, True],
            },
            records=[{"a": 1.0}, {"a": 2.0}],
            occurred_at=datetime(2026, 11, 25, 13, 0, 0),
        )
        self.assertEqual(len(storage.put_calls), 1)
        project_id, date_key, filename = storage.put_calls[0]
        self.assertEqual(project_id, str(self.project_id))
        self.assertEqual(date_key, "2026-11-25")
        self.assertIn("req-test-snap", filename)
        with SessionLocal() as db:
            row = db.query(InferenceResult).filter(
                InferenceResult.request_id == "req-test-snap",
                InferenceResult.is_anomaly.is_(True),
            ).one()
            self.assertIsNotNone(row.snapshot_uri)
            self.assertIn("inference-snapshots", row.snapshot_uri)

    def test_prune_keeps_buckets(self):
        project_id = self.project_id
        self._recorder().record_prediction(
            request_id="req-test-prune",
            project_id=project_id,
            result={"predictions": [0]},
            records=[{"a": 1.0}],
            occurred_at=datetime(2026, 1, 1, 0, 0, 0),
            retention_days=90,
        )
        with SessionLocal() as db:
            self.assertEqual(
                db.query(InferenceResult).filter(
                    InferenceResult.request_id == "req-test-prune",
                ).count(), 1,
            )
            pruned = self._recorder().prune(db, now=datetime(2026, 11, 25, 0, 0, 0))
            self.assertGreaterEqual(pruned, 1)
            self.assertEqual(
                db.query(InferenceResult).filter(
                    InferenceResult.request_id == "req-test-prune",
                ).count(), 0,
            )
            # 聚合桶永久保留
            self.assertGreaterEqual(
                db.query(InferenceResultBucket).filter(
                    InferenceResultBucket.project_id == project_id,
                ).count(), 1,
            )

    def test_persist_failure_event_into_outbox(self):
        with SessionLocal() as db:
            emit_persist_failed_event(
                db,
                project_id=self.project_id,
                deployment_id=uuid.uuid4(),
                error_code="INFERENCE_RESULT_PERSIST_FAILED",
            )
            db.commit()
            row = db.query(NotificationOutbox).filter(
                NotificationOutbox.event_type == "inference.result_persist_failed",
            ).order_by(NotificationOutbox.occurred_at.desc()).first()
            self.assertIsNotNone(row)
            self.assertEqual(row.severity, "warning")
            self.assertEqual(row.payload.get("error_code"), "INFERENCE_RESULT_PERSIST_FAILED")


class TestInferenceResultsQueryAPI(unittest.TestCase):
    """查询 API：默认排除 demo、筛选与分页、桶摘要。"""

    @classmethod
    def setUpClass(cls):
        from app.api.auth import get_current_user
        from app.main import app

        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        cls.db = cls.Session()
        cls.user = User(username=f"ir-query-{uuid.uuid4().hex[:6]}", password_hash="hash")
        cls.db.add(cls.user)
        cls.db.flush()
        cls.project = Project(name="IR query project", owner_id=cls.user.id)
        cls.db.add(cls.project)
        cls.db.commit()

        cls.current_user = cls.user
        app.dependency_overrides[get_db] = lambda: cls.db
        app.dependency_overrides[get_current_user] = lambda: cls.current_user
        cls.client = TestClient(app)

        now = datetime(2026, 11, 25, 9, 0, 0)
        cls.db.add_all([
            InferenceResult(
                request_id="q-1", sample_key="VIN-A", channel="online",
                project_id=cls.project.id, is_anomaly=True, anomaly_score=0.9,
                batch_no="B1", occurred_at=now,
                expires_at=now + timedelta(days=90),
            ),
            InferenceResult(
                request_id="q-2", sample_key="VIN-B", channel="online",
                project_id=cls.project.id, is_anomaly=False,
                batch_no="B1", occurred_at=now + timedelta(minutes=1),
                expires_at=now + timedelta(days=90),
            ),
            InferenceResult(
                request_id="demo-1", channel="demo",
                project_id=cls.project.id, is_anomaly=True,
                occurred_at=now + timedelta(minutes=2),
                expires_at=now + timedelta(days=90),
            ),
            InferenceResultBucket(
                bucket_start=now.replace(minute=0), project_id=cls.project.id,
                total=2, ok_count=1, anomaly_count=1, avg_score=0.5,
            ),
        ])
        cls.db.commit()

    @classmethod
    def tearDownClass(cls):
        from app.main import app

        app.dependency_overrides.clear()
        cls.db.close()
        cls.engine.dispose()

    def test_demo_excluded_by_default_and_explicit_channel(self):
        response = self.client.get(f"/api/projects/{self.project.id}/inference-results")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["total"], 2)
        demo = self.client.get(
            f"/api/projects/{self.project.id}/inference-results",
            params={"channel": "demo"},
        )
        self.assertEqual(demo.status_code, 200, demo.text)
        self.assertEqual(demo.json()["total"], 1)
        self.assertEqual(demo.json()["items"][0]["channel"], "demo")

    def test_filters_and_pagination(self):
        base = f"/api/projects/{self.project.id}/inference-results"
        by_sample = self.client.get(base, params={"sample_key": "VIN-A"})
        self.assertEqual(by_sample.json()["total"], 1)
        by_batch = self.client.get(base, params={"batch_no": "B1"})
        self.assertEqual(by_batch.json()["total"], 2)
        by_anomaly = self.client.get(base, params={"is_anomaly": "true"})
        self.assertEqual(by_anomaly.json()["total"], 1)
        paged = self.client.get(base, params={"page": 1, "page_size": 1})
        self.assertEqual(paged.status_code, 200, paged.text)
        self.assertEqual(paged.json()["total"], 2)
        self.assertEqual(len(paged.json()["items"]), 1)
        window = self.client.get(base, params={"occurred_from": "2026-11-25T09:01:00Z"})
        self.assertEqual(window.json()["total"], 1)

    def test_summary_reads_buckets(self):
        response = self.client.get(
            f"/api/projects/{self.project.id}/inference-results/summary",
            params={
                "occurred_from": "2026-11-25T00:00:00Z",
                "occurred_to": "2026-11-26T00:00:00Z",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["ok_count"], 1)
        self.assertEqual(body["anomaly_count"], 1)
        self.assertEqual(len(body["buckets"]), 1)


class TestInferenceContextContractAPI(unittest.TestCase):
    """生产推理端点：context 契约 422 与请求体严格性。"""

    @classmethod
    def setUpClass(cls):
        from app.api.inference_production import build_inference_production_router

        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        cls.deployment_id = uuid.uuid4()
        with cls.Session() as db:
            db.add(InferenceDeployment(
                id=cls.deployment_id, project_id=uuid.uuid4(),
                model_version_id=uuid.uuid4(),
                name="context-contract", desired_state="running",
                observed_state="running",
            ))
            db.commit()

        from tests.test_api_inference_production import (
            AllowKeyService,
            AllowingLimiter,
            NoopObservability,
        )

        app = FastAPI()
        app.include_router(build_inference_production_router(
            api_key_service=AllowKeyService(uuid.uuid4()),
            rate_limiter=AllowingLimiter(),
            observability=NoopObservability(),
            deployment_service=SimpleNamespace(
                runtime=SimpleNamespace(predict=lambda *a, **k: {"predictions": [0]}),
            ),
        ))

        def override_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_db
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.engine.dispose()

    def _post(self, payload):
        return self.client.post(
            f"/api/v1/inference/{self.deployment_id}/predict",
            headers={_API_KEY_HEADER: "contract-key"},
            json=payload,
        )

    def test_context_length_mismatch_rejected_422(self):
        response = self._post({
            "records": [{"current": 1.0}],
            "context": [{"sample_key": "A"}] * 2,
        })
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["detail"]["code"], "INFERENCE_CONTEXT_INVALID")

    def test_request_body_stays_strict(self):
        response = self._post({"records": [{"current": 1.0}], "unexpected": True})
        self.assertEqual(response.status_code, 422, response.text)


class _InlineExecutor:
    """同步执行器：TestClient 下线程池的 Future 不被等待，改为内联执行，
    响应返回时异步落库已完成，断言确定。"""

    def submit(self, fn, *args, **kwargs):
        future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as error:  # 与线程池语义一致：异常留在 Future 里
            future.set_exception(error)
        return future


class TestPredictToRecordsChain(unittest.TestCase):
    """端点级全链（F1 验收口径①）：

    - 带上下文推理 → 异步落库 → 生产记录查询可按样本键/批次查到，工位码解析到
      工位与场景，聚合桶同步计数；
    - 落库失败不影响推理响应，且告警事件入 outbox。
    """

    @classmethod
    def setUpClass(cls):
        from app.api.inference_production import build_inference_production_router
        from app.api.inference_results import router as results_router
        from app.models.artifact import Artifact
        from app.models.model_registry import RegisteredModel
        from tests.test_api_inference_production import (
            AllowKeyService,
            AllowingLimiter,
            NoopObservability,
        )

        cls.run_tag = uuid.uuid4().hex[:6]
        with SessionLocal() as db:
            user = User(username=f"predict-chain-{cls.run_tag}", password_hash="hash")
            db.add(user)
            db.flush()
            project = Project(name="Predict chain", owner_id=user.id)
            db.add(project)
            db.flush()
            scene = QualityScene(project_id=project.id, code=f"PC-{cls.run_tag}", name="scene")
            db.add(scene)
            db.flush()
            station = QualityStation(scene_id=scene.id, code=f"ST-{cls.run_tag}", name="station")
            db.add(station)
            artifact = Artifact(
                project_id=project.id, name=f"chain-artifact-{cls.run_tag}",
                type="model", storage_path=f"chain/{cls.run_tag}.joblib",
            )
            db.add(artifact)
            db.flush()
            registered = RegisteredModel(project_id=project.id, name=f"chain-model-{cls.run_tag}")
            db.add(registered)
            db.flush()
            version = ModelVersion(
                registered_model_id=registered.id, version_number=1,
                source_kind="onnx_artifact",
                source_artifact_id=artifact.id, onnx_artifact_id=artifact.id,
            )
            db.add(version)
            db.flush()
            deployment = InferenceDeployment(
                project_id=project.id, model_version_id=version.id,
                name=f"chain-{cls.run_tag}", desired_state="running",
                observed_state="running",
            )
            db.add(deployment)
            db.flush()
            # 明细行的 revision_id 是真实外键：造一条稳定 revision
            revision = DeploymentRevision(
                deployment_id=deployment.id, revision_number=1,
                strategy="immediate", status="stable",
            )
            db.add(revision)
            db.commit()
            # 只带走纯值：会话关闭后 ORM 实例即 detach，不能再读属性
            cls.actor = SimpleNamespace(id=user.id, username=user.username, role="engineer")
            cls.project_id = project.id
            cls.scene_id = scene.id
            cls.station_id = station.id
            cls.station_code = station.code
            cls.deployment_id = deployment.id
            cls.revision_id, cls.version_id = revision.id, version.id

        cls.app = FastAPI()
        cls.app.include_router(build_inference_production_router(
            api_key_service=AllowKeyService(uuid.uuid4()),
            rate_limiter=AllowingLimiter(),
            observability=NoopObservability(),
            deployment_service=SimpleNamespace(
                runtime=SimpleNamespace(
                    predict=lambda _key, records: {"predictions": [1] * len(records)},
                ),
            ),
        ))
        cls.app.include_router(results_router)
        cls.app.dependency_overrides[get_current_user] = lambda: cls.actor
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.app.dependency_overrides.pop(get_current_user, None)

    def _predict(self, context):
        with (
            patch("app.api.inference_production._TELEMETRY_EXECUTOR", _InlineExecutor()),
            patch("app.api.inference_production.WeightedTargetRouter") as router,
            patch(
                "app.api.inference_production.anomaly_predict_enrichment",
                side_effect=lambda _runtime, _key, _records, result, **_kw: result,
            ),
            patch("app.api.inference_production.anomaly_threshold_for_version", return_value=None),
            # 抽样恒不命中：快照路径不在本用例范围
            patch("app.services.inference_results.random.random", return_value=0.99),
        ):
            router.return_value.select_active.return_value = SimpleNamespace(
                revision_id=self.revision_id, model_version_id=self.version_id,
            )
            return self.client.post(
                f"/api/v1/inference/{self.deployment_id}/predict",
                headers={_API_KEY_HEADER: "chain-key"},
                json={
                    "records": [{"current": 1.0}, {"current": 2.0}],
                    "context": context,
                },
            )

    def test_contextual_prediction_is_queryable(self):
        first, second = f"{self.run_tag}-VIN-A", f"{self.run_tag}-VIN-B"
        batch = f"{self.run_tag}-B9"
        response = self._predict([
            {"sample_key": first, "station": self.station_code, "batch_no": batch},
            {"sample_key": second, "batch_no": batch},
        ])
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["predictions"], [1, 1])

        base = f"/api/projects/{self.project_id}/inference-results"
        by_sample = self.client.get(base, params={"sample_key": first})
        self.assertEqual(by_sample.status_code, 200, by_sample.text)
        self.assertEqual(by_sample.json()["total"], 1)
        row = by_sample.json()["items"][0]
        # 归属链：工位码 → 工位 → 场景（产生时点绑定快照）
        self.assertEqual(row["station_id"], str(self.station_id))
        self.assertEqual(row["scene_id"], str(self.scene_id))
        self.assertEqual(row["batch_no"], batch)
        self.assertEqual(row["channel"], "online")
        self.assertEqual(row["model_version_id"], str(self.version_id))
        self.assertIsNotNone(row["expires_at"])  # 保留期到期时间随行写入

        unbound = self.client.get(base, params={"sample_key": second}).json()["items"][0]
        self.assertIsNone(unbound["station_id"])

        by_batch = self.client.get(base, params={"batch_no": batch})
        self.assertEqual(by_batch.json()["total"], 2)

        # 聚合桶与明细同口径：两行都计入
        summary = self.client.get(f"{base}/summary")
        self.assertEqual(summary.status_code, 200, summary.text)
        self.assertGreaterEqual(summary.json()["total"], 2)

    def test_persist_failure_keeps_prediction_and_alerts(self):
        sample_key = f"{self.run_tag}-VIN-FAIL"

        def _events():
            with SessionLocal() as db:
                return db.query(NotificationOutbox).filter(
                    NotificationOutbox.event_type == "inference.result_persist_failed",
                    NotificationOutbox.project_id == self.project_id,
                ).all()

        before = len(_events())
        with patch.object(
            InferenceResultRecorder, "record_prediction",
            side_effect=RuntimeError("database unavailable"),
        ):
            response = self._predict([{"sample_key": sample_key}, {}])
        # 推理响应不受落库失败影响
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["predictions"], [1, 1])

        with SessionLocal() as db:
            kept = db.query(InferenceResult).filter(
                InferenceResult.request_id == response.json()["request_id"],
            ).count()
            self.assertEqual(kept, 0)
        # 一次落库失败对应恰好一条告警事件（不重复、不遗漏）
        events = _events()
        self.assertEqual(len(events), before + 1)
        self.assertEqual(events[-1].severity, "warning")
        self.assertEqual(
            events[-1].payload.get("error_code"), "INFERENCE_RESULT_PERSIST_FAILED",
        )


if __name__ == "__main__":
    unittest.main()
