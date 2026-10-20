"""Comprehensive test covering all registered operators: registration, metadata, and execution.

This test module validates every operator in the registry without modifying source code.
Operators are tested in three dimensions:
1. Registration: all operators registered with unique IDs
2. Metadata: each operator has valid id, name, category, inputs, outputs
3. Execution: each operator runs with appropriate sample data and returns OperatorResult
"""
import io
import os
import tempfile
import unittest

from app.engine.registry import OperatorRegistry
from app.engine.operator_contract import OperatorContext, OperatorResult
from app.services.spot_weld_features import FEATURE_SCHEMA, QualityPipelineError
from app.services.spot_weld_quality import build_demo_report_frame
from tests.operator_test_utils import execute_operator, operator_context

# Importing app triggers operator registration via module side effects.
from app.main import app  # noqa: F401


# ---- Sample data fixtures ----

CLASSIFICATION_DATA = [
    {"feature1": float(i), "feature2": float(i * 2), "target": 0 if i < 8 else 1}
    for i in range(20)
]

REGRESSION_DATA = [
    {"x": float(i), "y": float(i * 3 + 1)}
    for i in range(20)
]

CLUSTER_DATA = [
    {"x": float(i), "y": float((i % 3) * 10)}
    for i in range(15)
]

TRANSACTION_DATA = [
    {"item": "A", "qty": 1},
    {"item": "A", "qty": 2},
    {"item": "B", "qty": 1},
    {"item": "A", "qty": 1},
]

LEFT_DATA = [
    {"id": 1, "name": "alpha", "value": 10},
    {"id": 2, "name": "beta", "value": 20},
]

RIGHT_DATA = [
    {"id": 1, "label": "L1", "score": 0.9},
    {"id": 2, "label": "L2", "score": 0.8},
]

EVAL_DATA = [
    {"feature": float(i), "Fault": 0 if i < 8 else 1, "outlier": 0 if i < 9 else 1}
    for i in range(20)
]


def pd_is_nan(value):
    import math
    return value is None or (isinstance(value, float) and math.isnan(value))


def _trained_model_bytes():
    """Train a simple sklearn model and return joblib bytes."""
    import joblib
    from sklearn.linear_model import LogisticRegression
    from app.operators.ml_operators import LinearModelTrainer
    op = OperatorRegistry.get("linear_model_train")
    result = op.execute(operator_context(), {"data": CLASSIFICATION_DATA}, {"target_column": "target"})
    return result.outputs["model"]


class TestAllOperatorsRegistered(unittest.TestCase):
    """Verify all operators are registered with unique IDs."""

    def test_operator_count_meets_baseline(self):
        ops = OperatorRegistry.list_all()
        self.assertGreaterEqual(len(ops), 80,
            f"Expected at least 80 operators, found {len(ops)}")

    def test_all_ids_are_unique(self):
        ops = OperatorRegistry.list_all()
        ids = [op.id for op in ops]
        duplicates = [i for i in ids if ids.count(i) > 1]
        self.assertEqual(duplicates, [], f"Duplicate operator IDs: {set(duplicates)}")

    def test_all_ids_are_nonempty_strings(self):
        for op in OperatorRegistry.list_all():
            self.assertTrue(isinstance(op.id, str) and op.id.strip(),
                f"Operator has invalid id: {op.id!r}")

    def test_expected_categories_exist(self):
        categories = {op.category for op in OperatorRegistry.list_all()}
        expected = {"io", "processing", "ml", "evaluation", "visualization",
                    "control", "dl", "blending", "optimization"}
        missing = expected - categories
        self.assertEqual(missing, set(), f"Missing categories: {missing}")

    def test_every_category_has_operators(self):
        from collections import Counter
        counts = Counter(op.category for op in OperatorRegistry.list_all())
        for cat, count in counts.items():
            self.assertGreater(count, 0, f"Category '{cat}' has no operators")


class TestAllOperatorsMetadata(unittest.TestCase):
    """Verify each operator has valid metadata."""

    def test_every_operator_has_name_and_description(self):
        for op in OperatorRegistry.list_all():
            self.assertTrue(isinstance(op.name, str) and op.name.strip(),
                f"Operator '{op.id}' has empty name")
            self.assertTrue(isinstance(op.description, str),
                f"Operator '{op.id}' has no description")

    def test_every_operator_has_inputs_list(self):
        for op in OperatorRegistry.list_all():
            self.assertTrue(isinstance(op.inputs, list),
                f"Operator '{op.id}' inputs is not a list")

    def test_every_operator_has_outputs_list(self):
        for op in OperatorRegistry.list_all():
            self.assertTrue(isinstance(op.outputs, list),
                f"Operator '{op.id}' outputs is not a list")

    def test_every_operator_has_parameters_list(self):
        for op in OperatorRegistry.list_all():
            self.assertTrue(isinstance(op.parameters, list),
                f"Operator '{op.id}' parameters is not a list")

    def test_output_ports_have_name_and_type(self):
        from app.engine.base_operator import PortSpec
        for op in OperatorRegistry.list_all():
            for port in op.outputs:
                self.assertTrue(hasattr(port, 'name'),
                    f"Operator '{op.id}' output port missing name")
                self.assertTrue(hasattr(port, 'type'),
                    f"Operator '{op.id}' output port missing type")

    def test_input_ports_have_name_and_type(self):
        for op in OperatorRegistry.list_all():
            for port in op.inputs:
                self.assertTrue(hasattr(port, 'name'),
                    f"Operator '{op.id}' input port missing name")
                self.assertTrue(hasattr(port, 'type'),
                    f"Operator '{op.id}' input port missing type")


