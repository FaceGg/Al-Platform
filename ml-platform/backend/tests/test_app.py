import unittest

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)


class TestHealth(unittest.TestCase):
    """Health endpoint tests."""

    def test_health_returns_ok(self):
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data, {"status": "ok"})


class TestConfig(unittest.TestCase):
    """Configuration tests."""

    def test_default_database_url(self):
        self.assertEqual(settings.database_url, "sqlite:///./ml_platform.db")

    def test_default_secret_key(self):
        self.assertEqual(settings.secret_key, "change-me-in-production")

    def test_default_algorithm(self):
        self.assertEqual(settings.algorithm, "HS256")

    def test_default_token_expire(self):
        self.assertEqual(settings.access_token_expire_minutes, 1440)


class TestCORSMiddleware(unittest.TestCase):
    """CORS middleware tests."""

    def test_cors_preflight_headers(self):
        response = client.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://localhost:3000",
        )
        self.assertEqual(
            response.headers.get("access-control-allow-credentials"),
            "true",
        )


if __name__ == "__main__":
    unittest.main()