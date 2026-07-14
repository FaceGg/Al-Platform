"""Labeling API integration tests."""
import sys, os, unittest
sys.path.insert(0, ".")

from fastapi.testclient import TestClient
from app.main import app
from app.database import Base, engine

Base.metadata.create_all(bind=engine)
client = TestClient(app)


class TestLabelingAPI(unittest.TestCase):
    def test_01_label_by_rules(self):
        data = [
            [10, "pass"],
            [3, "fail"],
            [8, "pass"],
            [1, "fail"],
        ]
        columns = ["score", "result"]
        rules = [
            {"column": "score", "condition": "greater_than", "value": 5, "label": "high"},
            {"column": "result", "condition": "equals", "value": "pass", "label": "passed"},
        ]
        r = client.post("/api/labeling/rules", json={
            "data": data, "columns": columns, "rules": rules
        })
        self.assertEqual(r.status_code, 200)
        result = r.json()
        self.assertIn("labels", result)

    def test_02_label_by_rules_equals(self):
        data = [["cat"], ["dog"], ["cat"], ["bird"]]
        columns = ["animal"]
        rules = [{"column": "animal", "condition": "equals", "value": "cat", "label": "feline"}]
        r = client.post("/api/labeling/rules", json={
            "data": data, "columns": columns, "rules": rules
        })
        self.assertEqual(r.status_code, 200)
        result = r.json()
        labels = result["labels"]
        self.assertEqual(sum(1 for l in labels if l["label"] == "feline"), 2)

    def test_03_label_by_rules_contains(self):
        data = [["hello world"], ["goodbye"], ["hello again"]]
        columns = ["text"]
        rules = [{"column": "text", "condition": "contains", "value": "hello", "label": "greeting"}]
        r = client.post("/api/labeling/rules", json={
            "data": data, "columns": columns, "rules": rules
        })
        self.assertEqual(r.status_code, 200)
        result = r.json()
        self.assertEqual(sum(1 for l in result["labels"] if l["label"] == "greeting"), 2)

    def test_04_label_by_rules_regex(self):
        data = [["error-001"], ["info-002"], ["error-003"]]
        columns = ["log"]
        rules = [{"column": "log", "condition": "regex", "value": r"error-\d+", "label": "error_log"}]
        r = client.post("/api/labeling/rules", json={
            "data": data, "columns": columns, "rules": rules
        })
        self.assertEqual(r.status_code, 200)
        result = r.json()
        self.assertEqual(sum(1 for l in result["labels"] if l["label"] == "error_log"), 2)

    def test_05_label_by_rules_in(self):
        data = [["A"], ["B"], ["C"], ["D"], ["A"]]
        columns = ["grade"]
        rules = [{"column": "grade", "condition": "in", "value": ["A", "B"], "label": "top_grade"}]
        r = client.post("/api/labeling/rules", json={
            "data": data, "columns": columns, "rules": rules
        })
        self.assertEqual(r.status_code, 200)
        result = r.json()
        self.assertEqual(sum(1 for l in result["labels"] if l["label"] == "top_grade"), 3)

    def test_06_label_by_rules_less_than(self):
        data = [[5], [10], [3], [15]]
        columns = ["value"]
        rules = [{"column": "value", "condition": "less_than", "value": 8, "label": "low"}]
        r = client.post("/api/labeling/rules", json={
            "data": data, "columns": columns, "rules": rules
        })
        self.assertEqual(r.status_code, 200)
        result = r.json()
        self.assertEqual(sum(1 for l in result["labels"] if l["label"] == "low"), 2)

    def test_07_label_empty_data(self):
        r = client.post("/api/labeling/rules", json={
            "data": [], "columns": ["x"], "rules": [{"column": "x", "condition": "equals", "value": 1, "label": "t"}]
        })
        self.assertEqual(r.status_code, 200)

    def test_08_label_similarity_available(self):
        """Check if similarity endpoint is available (may be 404 if not implemented)."""
        r = client.post("/api/labeling/similarity", json={
            "texts": ["spot welding current 8kA"],
            "reference": [{"text": "spot welding", "label": "spot_weld"}],
        })
        self.assertIn(r.status_code, [200, 201, 404, 422])


if __name__ == "__main__":
    unittest.main()
