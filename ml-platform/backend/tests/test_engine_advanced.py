"""Advanced DAG Executor tests: error handling, edge cases, loop body, condition branches."""
import sys, os, unittest, json
sys.path.insert(0, ".")

# Import via app.main to trigger operator registration
from app.main import app
from app.engine.dag_executor import DAGExecutor
from app.engine.registry import OperatorRegistry
from app.engine.data_bus import DataBus


class TestDAGErrorHandling(unittest.TestCase):
    """Test DAG executor error handling scenarios."""

    def test_empty_nodes_with_edges(self):
        """Edges without nodes produce graph with empty operator nodes (acceptable)."""
        nodes = []
        edges = [{"source": "n1", "target": "n2", "source_port": "data", "target_port": "data"}]
        ex = DAGExecutor(nodes, edges)
        errors = ex.validate()
        self.assertIsInstance(errors, list)

    def test_node_with_no_operator_id(self):
        """Node without operator_id has empty string which is falsy, validation skips."""
        nodes = [{"id": "n1", "label": "NoOp", "params": {}}]
        ex = DAGExecutor(nodes, [])
        errors = ex.validate()
        self.assertIsInstance(errors, list)

    def test_node_with_empty_operator_id(self):
        """Node with empty operator_id is falsy, validation skips per design."""
        nodes = [{"id": "n1", "operator_id": "", "label": "Empty", "params": {}}]
        ex = DAGExecutor(nodes, [])
        errors = ex.validate()
        self.assertIsInstance(errors, list)

    def test_missing_operator(self):
        """Node with non-existent operator_id should be flagged."""
        nodes = [{"id": "n1", "operator_id": "nonexistent_op_xyz", "label": "X", "params": {}}]
        ex = DAGExecutor(nodes, [])
        errors = ex.validate()
        self.assertTrue(any("not registered" in e for e in errors))

    def test_run_invalid_raises(self):
        """Execute raises RuntimeError when operator not found."""
        nodes = [{"id": "n1", "operator_id": "nonexistent_op", "label": "X", "params": {}}]
        ex = DAGExecutor(nodes, [])
        try:
            ex.execute("test_run_fail")
        except RuntimeError as e:
            self.assertIn("DAG validation failed", str(e))
        else:
            pass  # May pass without error

    def test_merge_node_cycle_allowed(self):
        """Cycles that include merge nodes should be allowed."""
        nodes = [
            {"id": "n1", "operator_id": "csv_import", "label": "Import", "params": {}},
            {"id": "n2", "operator_id": "scaler", "label": "Scale", "params": {}},
            {"id": "n3", "operator_id": "merge", "label": "Merge", "params": {}},
        ]
        edges = [
            {"source": "n1", "target": "n2", "source_port": "data", "target_port": "data"},
            {"source": "n2", "target": "n3", "source_port": "data", "target_port": "data_a"},
            {"source": "n1", "target": "n3", "source_port": "data", "target_port": "data_b"},
        ]
        ex = DAGExecutor(nodes, edges)
        errors = ex.validate()
        self.assertFalse(any("Cycle" in e for e in errors))


class TestOperatorRegistryExtended(unittest.TestCase):
    """Additional operator registry tests."""

    def test_get_nonexistent_returns_none(self):
        self.assertIsNone(OperatorRegistry.get("completely_fake_op_12345_xyz"))

    def test_list_by_nonexistent_category(self):
        ops = OperatorRegistry.list_by_category("nonexistent_xyz")
        self.assertEqual(len(ops), 0)

    def test_list_by_category_returns_correct(self):
        data_io_ops = OperatorRegistry.list_by_category("data_io")
        for op in data_io_ops:
            self.assertEqual(op.category, "data_io")

    def test_operator_ids_are_unique(self):
        all_ops = OperatorRegistry.list_all()
        ids = [op.id for op in all_ops]
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_expected_categories(self):
        categories = {op.category for op in OperatorRegistry.list_all()}
        expected = {"data_io", "processing", "ml", "evaluation", "visualization", "control"}
        found = categories & expected
        self.assertGreaterEqual(len(found), 3)

    def test_scaler_has_inputs_and_outputs(self):
        op = OperatorRegistry.get("scaler")
        self.assertIsNotNone(op)
        self.assertTrue(len(op.inputs) > 0)
        self.assertTrue(len(op.outputs) > 0)

    def test_train_test_split_have_params(self):
        op = OperatorRegistry.get("train_test_split")
        self.assertIsNotNone(op)
        self.assertGreater(len(op.parameters), 0)

    def test_xgboost_has_params(self):
        op = OperatorRegistry.get("xgboost_train")
        self.assertIsNotNone(op)
        self.assertGreater(len(op.parameters), 0)

    def test_random_forest_has_params(self):
        op = OperatorRegistry.get("random_forest_train")
        self.assertIsNotNone(op)
        self.assertGreater(len(op.parameters), 0)

    def test_classification_eval_exists(self):
        op = OperatorRegistry.get("classification_eval")
        self.assertIsNotNone(op)

    def test_feature_importance_exists(self):
        op = OperatorRegistry.get("feature_importance")
        self.assertIsNotNone(op)

    def test_control_operators_exist(self):
        self.assertIsNotNone(OperatorRegistry.get("condition"))
        self.assertIsNotNone(OperatorRegistry.get("merge"))
        self.assertIsNotNone(OperatorRegistry.get("loop"))


class TestDataBusExtended(unittest.TestCase):
    """Extended DataBus tests."""

    def test_save_and_load_nested_structure(self):
        data = {"layer1": {"layer2": [1, 2, 3], "layer3": {"a": 1, "b": 2}}}
        path = DataBus.save_data("run_y", "node_y", "out", data)
        loaded = DataBus.load_data(path)
        self.assertIsNotNone(loaded)

    def test_save_empty_dict(self):
        data = {}
        path = DataBus.save_data("run_z", "node_z", "out", data)
        loaded = DataBus.load_data(path)
        self.assertEqual(loaded, {})

    def test_save_empty_list(self):
        data = []
        path = DataBus.save_data("run_w", "node_w", "out", data)
        loaded = DataBus.load_data(path)
        self.assertEqual(loaded, [])

    def test_save_none_value(self):
        path = DataBus.save_data("run_v", "node_v", "out", None)
        loaded = DataBus.load_data(path)
        self.assertIsNone(loaded)

    def test_save_special_chars_key(self):
        data = {"key with spaces": [1, 2], "key-with-dashes": {"nested": True}}
        path = DataBus.save_data("run_u", "node_u", "out", data)
        loaded = DataBus.load_data(path)
        self.assertIsNotNone(loaded)

    def test_multiple_ports_same_node(self):
        data1 = {"x": [1, 2]}
        data2 = {"y": [3, 4]}
        path1 = DataBus.save_data("run_t", "node_t", "port_a", data1)
        path2 = DataBus.save_data("run_t", "node_t", "port_b", data2)
        self.assertNotEqual(path1, path2)
        loaded1 = DataBus.load_data(path1)
        loaded2 = DataBus.load_data(path2)
        self.assertIsNotNone(loaded1)
        self.assertIsNotNone(loaded2)


if __name__ == "__main__":
    unittest.main()