class TestIOOperatorsExecution(unittest.TestCase):
    """Test IO operators execution."""

    def test_csv_import_no_file_returns_error(self):
        op = OperatorRegistry.get("csv_import")
        with self.assertRaises(RuntimeError):
            op.execute(operator_context(), {}, {"source": "local", "file_path": ""})

    def test_csv_import_reads_local_file(self):
        op = OperatorRegistry.get("csv_import")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            f.write("a,b\n1,2\n3,4\n")
            f.flush()
            path = f.name
        try:
            result = op.execute(operator_context(), {},
                {"source": "local", "file_path": path, "delimiter": ",", "has_header": True})
            self.assertIsInstance(result, OperatorResult)
            self.assertEqual(len(result.outputs["data"]), 2)
        finally:
            os.unlink(path)

    def test_csv_export_passthrough(self):
        outputs = execute_operator(
            OperatorRegistry.get("csv_export"),
            {"data": [{"a": 1}]}, {"file_path": ""})
        self.assertEqual(outputs["data"], [{"a": 1}])

    def test_csv_export_writes_file(self):
        with tempfile.NamedTemporaryFile(suffix='.csv', delete=False) as f:
            path = f.name
        try:
            execute_operator(
                OperatorRegistry.get("csv_export"),
                {"data": [{"a": 1, "b": 2}]},
                {"file_path": path, "separator": ","})
            self.assertTrue(os.path.exists(path))
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_image_import_no_path_returns_empty(self):
        outputs = execute_operator(
            OperatorRegistry.get("image_import"), {}, {"file_path": "", "pattern": "*.png"})
        self.assertEqual(outputs["data"], [])

    def test_json_import_no_path_returns_empty(self):
        outputs = execute_operator(
            OperatorRegistry.get("json_import"), {}, {"file_path": "", "orient": "records"})
        self.assertEqual(outputs["data"], [])

    def test_json_import_reads_file(self):
        import json
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump([{"x": 1}, {"x": 2}], f)
            f.flush()
            path = f.name
        try:
            outputs = execute_operator(
                OperatorRegistry.get("json_import"), {},
                {"file_path": path, "orient": "records"})
            self.assertEqual(len(outputs["data"]), 2)
        finally:
            os.unlink(path)

    def test_read_excel_no_path_raises_required_error(self):
        with self.assertRaisesRegex(RuntimeError, "Excel file path is required"):
            execute_operator(
                OperatorRegistry.get("read_excel"), {}, {"file_path": ""})

    def test_read_database_no_conn_returns_empty(self):
        outputs = execute_operator(
            OperatorRegistry.get("read_database"), {},
            {"connection_string": "", "query": "SELECT 1"})
        self.assertEqual(outputs["data"], [])

    def test_read_url_no_url_returns_empty(self):
        outputs = execute_operator(
            OperatorRegistry.get("read_url"), {}, {"url": ""})
        self.assertEqual(outputs["data"], [])

    def test_write_csv_passthrough(self):
        outputs = execute_operator(
            OperatorRegistry.get("write_csv"),
            {"data": [{"a": 1}]}, {"file_path": ""})
        self.assertEqual(outputs["data"], [{"a": 1}])

    def test_retrieve_no_path_returns_empty(self):
        outputs = execute_operator(
            OperatorRegistry.get("retrieve"), {}, {"repository_entry": ""})
        self.assertEqual(outputs["data"], [])

    def test_store_passthrough(self):
        outputs = execute_operator(
            OperatorRegistry.get("store"),
            {"data": [{"a": 1}]}, {"repository_entry": ""})
        self.assertEqual(outputs["data"], [{"a": 1}])


