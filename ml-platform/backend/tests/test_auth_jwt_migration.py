"""JWT library migration and token-boundary regression tests."""

from datetime import datetime, timedelta, timezone
import sys
import unittest
import uuid

sys.path.insert(0, ".")

from fastapi.testclient import TestClient

from app.api import auth
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.main import app
from app.models.user import User


Base.metadata.create_all(bind=engine)
client = TestClient(app)


class AuthJwtMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.username = "jwt-migration-user"
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == cls.username).first()
            if user is None:
                user = User(
                    username=cls.username,
                    password_hash=auth.pwd_context.hash("jwt-migration-password"),
                    role="engineer",
                )
                db.add(user)
                db.commit()
                db.refresh(user)
            cls.user_id = str(user.id)
        finally:
            db.close()

    def _token(self, *, algorithm: str | None = None, expires_at: datetime | None = None):
        payload = {
            "sub": self.user_id,
            "exp": expires_at or (datetime.now(timezone.utc) + timedelta(minutes=5)),
        }
        return auth.jwt.encode(
            payload,
            settings.resolved_secret_key.get_secret_value(),
            algorithm=algorithm or settings.algorithm,
        )

    def test_auth_module_uses_pyjwt(self):
        self.assertEqual(auth.jwt.__name__, "jwt")

    def test_issued_token_authenticates_its_subject(self):
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {auth.create_access_token({'sub': self.user_id})}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], self.user_id)

    def test_expired_token_is_rejected(self):
        response = client.get(
            "/api/auth/me",
            headers={
                "Authorization": f"Bearer {self._token(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))}"
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_signature_tampering_is_rejected(self):
        parts = self._token().split(".")
        parts[-1] = "A" * len(parts[-1])
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {'.'.join(parts)}"},
        )
        self.assertEqual(response.status_code, 401)

    def test_token_signed_with_a_different_algorithm_is_rejected(self):
        response = client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {self._token(algorithm='HS384')}"},
        )
        self.assertEqual(response.status_code, 401)

    def test_token_with_malformed_subject_is_rejected(self):
        for subject in ("not-a-uuid", ["not-a-uuid"]):
            with self.subTest(subject=subject), TestClient(
                app,
                raise_server_exceptions=False,
            ) as isolated_client:
                token = auth.jwt.encode(
                    {
                        "sub": subject,
                        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                    },
                    settings.resolved_secret_key.get_secret_value(),
                    algorithm=settings.algorithm,
                )
                response = isolated_client.get(
                    "/api/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
                self.assertEqual(response.status_code, 401, response.text)


if __name__ == "__main__":
    unittest.main()
