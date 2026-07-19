import tempfile
import threading
import unittest
import uuid
from pathlib import Path

import joblib
import numpy as np
from fastapi.testclient import TestClient
from sklearn.linear_model import LogisticRegression

from app.inference_runtime.app import create_runtime_app
from app.inference_runtime.runtime import RuntimeRegistry
from app.services.onnx_conversion import convert_platform_joblib
from app.storage.local import LocalStorage


class TestInferenceRuntime(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        source = self.root / "source.joblib"
        onnx_path = self.root / "classifier.onnx"
        features = np.asarray([
            [0.0, 0.0],
            [0.2, 0.1],
            [8.0, 9.0],
            [9.0, 8.5],
        ])
        target = np.asarray([0, 0, 1, 1])
        model = LogisticRegression(random_state=0).fit(features, target)
        joblib.dump({
            "model": model,
            "feature_schema": [
                {"name": "current", "dtype": "float64"},
                {"name": "voltage", "dtype": "float64"},
            ],
            "target_schema": {
                "name": "fault", "dtype": "int64", "task": "classification",
            },
        }, source)
        conversion = convert_platform_joblib(source, onnx_path)
        self.storage = LocalStorage(self.root / "storage")
        stored = self.storage.put(
            onnx_path,
            "project",
            "artifact",
            "classifier.onnx",
        )
        self.deployment_id = str(uuid.uuid4())
        self.version_id = str(uuid.uuid4())
        self.spec = {
            "deployment_id": self.deployment_id,
            "model_version_id": self.version_id,
            "version_number": 1,
            "storage_uri": stored.uri,
            "sha256": stored.sha256,
            "size": stored.size,
            "feature_schema": conversion.feature_schema,
            "output_schema": conversion.output_schema,
            "input_names": list(conversion.input_names),
            "output_names": list(conversion.output_names),
        }
        self.registry = RuntimeRegistry(self.storage)
        self.app = create_runtime_app(
            registry=self.registry,
            internal_token="runtime-secret-at-least-32-characters",
        )
        self.client = TestClient(self.app)
        self.headers = {
            "X-Inference-Internal-Token": "runtime-secret-at-least-32-characters",
        }

    def tearDown(self):
        self.client.close()
        self.temporary.cleanup()

    def test_internal_routes_require_token(self):
        missing = self.client.get("/internal/deployments")
        wrong = self.client.get(
            "/internal/deployments",
            headers={"X-Inference-Internal-Token": "wrong"},
        )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(missing.json()["detail"]["code"], "INFERENCE_UNAUTHORIZED")
        self.assertNotIn("runtime-secret", str(missing.json()))

    def test_load_and_unload_are_idempotent(self):
        first = self.client.put(
            f"/internal/deployments/{self.deployment_id}",
            json=self.spec,
            headers=self.headers,
        )
        second = self.client.put(
            f"/internal/deployments/{self.deployment_id}",
            json=self.spec,
            headers=self.headers,
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["already_loaded"])
        listing = self.client.get("/internal/deployments", headers=self.headers)
        self.assertEqual(listing.json()["items"][0]["model_version_id"], self.version_id)

        stopped = self.client.delete(
            f"/internal/deployments/{self.deployment_id}", headers=self.headers,
        )
        stopped_again = self.client.delete(
            f"/internal/deployments/{self.deployment_id}", headers=self.headers,
        )
        self.assertEqual(stopped.status_code, 200)
        self.assertTrue(stopped_again.json()["already_absent"])

    def test_conflicting_loaded_spec_is_rejected(self):
        self.client.put(
            f"/internal/deployments/{self.deployment_id}",
            json=self.spec,
            headers=self.headers,
        )
        conflicting = {**self.spec, "model_version_id": str(uuid.uuid4())}
        response = self.client.put(
            f"/internal/deployments/{self.deployment_id}",
            json=conflicting,
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(
            response.json()["detail"]["code"],
            "DEPLOYMENT_SPEC_CONFLICT",
        )

    def test_predict_orders_named_features_and_returns_probabilities(self):
        self.client.put(
            f"/internal/deployments/{self.deployment_id}",
            json=self.spec,
            headers=self.headers,
        )
        response = self.client.post(
            f"/internal/deployments/{self.deployment_id}/predict",
            json={"records": [
                {"voltage": 0.1, "current": 0.2},
                {"current": 9.0, "voltage": 8.5},
            ]},
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["deployment_id"], self.deployment_id)
        self.assertEqual(payload["model_version_id"], self.version_id)
        self.assertEqual(payload["version_number"], 1)
        self.assertEqual(payload["predictions"], [0, 1])
        self.assertEqual(len(payload["probabilities"]), 2)
        self.assertGreaterEqual(payload["duration_ms"], 0)

    def test_predict_rejects_missing_unknown_and_non_finite_values(self):
        self.client.put(
            f"/internal/deployments/{self.deployment_id}",
            json=self.spec,
            headers=self.headers,
        )
        invalid_records = [
            {"current": 1.0},
            {"current": 1.0, "voltage": 2.0, "force": 3.0},
        ]
        for record in invalid_records:
            with self.subTest(record=record):
                response = self.client.post(
                    f"/internal/deployments/{self.deployment_id}/predict",
                    json={"records": [record]},
                    headers=self.headers,
                )
                self.assertEqual(response.status_code, 422)
                self.assertEqual(
                    response.json()["detail"]["code"],
                    "INFERENCE_SCHEMA_MISMATCH",
                )
        non_finite = self.client.post(
            f"/internal/deployments/{self.deployment_id}/predict",
            content=b'{"records":[{"current":Infinity,"voltage":2.0}]}',
            headers={**self.headers, "Content-Type": "application/json"},
        )
        self.assertEqual(non_finite.status_code, 422)
        self.assertEqual(
            non_finite.json()["detail"]["code"],
            "INFERENCE_SCHEMA_MISMATCH",
        )

    def test_predict_enforces_record_and_body_limits(self):
        self.client.put(
            f"/internal/deployments/{self.deployment_id}",
            json=self.spec,
            headers=self.headers,
        )
        empty = self.client.post(
            f"/internal/deployments/{self.deployment_id}/predict",
            json={"records": []}, headers=self.headers,
        )
        too_many = self.client.post(
            f"/internal/deployments/{self.deployment_id}/predict",
            json={"records": [
                {"current": 1.0, "voltage": 2.0} for _ in range(101)
            ]},
            headers=self.headers,
        )
        oversized = self.client.post(
            f"/internal/deployments/{self.deployment_id}/predict",
            content=b'{"records":[]}' + b" " * (1024 * 1024),
            headers={**self.headers, "Content-Type": "application/json"},
        )
        self.assertEqual(empty.status_code, 413)
        self.assertEqual(too_many.status_code, 413)
        self.assertEqual(oversized.status_code, 413)

    def test_unload_does_not_invalidate_active_prediction_reference(self):
        loaded = self.registry.load(self.spec)
        entered = threading.Event()
        release = threading.Event()
        original_run = loaded.session.run

        class BlockingSession:
            def run(self, outputs, inputs):
                entered.set()
                release.wait(timeout=5)
                return original_run(outputs, inputs)

        object.__setattr__(loaded, "session", BlockingSession())
        result = {}

        def predict():
            result.update(self.registry.predict(
                self.deployment_id,
                [{"current": 9.0, "voltage": 8.5}],
            ))

        thread = threading.Thread(target=predict)
        thread.start()
        self.assertTrue(entered.wait(timeout=5))
        self.registry.unload(self.deployment_id)
        release.set()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result["predictions"], [1])


if __name__ == "__main__":
    unittest.main()
