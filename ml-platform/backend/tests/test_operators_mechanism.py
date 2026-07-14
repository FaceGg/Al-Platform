"""Mechanism Models operator unit tests."""
import sys, os, unittest
sys.path.insert(0, ".")

from app.main import app
from app.engine.registry import OperatorRegistry
from tests.operator_test_utils import execute_operator


class TestMechanismModels(unittest.TestCase):
    def test_01_thermal(self):
        op = OperatorRegistry.get("mechanism_thermal")
        self.assertIsNotNone(op)
        output = execute_operator(op, {}, {
            "current_ka": 10.0, "voltage_v": 1.5,
            "weld_time_ms": 200, "sheet_thickness_mm": 1.5,
            "material_code": "DC04", "electrode_diameter_mm": 6.0,
        })
        self.assertIsInstance(output, dict)

    def test_02_nugget(self):
        op = OperatorRegistry.get("mechanism_nugget")
        self.assertIsNotNone(op)
        output = execute_operator(op, {}, {
            "current_ka": 10.0, "weld_time_ms": 200,
            "electrode_force_kn": 3.0, "sheet_thickness_mm": 1.5,
            "material_code": "DC04",
        })
        self.assertIsInstance(output, dict)

    def test_03_lobe(self):
        op = OperatorRegistry.get("mechanism_lobe")
        self.assertIsNotNone(op)
        output = execute_operator(op, {}, {
            "sheet_thickness_mm": 1.0, "material_code": "DC04",
        })
        self.assertIsInstance(output, dict)

    def test_04_splash(self):
        op = OperatorRegistry.get("mechanism_splash")
        self.assertIsNotNone(op)
        output = execute_operator(op, {}, {
            "current_ka": 10.0, "weld_time_ms": 150,
            "electrode_force_kn": 3.0, "sheet_thickness_mm": 1.5,
            "material_code": "DC04",
        })
        self.assertIsInstance(output, dict)

    def test_05_stress(self):
        op = OperatorRegistry.get("mechanism_stress")
        self.assertIsNotNone(op)
        output = execute_operator(op, {}, {
            "current_ka": 10.0, "weld_time_ms": 200,
            "electrode_force_kn": 3.0, "sheet_thickness_mm": 1.5,
            "sheet_width_mm": 100.0, "material_code": "DC04",
        })
        self.assertIsInstance(output, dict)

    def test_06_gate(self):
        op = OperatorRegistry.get("mechanism_gate")
        self.assertIsNotNone(op)
        output = execute_operator(op, {}, {
            "current_ka": 10.0, "voltage_v": 1.5,
            "weld_time_ms": 200, "sheet_thickness_mm": 1.5,
            "sheet_width_mm": 100.0, "material_code": "DC04",
            "electrode_diameter_mm": 6.0, "electrode_force_kn": 3.0,
        })
        self.assertIsInstance(output, dict)

    def test_07_all_have_outputs(self):
        for op in OperatorRegistry.list_by_category("mechanism"):
            self.assertGreater(len(op.outputs), 0, f"{op.id}")

    def test_08_count(self):
        self.assertGreaterEqual(len(OperatorRegistry.list_by_category("mechanism")), 5)


if __name__ == "__main__":
    unittest.main()
