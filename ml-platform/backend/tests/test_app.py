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


class TestModels(unittest.TestCase):
    """Database model relationship tests."""

    @classmethod
    def setUpClass(cls):
        from app.database import Base, engine, SessionLocal
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA foreign_keys = ON")
            conn.commit()
        Base.metadata.create_all(bind=engine)
        cls.SessionLocal = SessionLocal

    @classmethod
    def tearDownClass(cls):
        from app.database import Base, engine
        Base.metadata.drop_all(bind=engine)

    def setUp(self):
        self.session = self.SessionLocal()

    def tearDown(self):
        self.session.close()

    def test_all_models_create_and_relate(self):
        """Create instances of all models and verify foreign-key relationships."""
        from app.models import User, Project, Workflow, WorkflowNode, WorkflowEdge, WorkflowRun, NodeRun, Artifact

        user = User(username="alice", password_hash="hashed_pw", role="engineer")
        self.session.add(user)
        self.session.flush()

        project = Project(name="Demo Project", description="A test project", owner_id=user.id)
        self.session.add(project)
        self.session.flush()

        workflow = Workflow(
            project_id=project.id,
            name="Test Workflow",
            description="A test workflow",
            type="free",
            is_template=False,
            created_by=user.id,
        )
        self.session.add(workflow)
        self.session.flush()

        node_a = WorkflowNode(
            workflow_id=workflow.id,
            operator_id="csv_reader",
            label="Read CSV",
            position_x=100.0,
            position_y=200.0,
            params={"file": "data.csv"},
        )
        node_b = WorkflowNode(
            workflow_id=workflow.id,
            operator_id="row_filter",
            label="Filter Rows",
            position_x=300.0,
            position_y=200.0,
            params={"condition": "col > 5"},
        )
        self.session.add_all([node_a, node_b])
        self.session.flush()

        edge = WorkflowEdge(
            workflow_id=workflow.id,
            source_node_id=node_a.id,
            source_port="default",
            target_node_id=node_b.id,
            target_port="input",
        )
        self.session.add(edge)
        self.session.flush()

        run = WorkflowRun(
            workflow_id=workflow.id,
            status="running",
            triggered_by=user.id,
        )
        self.session.add(run)
        self.session.flush()

        node_run = NodeRun(
            run_id=run.id,
            node_id=node_a.id,
            status="completed",
            output_meta={"rows": 100},
            preview_data="col1,col2\n1,2\n3,4",
        )
        self.session.add(node_run)
        self.session.flush()

        artifact = Artifact(
            project_id=project.id,
            name="output.parquet",
            type="dataset",
            storage_path="/data/projects/demo/output.parquet",
            file_size=2048,
            format="parquet",
            metadata_={"schema": ["col1", "col2"]},
        )
        self.session.add(artifact)
        self.session.flush()

        self.assertIn(project, user.projects)
        self.assertEqual(project.owner, user)
        self.assertIn(workflow, user.created_workflows)
        self.assertEqual(workflow.created_by_user, user)
        self.assertIn(run, user.triggered_runs)
        self.assertEqual(run.triggered_by_user, user)
        self.assertIn(workflow, project.workflows)
        self.assertIn(artifact, project.artifacts)
        self.assertEqual(workflow.project, project)
        self.assertEqual(artifact.project, project)
        self.assertIn(node_a, workflow.nodes)
        self.assertIn(node_b, workflow.nodes)
        self.assertIn(edge, workflow.edges)
        self.assertIn(run, workflow.runs)
        self.assertEqual(node_a.workflow, workflow)
        self.assertEqual(node_b.workflow, workflow)
        self.assertEqual(edge.workflow, workflow)
        self.assertEqual(run.workflow, workflow)
        self.assertIn(edge, node_a.outgoing_edges)
        self.assertIn(edge, node_b.incoming_edges)
        self.assertEqual(edge.source_node, node_a)
        self.assertEqual(edge.target_node, node_b)
        self.assertIn(node_run, node_a.node_runs)
        self.assertEqual(node_run.node, node_a)
        self.assertIn(node_run, run.node_runs)
        self.assertEqual(node_run.run, run)


if __name__ == "__main__":
    unittest.main()