class TestProcessingOperatorsExecution(unittest.TestCase):
    """Test processing operators execution."""

    def test_missing_value_handler_drop(self):
        data = [{"a": 1, "b": None}, {"a": 2, "b": 3}]
        outputs = execute_operator(
            OperatorRegistry.get("missing_value_handler"),
            {"data": data}, {"strategy": "drop", "columns": ""})
        self.assertEqual(len(outputs["data"]), 1)

    def test_missing_value_handler_mean(self):
        data = [{"a": 1, "b": 10}, {"a": 2, "b": None}, {"a": 3, "b": 30}]
        outputs = execute_operator(
            OperatorRegistry.get("missing_value_handler"),
            {"data": data}, {"strategy": "mean", "columns": "b"})
        self.assertEqual(outputs["data"][1]["b"], 20.0)

    def test_label_encoder(self):
        data = [{"cat": "A", "v": 1}, {"cat": "B", "v": 2}]
        outputs = execute_operator(
            OperatorRegistry.get("label_encoder"),
            {"data": data}, {"columns": "cat", "encoding_type": "label"})
        self.assertIn(outputs["data"][0]["cat"], [0, 1])

    def test_scaler(self):
        outputs = execute_operator(
            OperatorRegistry.get("scaler"),
            {"data": CLASSIFICATION_DATA}, {"method": "standard", "columns": ""})
        self.assertEqual(len(outputs["data"]), len(CLASSIFICATION_DATA))

    def test_train_test_split(self):
        outputs = execute_operator(
            OperatorRegistry.get("train_test_split"),
            {"data": CLASSIFICATION_DATA},
            {"test_size": 0.2, "random_seed": 42, "target_column": "target", "stratify": False})
        self.assertIn("train", outputs)
        self.assertIn("test", outputs)

    def test_auto_feature_engineering(self):
        outputs = execute_operator(
            OperatorRegistry.get("auto_feature_engineering"),
            {"data": REGRESSION_DATA}, {"operations": "poly", "degree": 2})
        self.assertGreater(len(outputs["data"]), 0)

    def test_auto_feature_engineering_respects_column_selection(self):
        data = [
            {"a": float(i), "b": float(i * 2), "c": float(i * 3), "target": 0 if i < 8 else 1}
            for i in range(16)
        ]

        outputs = execute_operator(
            OperatorRegistry.get("auto_feature_engineering"),
            {"data": data},
            {"columns": "a,b", "interactions": True, "polynomial_degree": 2})

        report = outputs["feature_report"]
        self.assertEqual(report["original_features"], 2)
        self.assertEqual(report["selected_columns"], ["a", "b"])
        step = next(s for s in report["steps"] if s["step"] == "polynomial_interactions")
        # 选中 a、b 两列 → 仅生成 a×b 一个交互项（3 列全参与应为 3 项），c 未参与
        self.assertEqual(step["features_added"], 1)
        self.assertAlmostEqual(outputs["data"][1]["poly_0"], 2.0)  # a=1, b=2 → a×b=2

    def test_auto_feature_engineering_ignores_unknown_columns(self):
        data = [{"a": float(i), "target": 0 if i < 5 else 1} for i in range(10)]

        outputs = execute_operator(
            OperatorRegistry.get("auto_feature_engineering"),
            {"data": data},
            {"columns": "a,not_there", "interactions": True, "polynomial_degree": 2})

        report = outputs["feature_report"]
        self.assertEqual(report["original_features"], 1)
        self.assertEqual(report["ignored_columns"], ["not_there"])

    def test_spot_weld_feature_engineering_preserves_report_feature_contract(self):
        frame = build_demo_report_frame(12)
        frame["Fault"] = [0 if index < 6 else 1 for index in range(len(frame))]

        outputs = execute_operator(
            OperatorRegistry.get("spot_weld_feature_engineering"),
            {"data": frame.to_dict(orient="records")}, {})

        self.assertEqual(len(outputs["features"]), 12)
        self.assertEqual(outputs["schema"]["columns"], list(FEATURE_SCHEMA) + ["Fault"])
        self.assertEqual(outputs["schema"]["label_column"], "Fault")
        self.assertEqual(outputs["schema"]["label_position"], "last")
        self.assertEqual(len(outputs["schema"]["columns"]), 74)
        self.assertEqual(outputs["statistics"]["feature_count"], 73)
        self.assertEqual(outputs["statistics"]["label_column"], "Fault")
        self.assertEqual(outputs["statistics"]["label_present"], True)
        self.assertEqual(outputs["statistics"]["label_dtype"], "int64")
        self.assertEqual(
            [name for name in ("cvei", "cvev", "cver", "cvep") if name in outputs["features"][0]],
            [],
        )
        self.assertEqual([row["Fault"] for row in outputs["features"]], frame["Fault"].tolist())

    def test_spot_weld_feature_engineering_reports_missing_optional_label(self):
        frame = build_demo_report_frame(12)

        outputs = execute_operator(
            OperatorRegistry.get("spot_weld_feature_engineering"),
            {"data": frame.to_dict(orient="records")}, {})

        self.assertNotIn("Fault", outputs["features"][0])
        self.assertNotIn("Fault", outputs["schema"]["columns"])
        self.assertEqual(outputs["schema"]["label_column"], "Fault")
        self.assertEqual(outputs["statistics"]["label_present"], False)

    def test_spot_weld_feature_engineering_declares_all_report_source_columns(self):
        operator = OperatorRegistry.get("spot_weld_feature_engineering")
        source_columns = next(port.required_columns for port in operator.inputs if port.name == "data")
        self.assertEqual(
            source_columns,
            (
                "wld1c", "wld2c", "tipv1", "tipv2", "wres", "energy",
                "wld_spatter_strength", "wld1_spatter_strength", "wld2_spatter_strength",
                "spatterpos_wld", "spatterpos_pre", "spotdiameter", "spotposition", "spattercode",
                "cvei", "cvev", "cver", "cvep",
            ),
        )

    def test_spot_weld_feature_engineering_accepts_dataframe(self):
        frame = build_demo_report_frame(12)

        outputs = execute_operator(
            OperatorRegistry.get("spot_weld_feature_engineering"),
            {"data": frame}, {})

        self.assertEqual(len(outputs["features"]), 12)

    def test_spot_weld_feature_engineering_filters_columns_and_preserves_lowercase_fault(self):
        frame = build_demo_report_frame(12)
        frame["fault"] = [0 if index < 6 else 1 for index in range(len(frame))]

        outputs = execute_operator(
            OperatorRegistry.get("spot_weld_feature_engineering"),
            {"data": frame.to_dict(orient="records")},
            {"exclude_columns": "current_mean", "label_column": "fault"},
        )

        columns = outputs["schema"]["columns"]
        self.assertNotIn("current_mean", columns)
        self.assertEqual(columns[-1], "fault")
        self.assertEqual(outputs["schema"]["label_column"], "fault")
        self.assertEqual([row["fault"] for row in outputs["features"]], frame["fault"].tolist())

    def test_spot_weld_feature_engineering_rejects_filtering_required_source_column(self):
        frame = build_demo_report_frame(12)

        with self.assertRaises(ValueError) as raised:
            execute_operator(
                OperatorRegistry.get("spot_weld_feature_engineering"),
                {"data": frame.to_dict(orient="records")},
                {"exclude_columns": "cvei"},
            )

        self.assertIn("required source column", str(raised.exception))

    def test_spot_weld_feature_engineering_propagates_waveform_error(self):
        frame = build_demo_report_frame(12)
        frame.loc[0, "cvei"] = "not-base64"

        with self.assertRaises(QualityPipelineError) as raised:
            execute_operator(
                OperatorRegistry.get("spot_weld_feature_engineering"),
                {"data": frame}, {})

        error = raised.exception
        self.assertIs(type(error), QualityPipelineError)
        self.assertEqual(error.code, "QUALITY_WAVEFORM_INVALID_BASE64")
        self.assertEqual(error.row_index, 0)
        self.assertEqual(error.field_name, "cvei")

    def test_tighten_feature_engineering_derives_core_features(self):
        data = [
            {"ACTUAL_TORQUE": 632.0, "TARGET_TORQUE": 630.0,
             "UPPER_LIMIT": 635.0, "LOWER_LIMIT": 625.0,
             "ACTUAL_TORQUE_TWO": 634.0},
            {"ACTUAL_TORQUE": 478.0, "TARGET_TORQUE": 475.0,
             "UPPER_LIMIT": 480.0, "LOWER_LIMIT": 470.0,
             "ACTUAL_TORQUE_TWO": None},
        ]

        outputs = execute_operator(
            OperatorRegistry.get("tighten_feature_engineering"),
            {"data": data},
            # keep：本用例聚焦派生逻辑本身（缺失保留为 NaN）；默认 median
            # 填充行为由 drops_leakage_and_fills_missing 用例覆盖。
            {"missing_strategy": "keep", "missing_flag_column": ""})

        derived = outputs["schema"]["derived_columns"]
        self.assertEqual(
            derived,
            ["TIGHTEN_TORQUE_DEVIATION", "TIGHTEN_DEVIATION_RATIO",
             "TIGHTEN_UPPER_MARGIN", "TIGHTEN_LOWER_MARGIN", "TIGHTEN_DUAL_AXIS_DIFF"],
        )
        first = outputs["features"][0]
        self.assertAlmostEqual(first["TIGHTEN_TORQUE_DEVIATION"], 2.0)
        self.assertAlmostEqual(first["TIGHTEN_DEVIATION_RATIO"], 0.2)
        self.assertAlmostEqual(first["TIGHTEN_UPPER_MARGIN"], 3.0)
        self.assertAlmostEqual(first["TIGHTEN_LOWER_MARGIN"], 7.0)
        self.assertAlmostEqual(first["TIGHTEN_DUAL_AXIS_DIFF"], -2.0)
        second = outputs["features"][1]
        self.assertAlmostEqual(second["TIGHTEN_DEVIATION_RATIO"], 0.3)
        self.assertTrue(pd_is_nan(second["TIGHTEN_DUAL_AXIS_DIFF"]))
        statistics = outputs["statistics"]
        self.assertEqual(statistics["rows"], 2)
        self.assertEqual(statistics["TIGHTEN_TORQUE_DEVIATION_non_null"], 2)
        self.assertEqual(statistics["TIGHTEN_DUAL_AXIS_DIFF_non_null"], 1)
        self.assertEqual(statistics["skipped"], {})

    def test_tighten_feature_engineering_skips_band_when_limits_missing(self):
        data = [
            {"ACTUAL_TORQUE": 632.0, "TARGET_TORQUE": 630.0},
            {"ACTUAL_TORQUE": 478.0, "TARGET_TORQUE": 475.0},
        ]

        outputs = execute_operator(
            OperatorRegistry.get("tighten_feature_engineering"),
            {"data": data}, {"torque_two_column": ""})

        derived = outputs["schema"]["derived_columns"]
        self.assertEqual(derived, ["TIGHTEN_TORQUE_DEVIATION"])
        self.assertIn("band_features", outputs["statistics"]["skipped"])
        self.assertIn("dual_axis_diff", outputs["statistics"]["skipped"])
        self.assertNotIn("TIGHTEN_DEVIATION_RATIO", outputs["features"][0])

    def test_tighten_feature_engineering_handles_zero_band_width(self):
        data = [
            {"ACTUAL_TORQUE": 630.0, "TARGET_TORQUE": 630.0,
             "UPPER_LIMIT": 630.0, "LOWER_LIMIT": 630.0},
        ]

        outputs = execute_operator(
            OperatorRegistry.get("tighten_feature_engineering"),
            {"data": data},
            # keep：聚焦零带宽 → 比率 NaN 的派生逻辑（默认 median 会填充）
            {"missing_strategy": "keep", "missing_flag_column": ""})

        self.assertTrue(pd_is_nan(outputs["features"][0]["TIGHTEN_DEVIATION_RATIO"]))
        self.assertEqual(outputs["statistics"]["band_width_zero_rows"], 1)

    def test_tighten_feature_engineering_requires_torque_columns(self):
        with self.assertRaises(ValueError) as raised:
            execute_operator(
                OperatorRegistry.get("tighten_feature_engineering"),
                {"data": [{"foo": 1.0}]}, {})

        self.assertIn("ACTUAL_TORQUE", str(raised.exception))

    def test_tighten_feature_engineering_resolves_annotated_headers(self):
        # Production tighten CSVs carry Chinese annotations in the header,
        # e.g. "ACTUAL_TORQUE(实际扭矩/一轴实际扭矩)"; default base names
        # must still resolve through the parenthesis fallback.
        data = [
            {"ACTUAL_TORQUE(实际扭矩/一轴实际扭矩)": 632.0,
             "TARGET_TORQUE(设定目标力矩（N.m）)": 630.0,
             "UPPER_LIMIT(力矩上限（N.m）)": 635.0,
             "LOWER_LIMIT(力矩下限（N.m）)": 625.0,
             "ACTUAL_TORQUE_TWO(二轴实际扭矩)": 634.0},
        ]

        outputs = execute_operator(
            OperatorRegistry.get("tighten_feature_engineering"),
            {"data": data}, {})

        first = outputs["features"][0]
        self.assertAlmostEqual(first["TIGHTEN_TORQUE_DEVIATION"], 2.0)
        self.assertAlmostEqual(first["TIGHTEN_DEVIATION_RATIO"], 0.2)
        self.assertAlmostEqual(first["TIGHTEN_UPPER_MARGIN"], 3.0)
        self.assertAlmostEqual(first["TIGHTEN_LOWER_MARGIN"], 7.0)
        self.assertAlmostEqual(first["TIGHTEN_DUAL_AXIS_DIFF"], -2.0)
        self.assertEqual(outputs["statistics"]["skipped"], {})

    def test_tighten_feature_engineering_drops_leakage_and_fills_missing(self):
        # 默认参数：剔除 DECIDE_ONE/DECIDE_TWO（防标签泄漏）；二轴缺失（单轴
        # 拧紧）行按 median 填充保留——不再被下游 AutoML drop_rows 整行剔除，
        # 并生成缺失标记列让模型显式学习"单轴行"语义。
        data = [
            {"ACTUAL_TORQUE": 632.0, "TARGET_TORQUE": 630.0, "UPPER_LIMIT": 635.0,
             "LOWER_LIMIT": 625.0, "ACTUAL_TORQUE_TWO": 634.0,
             "DECIDE_ONE": 1, "DECIDE_TWO": 1},
            {"ACTUAL_TORQUE": 640.0, "TARGET_TORQUE": 630.0, "UPPER_LIMIT": 635.0,
             "LOWER_LIMIT": 625.0, "ACTUAL_TORQUE_TWO": None,
             "DECIDE_ONE": 1, "DECIDE_TWO": None},
        ]

        outputs = execute_operator(
            OperatorRegistry.get("tighten_feature_engineering"),
            {"data": data}, {})

        features = outputs["features"]
        self.assertEqual(len(features), 2)
        self.assertNotIn("DECIDE_ONE", features[0])
        self.assertNotIn("DECIDE_TWO", features[0])
        # 二轴缺失行被中位数填充：median([634.0]) = 634.0
        self.assertAlmostEqual(features[1]["ACTUAL_TORQUE_TWO"], 634.0)
        self.assertAlmostEqual(features[1]["TIGHTEN_DUAL_AXIS_DIFF"], 640.0 - 634.0)
        self.assertEqual(features[0]["TIGHTEN_MISSING_FLAG"], 0)
        self.assertEqual(features[1]["TIGHTEN_MISSING_FLAG"], 1)
        stats = outputs["statistics"]
        self.assertEqual(stats["removed_columns"], ["DECIDE_ONE", "DECIDE_TWO"])
        self.assertEqual(stats["missing_strategy"], "median")
        self.assertEqual(stats["missing_flag_rows"], 1)
        self.assertEqual(stats["filled_cells"], 2)  # ACTUAL_TORQUE_TWO + TIGHTEN_DUAL_AXIS_DIFF（行 2）

    def test_tighten_feature_engineering_keep_strategy_disables_fill(self):
        # missing_strategy=keep：保持缺失，不填充、不生成标记列
        data = [{"ACTUAL_TORQUE": 632.0, "TARGET_TORQUE": 630.0,
                 "UPPER_LIMIT": 635.0, "LOWER_LIMIT": 625.0,
                 "ACTUAL_TORQUE_TWO": None}]
        outputs = execute_operator(
            OperatorRegistry.get("tighten_feature_engineering"),
            {"data": data}, {"missing_strategy": "keep", "missing_flag_column": ""})
        first = outputs["features"][0]
        self.assertIsNone(first["ACTUAL_TORQUE_TWO"])
        self.assertNotIn("TIGHTEN_MISSING_FLAG", first)
        self.assertEqual(outputs["statistics"]["missing_strategy"], "keep")

    def test_feature_engineering_category_has_both_domain_operators(self):
        operators = OperatorRegistry.list_by_category("feature_engineering")
        ids = {op.id for op in operators}
        self.assertEqual(
            ids, {"spot_weld_feature_engineering", "tighten_feature_engineering"})
        for op in operators:
            raw_names = [port.name for port in op.outputs]
            self.assertIn("raw_data", raw_names,
                f"{op.id} must keep the raw_data output for backward compatibility")

    def test_normalize(self):
        outputs = execute_operator(
            OperatorRegistry.get("normalize"),
            {"data": CLASSIFICATION_DATA}, {"method": "minmax", "columns": ""})
        self.assertEqual(len(outputs["data"]), len(CLASSIFICATION_DATA))

    def test_discretize(self):
        outputs = execute_operator(
            OperatorRegistry.get("discretize"),
            {"data": REGRESSION_DATA}, {"columns": "x", "bins": 3, "strategy": "uniform"})
        self.assertEqual(len(outputs["data"]), len(REGRESSION_DATA))

    def test_detect_outliers(self):
        data = [{"x": float(i)} for i in range(10)] + [{"x": 1000.0}]
        outputs = execute_operator(
            OperatorRegistry.get("detect_outliers"),
            {"data": data}, {"method": "iqr", "columns": "x"})
        self.assertEqual(len(outputs["data"]), len(data))

    def test_select_attributes(self):
        outputs = execute_operator(
            OperatorRegistry.get("select_attributes"),
            {"data": CLASSIFICATION_DATA}, {"columns": "feature1,target"})
        self.assertTrue(all("feature2" not in row for row in outputs["data"]))

    def test_set_role(self):
        outputs = execute_operator(
            OperatorRegistry.get("set_role"),
            {"data": CLASSIFICATION_DATA}, {"target_column": "target"})
        self.assertEqual(len(outputs["data"]), len(CLASSIFICATION_DATA))

    def test_filter_examples(self):
        outputs = execute_operator(
            OperatorRegistry.get("filter_examples"),
            {"data": CLASSIFICATION_DATA},
            {"expression": "target == 0"})
        self.assertTrue(all(row["target"] == 0 for row in outputs["data"]))

    def test_sample(self):
        outputs = execute_operator(
            OperatorRegistry.get("sample"),
            {"data": CLASSIFICATION_DATA},
            {"sample_size": 5, "with_replacement": False, "random_seed": 42})
        self.assertEqual(len(outputs["data"]), 5)

    def test_impute_missing_advanced(self):
        data = [{"a": 1, "b": 10}, {"a": 2, "b": None}, {"a": 3, "b": 30}]
        outputs = execute_operator(
            OperatorRegistry.get("impute_missing_advanced"),
            {"data": data}, {"strategy": "mean", "fill_value": "0"})
        self.assertEqual(len(outputs["data"]), len(data))


