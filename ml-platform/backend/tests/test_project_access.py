import uuid
import unittest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


class TestRequestCorrelation(unittest.TestCase):
    def _client(self):
        from app.middleware.request_id import RequestIdMiddleware

        app = FastAPI()
        app.add_middleware(RequestIdMiddleware)

        @app.get("/request-id")
        def request_id(request: Request):
            return {"request_id": str(request.state.request_id)}

        return TestClient(app)

    def test_missing_request_id_is_generated_and_echoed(self):
        with self._client() as client:
            response = client.get("/request-id")

        request_id = uuid.UUID(response.json()["request_id"])
        self.assertEqual(response.headers["X-Request-ID"], str(request_id))

    def test_valid_request_id_is_preserved(self):
        request_id = uuid.uuid4()
        with self._client() as client:
            response = client.get(
                "/request-id",
                headers={"X-Request-ID": str(request_id)},
            )

        self.assertEqual(response.json()["request_id"], str(request_id))
        self.assertEqual(response.headers["X-Request-ID"], str(request_id))

    def test_invalid_request_id_is_replaced(self):
        with self._client() as client:
            response = client.get(
                "/request-id",
                headers={"X-Request-ID": "not-a-uuid"},
            )

        generated = uuid.UUID(response.json()["request_id"])
        self.assertNotEqual(str(generated), "not-a-uuid")
        self.assertEqual(response.headers["X-Request-ID"], str(generated))


class TestAuditRedaction(unittest.TestCase):
    def test_only_allowlisted_fields_are_kept_and_sensitive_values_are_redacted(self):
        from app.services.audit import redact_changes

        result = redact_changes(
            {
                "role": "editor",
                "password": "hidden",
                "nested": {"token": "hidden", "count": 2},
                "params": {"max_attempts": 3},
                "unlisted": "drop-me",
            },
            allowed={"role", "nested", "params", "password"},
        )

        self.assertEqual(
            result,
            {
                "role": "editor",
                "password": "[REDACTED]",
                "nested": {"token": "[REDACTED]", "count": 2},
                "params": {"max_attempts": 3},
            },
        )


if __name__ == "__main__":
    unittest.main()
