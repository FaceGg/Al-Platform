import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import joblib
import numpy as np
from catboost import CatBoostClassifier
from lightgbm import LGBMClassifier
from xgboost import XGBClassifier
from sklearn.cluster import KMeans
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from app.services.onnx_conversion import (
    ConversionError,
    convert_platform_joblib,
    validate_onnx,
)
from app.services import onnx_worker
from app.services.onnx_worker import _apply_resource_limits


class TestOnnxConversion(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "model.joblib"
        self.destination = self.root / "model.onnx"

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def _training_package(model, scaler=None):
        return {
            "model": model,
            "scaler": scaler,
            "feature_schema": [
                {"name": "current", "dtype": "float64"},
                {"name": "voltage", "dtype": "float64"},
            ],
            "target_schema": {
                "name": "fault",
                "dtype": "int64",
                "task": "classification",
            },
            "training_config": {"task": "classification"},
        }

    def _write_classifier(self):
        features = np.asarray([
            [1.0, 2.0],
            [1.2, 2.1],
            [8.0, 9.0],
            [8.5, 9.2],
        ])
        target = np.asarray([0, 0, 1, 1])
        scaler = StandardScaler().fit(features)
        model = LogisticRegression(random_state=0).fit(
            scaler.transform(features),
            target,
        )
        joblib.dump(self._training_package(model, scaler), self.source)

    def test_platform_joblib_converts_to_valid_onnx(self):
        self._write_classifier()

        result = convert_platform_joblib(
            self.source,
            self.destination,
            timeout_seconds=120,
        )

        self.assertEqual(result.input_names, ("features",))
        self.assertIn("label", result.output_names)
        self.assertIn("probabilities", result.output_names)
        self.assertGreaterEqual(result.opset, 15)
        self.assertEqual(result.converter, "skl2onnx")
        self.assertEqual(result.size, self.destination.stat().st_size)
        self.assertEqual(
            result.sha256,
            hashlib.sha256(self.destination.read_bytes()).hexdigest(),
        )
        self.assertEqual(result.feature_schema[0]["name"], "current")
        self.assertEqual(result.output_schema["task"], "classification")

        validated = validate_onnx(
            self.destination,
            result.feature_schema,
            result.output_schema,
        )
        self.assertEqual(validated.sha256, result.sha256)

    def test_worker_import_does_not_load_optional_converter_stacks(self):
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; import app.services.onnx_worker; "
                    "assert not any(name.split('.')[0] in "
                    "{'catboost', 'lightgbm', 'xgboost', 'onnxmltools'} "
                    "for name in sys.modules)"
                ),
            ],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)

    def test_catboost_joblib_converts_to_valid_onnx(self):
        features = np.asarray([
            [1.0, 2.0],
            [1.2, 2.1],
            [8.0, 9.0],
            [8.5, 9.2],
        ])
        target = np.asarray([0, 0, 1, 1])
        model = CatBoostClassifier(
            iterations=5,
            depth=2,
            verbose=False,
            random_seed=0,
            allow_writing_files=False,
        ).fit(features, target)
        joblib.dump(self._training_package(model), self.source)

        result = convert_platform_joblib(
            self.source,
            self.destination,
            timeout_seconds=120,
        )

        self.assertEqual(result.converter, "catboost")
        self.assertEqual(result.output_schema["task"], "classification")
        validated = validate_onnx(
            self.destination,
            result.feature_schema,
            result.output_schema,
        )
        self.assertEqual(validated.sha256, result.sha256)

    def test_supported_automl_tree_models_convert_to_valid_onnx(self):
        features = np.asarray([
            [1.0, 2.0],
            [1.2, 2.1],
            [8.0, 9.0],
            [8.5, 9.2],
        ])
        target = np.asarray([0, 0, 1, 1])
        models = [
            ("extra_trees", "skl2onnx", ExtraTreesClassifier(n_estimators=5, random_state=0, n_jobs=1)),
            ("hist_gradient_boosting", "skl2onnx", HistGradientBoostingClassifier(max_iter=5, random_state=0)),
            ("xgboost", "xgboost", XGBClassifier(n_estimators=5, max_depth=2, n_jobs=1, random_state=0, eval_metric="logloss")),
            ("lightgbm", "lightgbm", LGBMClassifier(n_estimators=5, num_leaves=7, random_state=0, verbosity=-1)),
        ]

        for name, converter, model in models:
            with self.subTest(name=name):
                model.fit(features, target)
                source = self.root / f"{name}.joblib"
                destination = self.root / f"{name}.onnx"
                joblib.dump(self._training_package(model), source)

                result = convert_platform_joblib(source, destination, timeout_seconds=120)

                self.assertEqual(result.converter, converter)
                validated = validate_onnx(
                    destination,
                    result.feature_schema,
                    result.output_schema,
                )
                self.assertEqual(validated.sha256, result.sha256)

    @staticmethod
    def _ensemble_data(labels=(0, 1)):
        rng = np.random.RandomState(7)
        features = np.vstack([
            rng.normal(0.0, 1.0, (60, 2)),
            rng.normal(2.0, 1.0, (60, 2)),
        ])
        target = np.asarray([labels[0]] * 60 + [labels[1]] * 60)
        return features, target

    def _assert_ensemble_matches_sklearn(self, vote, features, name):
        import onnxruntime as ort

        source = self.root / f"{name}.joblib"
        destination = self.root / f"{name}.onnx"
        joblib.dump(self._training_package(vote), source)
        result = convert_platform_joblib(source, destination, timeout_seconds=120)
        self.assertEqual(result.converter, "ensemble")
        self.assertEqual(result.input_names, ("features",))
        self.assertEqual(result.output_names, ("label", "probabilities"))
        validate_onnx(destination, result.feature_schema, result.output_schema)
        session = ort.InferenceSession(str(destination), providers=["CPUExecutionProvider"])
        label, probabilities = session.run(None, {"features": features.astype(np.float32)})
        # 合成图与 VotingClassifier.predict_proba 同口径（加权平均成员概率）
        np.testing.assert_allclose(probabilities, vote.predict_proba(features), atol=1e-4)
        self.assertEqual(list(label), list(vote.predict(features)))

    def test_soft_voting_ensemble_converts_and_matches_sklearn(self):
        """真机 91f51c69 的成员组合（CatBoost+HGB+LightGBM，含两种 ZipMap 输出）
        及 sklearn/XGBoost/MLP 组合：ONNX 概率与标签必须与 sklearn 一致。"""
        from sklearn.ensemble import RandomForestClassifier, VotingClassifier
        from sklearn.neural_network import MLPClassifier

        features, target = self._ensemble_data()
        combos = {
            "catboost_hgb_lightgbm": [
                ("catboost", CatBoostClassifier(iterations=20, depth=3, verbose=False, random_seed=0, allow_writing_files=False)),
                ("hist_gradient_boosting", HistGradientBoostingClassifier(max_iter=10, random_state=0)),
                ("lightgbm", LGBMClassifier(n_estimators=10, num_leaves=7, random_state=0, verbosity=-1)),
            ],
            "rf_lr_mlp_xgboost": [
                ("random_forest", RandomForestClassifier(n_estimators=8, random_state=0, n_jobs=1)),
                ("logistic", LogisticRegression(random_state=0)),
                ("mlp", MLPClassifier(hidden_layer_sizes=(8,), max_iter=400, random_state=0)),
                ("xgboost", XGBClassifier(n_estimators=8, max_depth=2, n_jobs=1, random_state=0, eval_metric="logloss")),
            ],
        }
        for name, estimators in combos.items():
            with self.subTest(combo=name):
                weights = [0.5, 0.3, 0.2] if len(estimators) == 3 else [0.4, 0.3, 0.2, 0.1]
                vote = VotingClassifier(estimators, voting="soft", weights=weights).fit(features, target)
                self._assert_ensemble_matches_sklearn(vote, features, name)

    def test_ensemble_with_string_labels_emits_string_label(self):
        from sklearn.ensemble import RandomForestClassifier, VotingClassifier

        features, target = self._ensemble_data(labels=("ok", "ng"))
        vote = VotingClassifier([
            ("random_forest", RandomForestClassifier(n_estimators=8, random_state=0, n_jobs=1)),
            ("logistic", LogisticRegression(random_state=0)),
        ], voting="soft").fit(features, target)
        import onnxruntime as ort

        source = self.root / "string-labels.joblib"
        destination = self.root / "string-labels.onnx"
        package = self._training_package(vote)
        package["target_schema"]["dtype"] = "object"
        joblib.dump(package, source)
        result = convert_platform_joblib(source, destination, timeout_seconds=120)
        self.assertEqual(result.converter, "ensemble")
        label, _probabilities = ort.InferenceSession(
            str(destination), providers=["CPUExecutionProvider"],
        ).run(None, {"features": features.astype(np.float32)})
        self.assertEqual([str(item) for item in label], [str(item) for item in vote.predict(features)])

    def test_hard_voting_ensemble_is_rejected(self):
        from sklearn.ensemble import RandomForestClassifier, VotingClassifier

        features, target = self._ensemble_data()
        vote = VotingClassifier([
            ("random_forest", RandomForestClassifier(n_estimators=4, random_state=0, n_jobs=1)),
            ("logistic", LogisticRegression(random_state=0)),
        ], voting="hard").fit(features, target)
        joblib.dump(self._training_package(vote), self.source)
        with self.assertRaises(ConversionError) as raised:
            convert_platform_joblib(self.source, self.destination)
        self.assertEqual(raised.exception.code, "MODEL_CONVERSION_UNSUPPORTED")

    def test_mlp_classifier_converts_with_skl2onnx(self):
        """MLP 补进白名单：AutoML mlp 家族冠军此前一律 MODEL_CONVERSION_UNSUPPORTED。"""
        from sklearn.neural_network import MLPClassifier

        features, target = self._ensemble_data()
        model = MLPClassifier(hidden_layer_sizes=(8,), max_iter=400, random_state=0).fit(features, target)
        joblib.dump(self._training_package(model), self.source)
        result = convert_platform_joblib(self.source, self.destination, timeout_seconds=120)
        self.assertEqual(result.converter, "skl2onnx")

    def test_unknown_estimator_is_rejected(self):
        model = KMeans(n_clusters=2, random_state=0, n_init=1).fit(
            np.asarray([[0.0, 0.0], [1.0, 1.0], [8.0, 8.0]])
        )
        joblib.dump(self._training_package(model), self.source)

        with self.assertRaises(ConversionError) as raised:
            convert_platform_joblib(self.source, self.destination)

        self.assertEqual(raised.exception.code, "MODEL_CONVERSION_UNSUPPORTED")
        self.assertFalse(self.destination.exists())

    def test_malformed_training_package_is_rejected(self):
        joblib.dump({"feature_schema": []}, self.source)

        with self.assertRaises(ConversionError) as raised:
            convert_platform_joblib(self.source, self.destination)

        self.assertEqual(raised.exception.code, "MODEL_CONVERSION_FAILED")
        self.assertFalse(self.destination.exists())

    def test_worker_timeout_has_stable_code(self):
        self._write_classifier()
        with patch(
            "app.services.onnx_conversion.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["python"], timeout=1),
        ):
            with self.assertRaises(ConversionError) as raised:
                convert_platform_joblib(
                    self.source,
                    self.destination,
                    timeout_seconds=1,
                )

        self.assertEqual(raised.exception.code, "MODEL_CONVERSION_TIMEOUT")
        self.assertFalse(self.destination.exists())

    def test_invalid_onnx_is_rejected_without_leaking_parser_details(self):
        self.destination.write_bytes(b"not-an-onnx-model")

        with self.assertRaises(ConversionError) as raised:
            validate_onnx(
                self.destination,
                [
                    {"name": "current", "dtype": "float64"},
                    {"name": "voltage", "dtype": "float64"},
                ],
                {"name": "fault", "dtype": "int64", "task": "classification"},
            )

        self.assertEqual(raised.exception.code, "ONNX_INVALID")
        self.assertEqual(str(raised.exception), "ONNX_INVALID")

    def test_feature_schema_width_must_match_onnx_input(self):
        self._write_classifier()
        result = convert_platform_joblib(self.source, self.destination)

        with self.assertRaises(ConversionError) as raised:
            validate_onnx(
                self.destination,
                [{"name": "current", "dtype": "float64"}],
                result.output_schema,
            )

        self.assertEqual(raised.exception.code, "MODEL_SCHEMA_INVALID")

    def test_worker_result_must_be_valid_json(self):
        self._write_classifier()

        def complete_with_invalid_result(command, **kwargs):
            result_index = command.index("--result") + 1
            Path(command[result_index]).write_text("not-json", encoding="utf-8")
            self.destination.write_bytes(b"invalid")
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "app.services.onnx_conversion.subprocess.run",
            side_effect=complete_with_invalid_result,
        ):
            with self.assertRaises(ConversionError) as raised:
                convert_platform_joblib(self.source, self.destination)

        self.assertEqual(raised.exception.code, "MODEL_CONVERSION_FAILED")
        self.assertFalse(self.destination.exists())

    def test_worker_loads_converter_dependencies_before_address_limit(self):
        features = np.asarray([
            [1.0, 2.0],
            [1.2, 2.1],
            [8.0, 9.0],
            [8.5, 9.2],
        ])
        target = np.asarray([0, 0, 1, 1])
        model = XGBClassifier(
            n_estimators=5,
            max_depth=2,
            n_jobs=1,
            random_state=0,
            eval_metric="logloss",
        ).fit(features, target)
        joblib.dump(self._training_package(model), self.source)

        events = []

        def load_dependencies():
            events.append("dependencies")
            return original_load_dependencies()

        def apply_limits(*, address_space=True):
            events.append(("limits", address_space))

        original_load_dependencies = onnx_worker._onnx_dependencies
        with patch.object(
            onnx_worker,
            "_onnx_dependencies",
            side_effect=load_dependencies,
        ), patch.object(
            onnx_worker,
            "_apply_resource_limits",
            side_effect=apply_limits,
        ):
            payload = onnx_worker._convert(self.source, self.destination)

        self.assertEqual(payload["converter"], "xgboost")
        self.assertEqual(events, ["dependencies", ("limits", True)])
        self.assertTrue(self.destination.is_file())

    @unittest.skipIf(os.name == "nt", "POSIX resource limits only")
    def test_worker_memory_limit_preserves_current_virtual_memory(self):
        import resource

        before = resource.getrlimit(resource.RLIMIT_AS)
        with patch("resource.setrlimit") as set_limit:
            _apply_resource_limits()

        address_space = next(
            call.args[1] for call in set_limit.call_args_list
            if call.args[0] == resource.RLIMIT_AS
        )
        current_virtual_bytes = int(
            Path("/proc/self/statm").read_text(encoding="ascii").split()[0]
        ) * os.sysconf("SC_PAGE_SIZE")
        self.assertGreater(address_space[0], current_virtual_bytes)
        self.assertEqual(resource.getrlimit(resource.RLIMIT_AS), before)


if __name__ == "__main__":
    unittest.main()
