import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.inference_production import build_inference_production_router


class TestProductionInferenceApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = FastAPI()
        cls.app.include_router(build_inference_production_router())
        cls.client = TestClient(cls.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

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

    def test_prediction_request_schema_rejects_unknown_fields(self):
        schemas = self.app.openapi().get("components", {}).get("schemas", {})
        request_schemas = [
            schema for schema in schemas.values()
            if "records" in schema.get("properties", {})
        ]
        self.assertTrue(request_schemas, "production predict request schema is missing")
        self.assertTrue(all(
            schema.get("additionalProperties") is False
            for schema in request_schemas
        ))

    def test_prediction_response_exposes_revision_and_actual_model_version(self):
        schemas = self.app.openapi().get("components", {}).get("schemas", {})
        response_schemas = [
            schema for schema in schemas.values()
            if {"revision_id", "model_version_id"}.issubset(schema.get("properties", {}))
        ]
        self.assertTrue(response_schemas, "production predict response schema is missing")


if __name__ == "__main__":
    unittest.main()
