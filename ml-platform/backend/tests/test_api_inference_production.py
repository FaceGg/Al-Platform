import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.inference_production import build_inference_production_router
from app.database import Base, get_db
from app.models import artifact as artifact_models  # noqa: F401
from app.models import model_library as model_library_models  # noqa: F401
from app.models import project as project_models  # noqa: F401
from app.models import user as user_models  # noqa: F401
from app.models.model_registry import InferenceDeployment, ModelVersion
from app.services.inference_api_keys import InferenceApiKeyError
from app.services.inference_runtime_client import InferenceRuntimeClientError


class AllowKey:
    def __init__(self, key_id):
        self.id = key_id


class AllowKeyService:
    def __init__(self, key_id):
        self.key_id = key_id

    def verify(self, *_args, **_kwargs):
        return AllowKey(self.key_id)


class FailingKeyService:
    def __init__(self, code):
        self.code = code

    def verify(self, *_args, **_kwargs):
        raise InferenceApiKeyError(self.code)


class AllowingLimiter:
    def consume(self, *_args, **_kwargs):
        return SimpleNamespace(allowed=True)


class NoopObservability:
    def record_request(self, *_args, **_kwargs):
        return None


class FailingRuntime:
    def __init__(self, code):
        self.code = code

    def predict(self, *_args, **_kwargs):
        raise InferenceRuntimeClientError(self.code)


class RuntimeDeploymentService:
    def __init__(self, code):
        self.runtime = FailingRuntime(code)


class TestProductionInferenceApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(cls.engine)
        cls.Session = sessionmaker(bind=cls.engine, expire_on_commit=False)
        cls.app = FastAPI()
        cls.app.include_router(build_inference_production_router())

        def override_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        cls.app.dependency_overrides[get_db] = override_db
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.engine.dispose()

    def test_production_route_is_versioned_and_requires_api_key(self):
        routes = {
            (route.path, method)
            for route in self.app.routes
            for method in getattr(route, "methods", set())
        }
        self.assertIn(("/api/v1/inference/{deployment_id}/predict", "POST"), routes)
        response = self.client.post(
            "/api/v1/inference/00000000-0000-0000-0000-000000000001/predict",
            json={"records": [{"current": 1.0}]},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "INFERENCE_API_KEY_INVALID")

    def test_production_route_uses_the_frozen_api_key_header(self):
        operation = self.app.openapi()["paths"][
            "/api/v1/inference/{deployment_id}/predict"
        ]["post"]
        header_parameters = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
            if parameter.get("in") == "header"
        }
        self.assertIn("X-Inference-Api-Key", header_parameters)

    def test_invalid_supplied_api_key_has_stable_error(self):
        response = self.client.post(
            "/api/v1/inference/00000000-0000-0000-0000-000000000001/predict",
            headers={"X-Inference-Api-Key": "wpk_invalid"},
            json={"records": [{"current": 1.0}]},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "INFERENCE_API_KEY_INVALID")

    def test_prediction_request_schema_rejects_unknown_fields(self):
        operation = self.app.openapi()["paths"][
            "/api/v1/inference/{deployment_id}/predict"
        ]["post"]
        reference = operation["requestBody"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        schema_name = reference.rsplit("/", 1)[-1]
        schema = self.app.openapi()["components"]["schemas"][schema_name]
        self.assertEqual(schema.get("additionalProperties"), False)

    def test_prediction_response_exposes_revision_and_actual_model_version(self):
        operation = self.app.openapi()["paths"][
            "/api/v1/inference/{deployment_id}/predict"
        ]["post"]
        reference = operation["responses"]["200"]["content"]["application/json"][
            "schema"
        ]["$ref"]
        schema_name = reference.rsplit("/", 1)[-1]
        schema = self.app.openapi()["components"]["schemas"][schema_name]
        self.assertTrue({"revision_id", "model_version_id"}.issubset(schema["properties"]))

    def test_production_request_over_one_megabyte_is_rejected_before_parsing(self):
        deployment_id = uuid.uuid4()
        key_id = uuid.uuid4()
        db = self.Session()
        db.add(InferenceDeployment(
            id=deployment_id, project_id=uuid.uuid4(), model_version_id=uuid.uuid4(),
            name="oversize",
        ))
        db.commit()
        app = FastAPI()
        app.include_router(build_inference_production_router(
            api_key_service=AllowKeyService(key_id),
        ))
        app.dependency_overrides[get_db] = lambda: self.Session()
        client = TestClient(app)
        try:
            response = client.post(
                f"/api/v1/inference/{deployment_id}/predict",
                headers={"X-Inference-Api-Key": "mli_test", "Content-Length": str(1024 * 1024 + 1)},
                content=b"x" * (1024 * 1024 + 1),
            )
            self.assertEqual(response.status_code, 413, response.text)
        finally:
            client.close()

    def test_production_request_with_misleading_content_length_is_rejected(self):
        deployment_id = uuid.uuid4()
        key_id = uuid.uuid4()
        db = self.Session()
        db.add(InferenceDeployment(
            id=deployment_id, project_id=uuid.uuid4(), model_version_id=uuid.uuid4(),
            name="header-mismatch",
        ))
        db.commit()
        app = FastAPI()
        app.include_router(build_inference_production_router(
            api_key_service=AllowKeyService(key_id),
        ))
        app.dependency_overrides[get_db] = lambda: self.Session()
        client = TestClient(app)
        try:
            response = client.post(
                f"/api/v1/inference/{deployment_id}/predict",
                headers={"X-Inference-Api-Key": "mli_test", "Content-Length": "1"},
                content=b"x" * (1024 * 1024 + 1),
            )
            self.assertEqual(response.status_code, 413, response.text)
            self.assertEqual(
                response.json()["detail"]["code"], "INFERENCE_LIMIT_EXCEEDED",
            )
        finally:
            client.close()

    def test_runtime_error_codes_keep_their_public_statuses(self):
        cases = (
            ("INFERENCE_SCHEMA_MISMATCH", 422),
            ("INFERENCE_LIMIT_EXCEEDED", 413),
            ("DEPLOYMENT_NOT_READY", 409),
        )
        for code, expected_status in cases:
            with self.subTest(code=code):
                deployment_id = uuid.uuid4()
                model_version_id = uuid.uuid4()
                revision_id = uuid.uuid4()
                key_id = uuid.uuid4()
                db = self.Session()
                db.add(ModelVersion(
                    id=model_version_id,
                    registered_model_id=uuid.uuid4(),
                    version_number=1,
                    source_kind="onnx_artifact",
                    source_artifact_id=uuid.uuid4(),
                    onnx_artifact_id=uuid.uuid4(),
                    approval_status="approved",
                ))
                db.add(InferenceDeployment(
                    id=deployment_id,
                    project_id=uuid.uuid4(),
                    model_version_id=model_version_id,
                    name=f"runtime-{code.lower()}",
                    desired_state="running",
                    observed_state="running",
                ))
                db.commit()
                app = FastAPI()
                app.include_router(build_inference_production_router(
                    api_key_service=AllowKeyService(key_id),
                    rate_limiter=AllowingLimiter(),
                    observability=NoopObservability(),
                    deployment_service=RuntimeDeploymentService(code),
                ))
                app.dependency_overrides[get_db] = lambda: self.Session()
                client = TestClient(app)
                try:
                    with patch("app.api.inference_production.WeightedTargetRouter") as router:
                        router.return_value.select_active.return_value = SimpleNamespace(
                            revision_id=revision_id,
                            model_version_id=model_version_id,
                        )
                        response = client.post(
                            f"/api/v1/inference/{deployment_id}/predict",
                            headers={"X-Inference-Api-Key": "mli_test"},
                            json={"records": [{"current": 1.0}]},
                        )
                    self.assertEqual(response.status_code, expected_status, response.text)
                    self.assertEqual(response.json()["detail"]["code"], code)
                finally:
                    client.close()

    def test_public_api_key_errors_preserve_their_stable_code(self):
        deployment_id = uuid.uuid4()
        for code in ("INFERENCE_API_KEY_EXPIRED", "INFERENCE_API_KEY_REVOKED", "INFERENCE_API_KEY_OUT_OF_SCOPE"):
            with self.subTest(code=code):
                app = FastAPI()
                app.include_router(build_inference_production_router(
                    api_key_service=FailingKeyService(code),
                ))
                app.dependency_overrides[get_db] = lambda: self.Session()
                client = TestClient(app)
                try:
                    response = client.post(
                        f"/api/v1/inference/{deployment_id}/predict",
                        headers={"X-Inference-Api-Key": "mli_test"},
                        json={"records": [{"current": 1.0}]},
                    )
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.json()["detail"]["code"], code)
                finally:
                    client.close()


if __name__ == "__main__":
    unittest.main()