class TestBlendingOperatorsExecution(unittest.TestCase):
    """Test blending operators execution."""

    def test_join(self):
        outputs = execute_operator(
            OperatorRegistry.get("join"),
            {"left": LEFT_DATA, "right": RIGHT_DATA},
            {"join_type": "inner", "left_keys": "id", "right_keys": "id"})
        self.assertEqual(len(outputs["data"]), 2)

    def test_union(self):
        outputs = execute_operator(
            OperatorRegistry.get("union"),
            {"data1": LEFT_DATA, "data2": LEFT_DATA}, {})
        self.assertEqual(len(outputs["data"]), 4)

    def test_aggregate(self):
        outputs = execute_operator(
            OperatorRegistry.get("aggregate"),
            {"data": LEFT_DATA},
            {"group_by": "name", "aggregations": "value:sum"})
        self.assertEqual(len(outputs["data"]), 2)

    def test_pivot(self):
        data = [
            {"id": 1, "key": "A", "val": 10},
            {"id": 1, "key": "B", "val": 20},
            {"id": 2, "key": "A", "val": 30},
        ]
        outputs = execute_operator(
            OperatorRegistry.get("pivot"),
            {"data": data}, {"index": "id", "columns": "key", "values": "val"})
        self.assertGreater(len(outputs["data"]), 0)

    def test_transpose(self):
        outputs = execute_operator(
            OperatorRegistry.get("transpose"),
            {"data": LEFT_DATA}, {})
        self.assertGreater(len(outputs["data"]), 0)

    def test_generate_attributes(self):
        outputs = execute_operator(
            OperatorRegistry.get("generate_attributes"),
            {"data": REGRESSION_DATA},
            {"new_column_name": "z", "expression": "row['x'] + row['y']"})
        self.assertTrue(any("z" in row for row in outputs["data"]))

    def test_sort(self):
        outputs = execute_operator(
            OperatorRegistry.get("sort"),
            {"data": [{"v": 3}, {"v": 1}, {"v": 2}]},
            {"sort_column": "v", "ascending": True})
        self.assertEqual([row["v"] for row in outputs["data"]], [1, 2, 3])


