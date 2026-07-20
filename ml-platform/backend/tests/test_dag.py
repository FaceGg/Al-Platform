"""DAG Executor, Operator Registry, and DataBus tests."""
import sys, os, json, unittest
from unittest.mock import patch
sys.path.insert(0, ".")

# Import main to trigger operator registration
from app.main import app
from app.engine.dag_executor import DAGExecutor
from app.engine.registry import OperatorRegistry
from app.engine.data_bus import DataBus


class TestDAGValidation(unittest.TestCase):
    def test_valid_dag_passes(self):
        nodes = [
            {"id": "n1", "operator_id": "csv_import", "label": "Import", "params": {}},
            {"id": "n2", "operator_id": "scaler", "label": "Scale", "params": {}},
        ]
        edges = [{"source": "n1", "target": "n2", "source_port": "data", "target_port": "data"}]
        ex = DAGExecutor(nodes, edges)
        errors = ex.validate()
        self.assertEqual(len([e for e in errors if "Cycle" in e]), 0)

    def test_empty_dag(self):
        ex = DAGExecutor([], [])
        errors = ex.validate()
        self.assertEqual(len(errors), 0)

    def test_cycle_detected(self):
        nodes = [
            {"id": "n1", "operator_id": "csv_import", "label": "n1", "params": {}},
            {"id": "n2", "operator_id": "scaler", "label": "n2", "params": {}},
            {"id": "n3", "operator_id": "scaler", "label": "n3", "params": {}},
        ]
        edges = [
            {"source": "n1", "target": "n2", "source_port": "data", "target_port": "data"},
            {"source": "n2", "target": "n3", "source_port": "data", "target_port": "data"},
            {"source": "n3", "target": "n1", "source_port": "data", "target_port": "data"},
        ]
        ex = DAGExecutor(nodes, edges)
        errors = ex.validate()
        self.assertTrue(any("cycle" in e.lower() for e in errors))

    def test_missing_operator_reported(self):
        nodes = [{"id": "n1", "operator_id": "nonexistent_op", "label": "Bad", "params": {}}]
        ex = DAGExecutor(nodes, [])
        errors = ex.validate()
        self.assertTrue(any("nonexistent_op" in e for e in errors))


class TestOperatorRegistry(unittest.TestCase):
    def test_operator_count(self):
        ops = OperatorRegistry.list_all()
        self.assertGreater(len(ops), 10)

    def test_all_builtin_registered(self):
        for oid in ["csv_import", "csv_export", "json_import", "missing_value_handler",
                     "scaler", "label_encoder", "train_test_split", "xgboost_train",
                     "random_forest_train", "linear_model_train", "classification_eval",
                     "regression_eval", "data_table", "histogram"]:
            self.assertIsNotNone(OperatorRegistry.get(oid), f"{oid} not registered")

    def test_csv_import_properties(self):
        op = OperatorRegistry.get("csv_import")
        self.assertIsNotNone(op)
        self.assertTrue(hasattr(op, "inputs"))
        self.assertTrue(hasattr(op, "outputs"))
        self.assertTrue(hasattr(op, "parameters"))

    def test_xgboost_properties(self):
        op = OperatorRegistry.get("xgboost_train")
        self.assertIsNotNone(op)
        self.assertTrue(hasattr(op, "inputs"))
        self.assertTrue(hasattr(op, "outputs"))
        self.assertTrue(hasattr(op, "parameters"))

    def test_control_operators_exist(self):
        for oid in ["condition", "loop", "merge"]:
            self.assertIsNotNone(OperatorRegistry.get(oid), f"{oid} not registered")


class TestDataBus(unittest.TestCase):
    def setUp(self):
        import tempfile
        DataBus.set_base_dir(tempfile.mkdtemp(prefix="test_databus_"))

    def tearDown(self):
        import shutil
        base = DataBus._base_dir
        if base and base.exists():
            shutil.rmtree(base)
        DataBus._base_dir = None

    def test_save_and_load_dict(self):
        data = {"a": 1, "b": "hello", "c": 3.14}
        path = DataBus.save_data("run_a", "node_a", "out", data)
        self.assertTrue(os.path.exists(path))
        loaded = DataBus.load_data(path)
        self.assertEqual(loaded, data)

    def test_save_and_load_list(self):
        data = [1, 2, 3]
        path = DataBus.save_data("run_b", "node_b", "out", data)
        self.assertTrue(os.path.exists(path))
        loaded = DataBus.load_data(path)
        self.assertEqual(loaded, data)

    def test_load_nonexistent(self):
        result = DataBus.load_data("/nonexistent/path.json")
        self.assertIsNone(result)

    def test_default_directory_does_not_depend_on_source_path_depth(self):
        import tempfile

        DataBus._base_dir = None
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ,
            {"ML_PLATFORM_TEMP_DIR": ""},
        ), patch(
            "tempfile.gettempdir",
            return_value=directory,
        ), patch(
            "app.engine.data_bus.__file__",
            "/app/app/engine/data_bus.py",
        ):
            base = DataBus._ensure_base_dir()

        self.assertEqual(base, __import__("pathlib").Path(directory) / "ml_platform_data")
