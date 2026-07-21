import unittest

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


if __name__ == "__main__":
    unittest.main()