class TestControlOperatorsExecution(unittest.TestCase):
    """Test control operators execution."""

    def test_condition_true_branch(self):
        outputs = execute_operator(
            OperatorRegistry.get("condition"),
            {"data": [{"x": 10}, {"x": 5}]},
            {"column": "x", "operator": ">", "value": "7"})
        self.assertEqual(len(outputs["true_branch"]), 1)
        self.assertEqual(len(outputs["false_branch"]), 1)

    def test_merge_concat_rows(self):
        outputs = execute_operator(
            OperatorRegistry.get("merge"),
            {"data_a": [{"a": 1}], "data_b": [{"a": 2}]},
            {"merge_type": "concat_rows", "key_column": ""})
        self.assertEqual(len(outputs["merged"]), 2)

    def test_loop(self):
        outputs = execute_operator(
            OperatorRegistry.get("loop"),
            {"data": CLASSIFICATION_DATA},
            {"max_iterations": 3, "condition": "count"})
        self.assertIn("result", outputs)
        self.assertIn("continue", outputs)


class TestMLOperatorsExecution(unittest.TestCase):
    """Test ML operators execution."""

    def test_xgboost_train(self):
        result = OperatorRegistry.get("xgboost_train").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "task": "classification",
             "n_estimators": 5, "max_depth": 2})
        self.assertIsInstance(result, OperatorResult)
        self.assertIn("model", result.outputs)
        self.assertTrue(len(result.outputs["model"]) > 0)

    def test_random_forest_train(self):
        result = OperatorRegistry.get("random_forest_train").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "task": "classification",
             "n_estimators": 5, "max_depth": 3})
        self.assertIn("model", result.outputs)

    def test_linear_model_train(self):
        result = OperatorRegistry.get("linear_model_train").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "task": "classification"})
        self.assertIn("model", result.outputs)

    def test_decision_tree(self):
        result = OperatorRegistry.get("decision_tree").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "max_depth": 3})
        self.assertIn("model", result.outputs)

    def test_naive_bayes(self):
        result = OperatorRegistry.get("naive_bayes").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target"})
        self.assertIn("model", result.outputs)

    def test_knn(self):
        result = OperatorRegistry.get("knn").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "k": 3})
        self.assertIn("model", result.outputs)

    def test_svm(self):
        result = OperatorRegistry.get("svm").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "kernel": "rbf", "C": 1.0})
        self.assertIn("model", result.outputs)

    def test_logistic_regression(self):
        result = OperatorRegistry.get("logistic_regression").execute(
            operator_context(), {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "C": 1.0, "max_iter": 100})
        self.assertIn("model", result.outputs)

    def test_kmeans_clustering(self):
        outputs = execute_operator(
            OperatorRegistry.get("kmeans_clustering"),
            {"data": CLUSTER_DATA}, {"k": 3, "max_runs": 3, "random_seed": 42})
        self.assertIn("clusters", outputs)
        self.assertTrue(any("cluster" in row for row in outputs["clusters"]))

    def test_dbscan(self):
        outputs = execute_operator(
            OperatorRegistry.get("dbscan"),
            {"data": CLUSTER_DATA}, {"eps": 5.0, "min_points": 2})
        self.assertIn("clusters", outputs)

    def test_apriori(self):
        outputs = execute_operator(
            OperatorRegistry.get("apriori"),
            {"data": TRANSACTION_DATA},
            {"min_support": 0.1, "min_confidence": 0.3})
        self.assertIn("rules", outputs)

    def test_fp_growth(self):
        outputs = execute_operator(
            OperatorRegistry.get("fp_growth"),
            {"data": TRANSACTION_DATA},
            {"min_support": 0.1, "min_confidence": 0.3})
        self.assertIn("rules", outputs)

    def test_random_forest_regression(self):
        result = OperatorRegistry.get("random_forest_regression").execute(
            operator_context(), {"data": REGRESSION_DATA},
            {"target_column": "y", "n_estimators": 5, "max_depth": 3})
        self.assertIn("model", result.outputs)

    def test_svm_regression(self):
        result = OperatorRegistry.get("svm_regression").execute(
            operator_context(), {"data": REGRESSION_DATA},
            {"target_column": "y", "kernel": "rbf", "C": 1.0, "epsilon": 0.1})
        self.assertIn("model", result.outputs)

    def test_apply_model(self):
        model_bytes = _trained_model_bytes()
        outputs = execute_operator(
            OperatorRegistry.get("apply_model"),
            {"model": model_bytes, "data": CLASSIFICATION_DATA}, {})
        self.assertIn("data", outputs)
        self.assertTrue(any("prediction" in row for row in outputs["data"]))


