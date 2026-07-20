import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.auth import create_access_token
from app.database import Base, get_db
from app.main import app as platform_app
from app.models.experiment import Experiment
from app.models.project import Project
from app.models.training import TrainingJob
from app.models.user import User
from app.tensorboard_gateway.app import app as gateway_app
from app.tensorboard_gateway.processes import (
    SessionPathInvalid,
    SessionRunMismatch,
    TensorBoardProcessManager,
)
from app.tensorboard_gateway.tokens import SessionSigner, SessionTokenInvalid


class MutableClock:
    def __init__(self, value=1000):
        self.value = value

    def __call__(self):
        return self.value


class FakeProcess:
    def __init__(self):
        self.terminated = False
        self.killed = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True
        self.terminated = True


class TestSessionSigner(unittest.TestCase):
    def test_valid_token_tampering_and_expiry(self):
        clock = MutableClock()
        signer = SessionSigner("x" * 32, clock=clock)
        token = signer.issue(
            session_id="s1",
            run_id="r1",
            relative_logdir="p1/r1",
            expires_at=clock() + 60,
        )
        claims = signer.verify(token)
        self.assertEqual(claims.run_id, "r1")
        self.assertEqual(claims.relative_logdir, "p1/r1")

        with self.assertRaises(SessionTokenInvalid):
            signer.verify(token + "tampered")
        clock.value += 60
        with self.assertRaises(SessionTokenInvalid):
            signer.verify(token)


class TestTensorBoardProcessManager(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.clock = MutableClock()
        self.calls = []

        def process_factory(command, **kwargs):
            process = FakeProcess()
            self.calls.append((command, kwargs, process))
            return process

        self.manager = TensorBoardProcessManager(
            Path(self.temporary.name),
            idle_timeout_seconds=30,
            clock=self.clock,
            process_factory=process_factory,
            port_allocator=lambda: 43210,
        )

    def tearDown(self):
        self.manager.close()
        self.temporary.cleanup()

    def test_path_traversal_and_absolute_paths_are_rejected(self):
        for value in ("../other-project", "/absolute/run", "p1/../../other", "p1\\r1"):
            with self.subTest(value=value):
                with self.assertRaises(SessionPathInvalid):
                    self.manager.resolve_logdir(value)

    def test_process_is_reused_only_for_matching_run_and_fixed_root(self):
        first = self.manager.get_or_start(
            session_id="s1",
            run_id="r1",
            relative_logdir="p1/r1",
            expires_at=self.clock() + 60,
        )
        second = self.manager.get_or_start(
            session_id="s1",
            run_id="r1",
            relative_logdir="p1/r1",
            expires_at=self.clock() + 60,
        )
        self.assertIs(first, second)
        self.assertEqual(len(self.calls), 1)
        command, kwargs, _process = self.calls[0]
        self.assertIn("127.0.0.1", command)
        self.assertIn(str(Path(self.temporary.name).resolve() / "p1" / "r1"), command)
        self.assertNotIn("shell", kwargs)
        with self.assertRaises(SessionRunMismatch):
            self.manager.get_or_start(
                session_id="s1",
                run_id="r2",
                relative_logdir="p1/r2",
                expires_at=self.clock() + 60,
            )

    def test_idle_or_expired_processes_are_terminated(self):
        session = self.manager.get_or_start(
            session_id="s1",
            run_id="r1",
            relative_logdir="p1/r1",
            expires_at=self.clock() + 120,
        )
        self.clock.value += 31
        self.assertEqual(self.manager.cleanup(), 1)
        self.assertTrue(session.process.terminated)


class TestTensorBoardPlatformAuthorization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.Session = sessionmaker(bind=cls.engine)
        Base.metadata.create_all(cls.engine)
        with cls.Session() as db:
            owner = User(username="tensorboard-owner", password_hash="hash")
            other = User(username="tensorboard-other", password_hash="hash")
            db.add_all([owner, other])
            db.flush()
            project = Project(name="TensorBoard", owner_id=owner.id)
            db.add(project)
            db.flush()
            experiment = Experiment(
                project_id=project.id,
                created_by=owner.id,
                name="TensorBoard",
                mlflow_experiment_id="tb-experiment",
            )
            db.add(experiment)
            db.flush()
            job = TrainingJob(
                project_id=project.id,
                user_id=owner.id,
                experiment_id=experiment.id,
                dataset_artifact_id=uuid.uuid4(),
                name="tb-job",
                status="completed",
                mlflow_run_id="run-safe-1",
            )
            db.add(job)
            db.commit()
            cls.owner_id = owner.id
            cls.other_id = other.id
            cls.job_id = job.id

        def override_db():
            db = cls.Session()
            try:
                yield db
            finally:
                db.close()

        platform_app.dependency_overrides[get_db] = override_db
        cls.clock = MutableClock()
        cls.signer = SessionSigner("s" * 32, clock=cls.clock)
        platform_app.state.tensorboard_signer = cls.signer
        platform_app.state.tensorboard_session_ttl_seconds = 60

        async def proxy_handler(claims, path, _request):
            return JSONResponse({"run_id": claims.run_id, "path": path})

        platform_app.state.tensorboard_proxy_handler = proxy_handler
        cls.client = TestClient(platform_app)
        cls.owner_headers = cls._headers(cls.owner_id)
        cls.other_headers = cls._headers(cls.other_id)

    @classmethod
    def tearDownClass(cls):
        platform_app.dependency_overrides.pop(get_db, None)
        for name in (
            "tensorboard_signer",
            "tensorboard_session_ttl_seconds",
            "tensorboard_proxy_handler",
        ):
            if hasattr(platform_app.state, name):
                delattr(platform_app.state, name)
        cls.engine.dispose()

    @staticmethod
    def _headers(user_id):
        return {"Authorization": "Bearer " + create_access_token({"sub": str(user_id)})}

    def test_owner_receives_short_lived_backend_proxy_and_other_user_gets_404(self):
        response = self.client.post(
            f"/api/training/jobs/{self.job_id}/tensorboard-session",
            headers=self.owner_headers,
        )
        self.assertEqual(response.status_code, 201, response.text)
        payload = response.json()
        self.assertTrue(payload["url"].startswith("/api/training/tensorboard/"))
        claims = self.signer.verify(payload["token"])
        self.assertEqual(claims.run_id, "run-safe-1")
        self.assertNotIn(str(Path.cwd()), claims.relative_logdir)

        hidden = self.client.post(
            f"/api/training/jobs/{self.job_id}/tensorboard-session",
            headers=self.other_headers,
        )
        self.assertEqual(hidden.status_code, 404)

        proxied = self.client.get(payload["url"] + "data/plugin/scalars")
        self.assertEqual(proxied.status_code, 200)
        self.assertEqual(proxied.json()["run_id"], "run-safe-1")
        tampered = self.client.get(payload["url"].replace(payload["token"], payload["token"] + "x"))
        self.assertEqual(tampered.status_code, 403)


class TestGatewayImport(unittest.TestCase):
    def test_gateway_app_exists(self):
        self.assertIsNotNone(gateway_app)


if __name__ == "__main__":
    unittest.main()
