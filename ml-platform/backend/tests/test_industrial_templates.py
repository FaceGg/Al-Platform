import unittest
import io
import uuid
from dataclasses import replace

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.workflow import Workflow, WorkflowNode
from app.templates.contract import (
    IndustrialTemplate,
    TemplateContractError,
    TemplateEdge,
    TemplateExpectedOutput,
    TemplateNode,
    validate_template,
)
from app.templates.industrial import INDUSTRIAL_TEMPLATES


class TestIndustrialTemplateContract(unittest.TestCase):
    def test_four_approved_templates_have_fault_contracts(self):
        self.assertEqual(set(INDUSTRIAL_TEMPLATES), {
            "weld_quality",
            "fault_parameter_analysis",
            "anomaly_detection",
            "full_ml_comparison",
        })
        for template in INDUSTRIAL_TEMPLATES.values():
            self.assertEqual(template.target_column, "Fault")
            self.assertIn("Fault", template.required_columns)
            self.assertNotIn("mlp_train", [node.operator_id for node in template.nodes])

    def test_all_industrial_templates_validate_against_registry(self):
        for template in INDUSTRIAL_TEMPLATES.values():
            validate_template(template)

    def test_templates_enable_imbalanced_fault_handling(self):
        for template_id in ("weld_quality", "fault_parameter_analysis", "full_ml_comparison"):
            template = INDUSTRIAL_TEMPLATES[template_id]
            split = next(node for node in template.nodes if node.operator_id == "train_test_split")
            self.assertEqual(split.params["target_column"], "Fault")
            self.assertTrue(split.params["stratify"])
        random_forests = [
            node for template in INDUSTRIAL_TEMPLATES.values() for node in template.nodes
            if node.operator_id == "random_forest_train"
        ]
        self.assertTrue(random_forests)
        self.assertTrue(all(node.params["class_weight"] == "balanced" for node in random_forests))

    def test_anomaly_template_reports_fault_comparison(self):
        template = INDUSTRIAL_TEMPLATES["anomaly_detection"]
        evaluator = next(node for node in template.nodes if node.operator_id == "anomaly_eval")
        self.assertEqual(evaluator.params["target_column"], "Fault")
        self.assertIn(TemplateExpectedOutput("evaluation", "metrics"), template.expected_outputs)

    def test_validator_rejects_unknown_operator_and_parameter(self):
        template = INDUSTRIAL_TEMPLATES["weld_quality"]
        unknown_operator = replace(
            template,
            nodes=(replace(template.nodes[0], operator_id="missing_operator"), *template.nodes[1:]),
        )
        with self.assertRaisesRegex(TemplateContractError, "TEMPLATE_OPERATOR_UNKNOWN"):
            validate_template(unknown_operator)

        train_index = next(
            index for index, node in enumerate(template.nodes)
            if node.operator_id == "random_forest_train"
        )
        nodes = list(template.nodes)
        nodes[train_index] = replace(nodes[train_index], params={"unknown": True})
        with self.assertRaisesRegex(TemplateContractError, "TEMPLATE_PARAM_INVALID"):
            validate_template(replace(template, nodes=tuple(nodes)))

    def test_validator_rejects_unknown_ports_and_outputs(self):
        template = INDUSTRIAL_TEMPLATES["weld_quality"]
        bad_edge = replace(template.edges[0], source_port="missing")
        with self.assertRaisesRegex(TemplateContractError, "TEMPLATE_PORT_UNKNOWN"):
            validate_template(replace(template, edges=(bad_edge, *template.edges[1:])))

        bad_output = TemplateExpectedOutput(node_key="evaluation", port="missing")
        with self.assertRaisesRegex(TemplateContractError, "TEMPLATE_OUTPUT_INVALID"):
            validate_template(replace(template, expected_outputs=(bad_output,)))

    def test_validator_rejects_duplicate_node_keys(self):
        template = INDUSTRIAL_TEMPLATES["weld_quality"]
        duplicate = replace(template.nodes[1], key=template.nodes[0].key)
        with self.assertRaisesRegex(TemplateContractError, "TEMPLATE_NODE_DUPLICATE"):
            validate_template(replace(template, nodes=(template.nodes[0], duplicate, *template.nodes[2:])))


class TestIndustrialTemplateAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()
        username = f"template_{uuid.uuid4().hex[:8]}"
        cls.client.post("/api/auth/register", json={
            "username": username, "password": "admin123", "role": "admin",
        })
        login = cls.client.post("/api/auth/login", data={
            "username": username, "password": "admin123",
        })
        cls.headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        project = cls.client.post(
            "/api/projects", json={"name": "Industrial Templates"}, headers=cls.headers,
        )
        cls.project_id = project.json()["id"]
        rows = ["Car Body,Welding Spot,Date,feature_a,feature_b,Fault"]
        rows.extend(
            f"{index // 5},{index % 5},2023-06-13,{index},{index % 5},{1 if index % 10 == 0 else 0}"
            for index in range(40)
        )
        upload = cls.client.post(
            f"/api/projects/{cls.project_id}/datasets/upload",
            files={"file": ("features.csv", io.BytesIO("\n".join(rows).encode()), "text/csv")},
            headers=cls.headers,
        )
        cls.artifact_id = upload.json()["artifact_id"]

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def test_list_and_detail_expose_industrial_metadata(self):
        listed = self.client.get("/api/templates", headers=self.headers)
        ids = {item["id"] for item in listed.json()["items"]}
        self.assertTrue(set(INDUSTRIAL_TEMPLATES).issubset(ids))
        detail = self.client.get("/api/templates/weld_quality", headers=self.headers).json()
        self.assertEqual(detail["target_column"], "Fault")
        self.assertIn("required_columns", detail)
        self.assertIn("expected_outputs", detail)

    def test_instantiate_uses_json_artifact_contract(self):
        response = self.client.post(
            "/api/templates/weld_quality/instantiate",
            json={
                "project_id": self.project_id,
                "dataset_artifact_id": self.artifact_id,
                "parameters": {"n_estimators": 20},
            },
            headers=self.headers,
        )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["template_id"], "weld_quality")
        self.assertEqual(response.json()["dataset_artifact_id"], self.artifact_id)
        with SessionLocal() as db:
            source = db.query(WorkflowNode).filter(
                WorkflowNode.workflow_id == uuid.UUID(response.json()["workflow_id"]),
                WorkflowNode.operator_id == "csv_import",
            ).one()
            self.assertTrue(source.params["file_path"].endswith(".csv"))

    def test_invalid_artifact_creates_no_workflow(self):
        with SessionLocal() as db:
            before = db.query(Workflow).filter(Workflow.project_id == uuid.UUID(self.project_id)).count()
        response = self.client.post(
            "/api/templates/weld_quality/instantiate",
            json={
                "project_id": self.project_id,
                "dataset_artifact_id": str(uuid.uuid4()),
                "parameters": {},
            },
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 400)
        with SessionLocal() as db:
            after = db.query(Workflow).filter(Workflow.project_id == uuid.UUID(self.project_id)).count()
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