class TestEvaluationOperatorsExecution(unittest.TestCase):
    """Test evaluation operators execution."""

    def test_anomaly_eval(self):
        outputs = execute_operator(
            OperatorRegistry.get("anomaly_eval"),
            {"data": EVAL_DATA},
            {"target_column": "Fault", "flag_column": "outlier"})
        self.assertIn("metrics", outputs)

    def test_classification_eval(self):
        model_bytes = _trained_model_bytes()
        outputs = execute_operator(
            OperatorRegistry.get("classification_eval"),
            {"model": model_bytes, "test": CLASSIFICATION_DATA},
            {"target_column": "target"})
        self.assertIn("metrics", outputs)

    def test_classification_eval_detailed(self):
        model_bytes = _trained_model_bytes()
        outputs = execute_operator(
            OperatorRegistry.get("classification_eval_detailed"),
            {"model": model_bytes, "test": CLASSIFICATION_DATA},
            {"target_column": "target"})
        self.assertIn("metrics", outputs)

    def test_regression_eval(self):
        from sklearn.linear_model import LinearRegression
        import joblib
        import pandas as pd
        df = pd.DataFrame(REGRESSION_DATA)
        model = LinearRegression().fit(df[["x"]], df["y"])
        buf = io.BytesIO(); joblib.dump(model, buf)
        outputs = execute_operator(
            OperatorRegistry.get("regression_eval"),
            {"model": buf.getvalue(), "test": REGRESSION_DATA},
            {"target_column": "y"})
        self.assertIn("metrics", outputs)

    def test_model_comparison(self):
        model_bytes = _trained_model_bytes()
        outputs = execute_operator(
            OperatorRegistry.get("model_comparison"),
            {"model_a": model_bytes, "model_b": model_bytes, "test": CLASSIFICATION_DATA},
            {"target_column": "target", "metric": "accuracy"})
        self.assertIn("comparison", outputs)

    def test_cross_validation(self):
        outputs = execute_operator(
            OperatorRegistry.get("cross_validation"),
            {"data": CLASSIFICATION_DATA},
            {"target_column": "target", "cv_folds": 3, "model_type": "logistic"})
        self.assertIn("avg_metrics", outputs)


class TestDLOperatorsMetadata(unittest.TestCase):
    """Test DL operators registration and metadata."""

    def test_mlp_classifier_registered(self):
        op = OperatorRegistry.get("mlp_classifier")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "dl")

    def test_mlp_regressor_registered(self):
        op = OperatorRegistry.get("mlp_regressor")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "dl")

    def test_cnn1d_classifier_registered(self):
        op = OperatorRegistry.get("cnn1d_classifier")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "dl")

    def test_dl_operators_have_model_output(self):
        for op_id in ["mlp_classifier", "mlp_regressor", "cnn1d_classifier"]:
            op = OperatorRegistry.get(op_id)
            output_names = [p.name for p in op.outputs]
            self.assertIn("model", output_names, f"{op_id} missing 'model' output")


class TestMechanismOperatorsMetadata(unittest.TestCase):
    """Test mechanism operators registration and metadata."""

    MECHANISM_IDS = [
        "mechanism_thermal", "mechanism_nugget", "mechanism_lobe",
        "mechanism_splash", "mechanism_stress", "mechanism_gate",
    ]

    def test_all_mechanism_operators_registered(self):
        for op_id in self.MECHANISM_IDS:
            op = OperatorRegistry.get(op_id)
            self.assertIsNotNone(op, f"{op_id} not registered")
            self.assertEqual(op.category, "mechanism",
                f"{op_id} category is {op.category}, expected 'mechanism'")

    def test_mechanism_operators_have_parameters(self):
        for op_id in self.MECHANISM_IDS:
            op = OperatorRegistry.get(op_id)
            self.assertGreater(len(op.parameters), 0,
                f"{op_id} has no parameters")


class TestOptimizationOperatorsMetadata(unittest.TestCase):
    """Test optimization operators registration and metadata."""

    def test_optimize_grid_registered(self):
        op = OperatorRegistry.get("optimize_grid")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "optimization")

    def test_optimize_evolutionary_registered(self):
        op = OperatorRegistry.get("optimize_evolutionary")
        self.assertIsNotNone(op)
        self.assertEqual(op.category, "optimization")


class TestUtilityOperatorsMetadata(unittest.TestCase):
    """Test utility operators registration and metadata."""

    UTILITY_IDS = ["python_script", "collect", "macro", "write_as_text"]

    def test_all_utility_operators_registered(self):
        for op_id in self.UTILITY_IDS:
            op = OperatorRegistry.get(op_id)
            self.assertIsNotNone(op, f"{op_id} not registered")


class TestSelectAttributesOperator(unittest.TestCase):
    def test_selects_multiple_columns(self):
        op = OperatorRegistry.get("select_attributes")
        outputs = execute_operator(
            op,
            {"data": [{"a": 1, "b": 2, "c": 3}]},
            {"columns": "a,c", "invert": False},
        )
        self.assertEqual(outputs["data"], [{"a": 1, "c": 3}])

    def test_rejects_unknown_column_instead_of_silently_dropping_it(self):
        op = OperatorRegistry.get("select_attributes")
        with self.assertRaises(ValueError):
            execute_operator(
                op,
                {"data": [{"a": 1, "b": 2}]},
                {"columns": "a,missing", "invert": False},
            )


class TestVisualizationOperatorsMetadata(unittest.TestCase):
    """Test visualization operators registration and metadata."""

    VIZ_IDS = [
        "data_table", "data_stats", "roc_curve", "feature_importance",
        "distribution_plot", "scatter_plot", "histogram", "line_chart",
        "confusion_matrix_plot", "box_plot", "bar_chart",
    ]

    def test_all_visualization_operators_registered(self):
        for op_id in self.VIZ_IDS:
            op = OperatorRegistry.get(op_id)
            self.assertIsNotNone(op, f"{op_id} not registered")
            self.assertEqual(op.category, "visualization",
                f"{op_id} category is {op.category}")


class TestNotifyAdminsThreshold(unittest.TestCase):
    """告警管理员阈值节流：每累计 N 行报错通知一次，数据始终透传。

    未配置报错数据集或阈值为 1 时保持旧行为（每行都通知）。
    """

    ROWS = [{"prediction": 1}]

    def _run(self, row_count: int, threshold: int, dataset_id: str = "ds-1"):
        from types import SimpleNamespace
        from unittest.mock import patch

        from tests.operator_test_utils import TestLogger

        operator = OperatorRegistry.get("notify_admins")
        context = OperatorContext(
            run_id="t", node_id="t", project_id="p-1",
            artifact_service=SimpleNamespace(
                db=None,
                resolve=lambda artifact_id, project_id, expected_type=None: SimpleNamespace(
                    metadata_={"row_count": row_count},
                ),
            ),
            cancel_requested=lambda: False, logger=TestLogger(),
        )
        params = {"title": "告警", "message": "报错回流", "severity": "warning"}
        if threshold is not None:
            params["threshold_rows"] = threshold
        if dataset_id is not None:
            params["error_dataset_artifact_id"] = dataset_id
        with patch("app.services.closed_loop_actions.notify_project_admins") as notify:
            notify.return_value = 2
            result = operator.execute(context, {"data": self.ROWS}, params)
        return result, notify

    def test_suppresses_below_threshold(self):
        result, notify = self._run(row_count=2, threshold=3)
        notify.assert_not_called()
        self.assertEqual(result.metrics["notified"], 0.0)
        self.assertEqual(result.metrics["total_rows"], 2.0)
        # 数据透传：重训阈值节点不依赖通知是否发出
        self.assertEqual(result.outputs["data"], self.ROWS)

    def test_notifies_on_threshold_multiple(self):
        result, notify = self._run(row_count=3, threshold=3)
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(result.metrics["notified"], 1.0)
        self.assertIn("累计 3 行", notify.call_args.kwargs["body"])

    def test_threshold_one_keeps_legacy_always_notify(self):
        result, notify = self._run(row_count=7, threshold=1)
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(result.metrics["notified"], 1.0)

    def test_without_dataset_id_always_notifies(self):
        result, notify = self._run(row_count=5, threshold=3, dataset_id="")
        self.assertEqual(notify.call_count, 1)
        self.assertEqual(result.metrics["notified"], 1.0)


if __name__ == "__main__":
    unittest.main()
