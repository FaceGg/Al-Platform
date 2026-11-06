"""Subprocess entry for converting trusted platform joblib packages."""

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile

import joblib
from sklearn.ensemble import (
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    RandomForestClassifier,
    RandomForestRegressor,
    VotingClassifier,
)
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


def _onnx_dependencies():
    """Load conversion-only dependencies when a conversion is actually requested."""
    try:
        import onnx
        from skl2onnx import convert_sklearn
        from skl2onnx.common.data_types import FloatTensorType
    except ModuleNotFoundError as error:
        raise WorkerError("MODEL_CONVERSION_DEPENDENCY_UNAVAILABLE") from error
    _apply_skl2onnx_bool_compat()
    return onnx, convert_sklearn, FloatTensorType


_SKL2ONNX_BOOL_COMPAT_APPLIED = False


def _apply_skl2onnx_bool_compat() -> None:
    """Coerce boolean tree attributes to int for protobuf 7.x strictness.

    onnx 1.22 (protobuf 7) rejects bool values in AttributeProto.ints
    fields, but skl2onnx 1.20 still passes raw booleans from
    HistGradientBoosting nodes via nodes_missing_value_tracks_true.
    """
    global _SKL2ONNX_BOOL_COMPAT_APPLIED
    if _SKL2ONNX_BOOL_COMPAT_APPLIED:
        return
    from skl2onnx.common import tree_ensemble

    original_add_node = tree_ensemble.add_node

    def add_node_compat(*args, **kwargs):
        value = kwargs.get("nodes_missing_value_tracks_true")
        if isinstance(value, bool):
            kwargs["nodes_missing_value_tracks_true"] = int(value)
        return original_add_node(*args, **kwargs)

    tree_ensemble.add_node = add_node_compat
    _SKL2ONNX_BOOL_COMPAT_APPLIED = True


ALLOWED_MODEL_TYPES = {
    LogisticRegression,
    LinearRegression,
    RandomForestClassifier,
    RandomForestRegressor,
    GradientBoostingClassifier,
    GradientBoostingRegressor,
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
    # AutoML 目录含 mlp 家族；skl2onnx 原生支持，此前漏登记 → MLP 冠军/集成
    # 成员一律 MODEL_CONVERSION_UNSUPPORTED。
    MLPClassifier,
    MLPRegressor,
}

# 集成合成图按各域最高 opset 声明。低于合成默认域版本的成员，只允许跨
# opset 9..17 语义不变的默认域算子；Squeeze/Unsqueeze/Clip/Reduce* 等在
# 11/13/18 改过签名，按高版本声明会静默改语义 → 不在名单内即拒绝转换。
_VERSION_STABLE_DEFAULT_OPS = frozenset({
    "Abs", "Add", "ArgMax", "Cast", "Concat", "Div", "Exp", "Flatten",
    "Gather", "Gemm", "Identity", "Log", "MatMul", "Max", "Min", "Mul",
    "Neg", "Relu", "Reshape", "Sigmoid", "Softmax", "Sqrt", "Sub", "Sum",
    "Tanh", "Transpose",
})
_ENSEMBLE_ML_OPS = frozenset({
    "ArrayFeatureExtractor", "LinearClassifier", "Normalizer", "Scaler",
    "TreeEnsembleClassifier",
})
_ENSEMBLE_TARGET_DEFAULT_OPSET = 17

class WorkerError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _apply_resource_limits(*, address_space: bool = True) -> None:
    if sys.platform == "win32":
        return
    try:
        import resource

        if address_space:
            page_size = os.sysconf("SC_PAGE_SIZE")
            current_virtual_memory = int(
                Path("/proc/self/statm").read_text(encoding="ascii").split()[0]
            ) * page_size
            memory_limit = max(
                4 * 1024 * 1024 * 1024,
                current_virtual_memory + 2 * 1024 * 1024 * 1024,
            )
            resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))
        resource.setrlimit(resource.RLIMIT_CPU, (110, 110))
    except (ImportError, OSError, ValueError):
        return


def _feature_schema(value: object) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise WorkerError("MODEL_CONVERSION_FAILED")
    normalized: list[dict[str, str]] = []
    names: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            name, dtype = item.get("name"), item.get("dtype")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            name, dtype = item
        else:
            raise WorkerError("MODEL_CONVERSION_FAILED")
        name = str(name or "").strip()
        dtype = str(dtype or "").strip().lower()
        if not name or not dtype or name in names:
            raise WorkerError("MODEL_CONVERSION_FAILED")
        names.add(name)
        normalized.append({"name": name, "dtype": dtype})
    return normalized


def _output_schema(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise WorkerError("MODEL_CONVERSION_FAILED")
    name = str(value.get("name") or "prediction").strip()
    dtype = str(value.get("dtype") or "").strip().lower()
    task = str(value.get("task") or "").strip().lower()
    if not name or not dtype or task not in {"classification", "regression"}:
        raise WorkerError("MODEL_CONVERSION_FAILED")
    return {**value, "name": name, "dtype": dtype, "task": task}


def _model_family(model: object) -> str:
    """Identify a supported model without importing optional converter stacks."""
    model_type = type(model)
    if model_type in ALLOWED_MODEL_TYPES:
        return "skl2onnx"
    if model_type is VotingClassifier:
        return "ensemble"
    module = model_type.__module__.split(".", 1)[0]
    name = model_type.__name__
    if module == "catboost" and name in {"CatBoostClassifier", "CatBoostRegressor"}:
        from catboost import CatBoostClassifier, CatBoostRegressor

        if model_type in {CatBoostClassifier, CatBoostRegressor}:
            return "catboost"
    if module == "xgboost" and name in {"XGBClassifier", "XGBRegressor"}:
        from xgboost import XGBClassifier, XGBRegressor

        if model_type in {XGBClassifier, XGBRegressor}:
            return "xgboost"
    if module == "lightgbm" and name in {"LGBMClassifier", "LGBMRegressor"}:
        from lightgbm import LGBMClassifier, LGBMRegressor

        if model_type in {LGBMClassifier, LGBMRegressor}:
            return "lightgbm"
    raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")


def _strip_zipmap(proto):
    """把 ZipMap 序列概率输出改回张量（CatBoost/LightGBM 默认输出 seq(map)）。

    ZipMap 的输入就是 [N, C] float 张量：删掉 ZipMap，用 Identity 把该张量接回
    原输出名，并把图输出声明改为 float 张量——合成图才能逐成员加权求和。"""
    from onnx import TensorProto, helper

    graph = proto.graph
    for node in [item for item in graph.node if item.op_type == "ZipMap"]:
        tensor_name, output_name = node.input[0], node.output[0]
        graph.node.remove(node)
        graph.node.append(helper.make_node(
            "Identity", [tensor_name], [output_name], name=f"{output_name}_as_tensor",
        ))
        outputs = [
            helper.make_tensor_value_info(output_name, TensorProto.FLOAT, [None, None])
            if item.name == output_name else item
            for item in graph.output
        ]
        del graph.output[:]
        graph.output.extend(outputs)
    return proto


def _member_probability_model(member, n_features: int, work_dir: Path):
    """单个已拟合成员 → 输入 "features"、输出 "probabilities" 张量 [N, C] 的 ONNX。

    复用单模型路径的同一套转换器与 opset（sklearn 17 / onnxmltools 15 / CatBoost
    原生导出），保证成员图与单独注册时一致。"""
    family = _model_family(member)
    if family == "ensemble":
        raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")  # 不支持嵌套集成
    onnx, convert_sklearn, FloatTensorType = _onnx_dependencies()
    if family == "catboost":
        with tempfile.TemporaryDirectory(dir=str(work_dir)) as temporary:
            path = Path(temporary) / "member.onnx"
            member.save_model(str(path), format="onnx")
            proto = onnx.load(str(path))
    elif family in {"xgboost", "lightgbm"}:
        if family == "xgboost":
            from onnxmltools import convert_xgboost as converter
        else:
            from onnxmltools import convert_lightgbm as converter
        from onnxmltools.convert.common.data_types import (
            FloatTensorType as OnnxFloatTensorType,
        )
        proto = converter(
            member,
            initial_types=[("features", OnnxFloatTensorType([None, n_features]))],
            target_opset=15,
        )
    else:
        proto = convert_sklearn(
            member,
            initial_types=[("features", FloatTensorType([None, n_features]))],
            target_opset=17,
            options={id(member): {"zipmap": False}},
        )
    return _strip_zipmap(proto)


def _ensemble_opsets(member_protos) -> dict[str, int]:
    """合成图各域 opset 取成员最高版本；低版本成员只允许版本稳定算子。"""
    def domain_of(name: str) -> str:
        return "" if name in ("", "ai.onnx") else name

    versions: dict[str, int] = {"": _ENSEMBLE_TARGET_DEFAULT_OPSET}
    for proto in member_protos:
        for item in proto.opset_import:
            key = domain_of(item.domain)
            versions[key] = max(versions.get(key, 0), int(item.version))
    if set(versions) - {"", "ai.onnx.ml"} or versions.get("ai.onnx.ml", 0) > 3:
        raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
    for proto in member_protos:
        member_default = max(
            (int(item.version) for item in proto.opset_import if domain_of(item.domain) == ""),
            default=0,
        )
        for node in proto.graph.node:
            domain = domain_of(node.domain)
            if domain == "ai.onnx.ml":
                if node.op_type not in _ENSEMBLE_ML_OPS:
                    raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
            elif domain == "":
                if member_default < versions[""] and node.op_type not in _VERSION_STABLE_DEFAULT_OPS:
                    raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
            else:
                raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
    return versions


def _convert_ensemble(model, features, output, destination: Path) -> dict[str, object]:
    """soft-voting 集成 → 单一 ONNX 图（推理运行时无需改动，仍只跑 ONNX）。

    图结构：共享输入 features → 各成员子图（前缀 m{i}_ 隔离命名）→ 概率张量
    × 归一化权重 → Sum → probabilities；ArgMax + Gather(classes_) → label。
    与 VotingClassifier.predict_proba 同口径：Σ w_i·p_i / Σ w_i，成员为其
    estimators_（投票器内部按编码标签 0..C-1 拟合，列序即 classes_ 序）。"""
    import numpy as np

    if output.get("task") != "classification" or getattr(model, "voting", None) != "soft":
        raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
    members = list(getattr(model, "estimators_", None) or [])
    classes = np.asarray(getattr(model, "classes_", []))
    if len(members) < 2 or classes.ndim != 1 or len(classes) < 2:
        raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
    raw_weights = model.weights if model.weights is not None else [1.0] * len(members)
    try:
        weights = [float(value) for value in raw_weights]
    except (TypeError, ValueError):
        raise WorkerError("MODEL_CONVERSION_UNSUPPORTED") from None
    if (
        len(weights) != len(members)
        or any(not math.isfinite(value) or value < 0 for value in weights)
        or sum(weights) <= 0
    ):
        raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
    total = sum(weights)

    onnx, _convert_sklearn, _float_tensor_type = _onnx_dependencies()
    from onnx import TensorProto, compose, helper

    families = {_model_family(member) for member in members}
    if families & {"xgboost", "lightgbm"}:
        import onnxmltools  # noqa: F401 - 先于地址空间上限加载二进制扩展
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        _apply_resource_limits()
        member_protos = [
            _member_probability_model(member, len(features), destination.parent)
            for member in members
        ]
        versions = _ensemble_opsets(member_protos)

        nodes, initializers, value_infos, weighted = [], [], [], []
        for index, proto in enumerate(member_protos):
            prefixed = compose.add_prefix(proto, prefix=f"m{index}_")
            graph = prefixed.graph
            probabilities = f"m{index}_probabilities"
            if len(graph.input) != 1 or probabilities not in {item.name for item in graph.output}:
                raise WorkerError("MODEL_CONVERSION_FAILED")
            nodes.append(helper.make_node(
                "Identity", ["features"], [graph.input[0].name], name=f"m{index}_input",
            ))
            nodes.extend(graph.node)
            initializers.extend(graph.initializer)
            value_infos.extend(graph.value_info)
            weight_name = f"m{index}_weight"
            initializers.append(helper.make_tensor(
                weight_name, TensorProto.FLOAT, [], [weights[index] / total],
            ))
            nodes.append(helper.make_node(
                "Mul", [probabilities, weight_name], [f"m{index}_weighted"],
                name=f"m{index}_weighting",
            ))
            weighted.append(f"m{index}_weighted")
        nodes.append(helper.make_node("Sum", weighted, ["probabilities"], name="soft_vote"))
        nodes.append(helper.make_node(
            "ArgMax", ["probabilities"], ["label_index"], axis=1, keepdims=0, name="vote_argmax",
        ))
        if classes.dtype.kind in "iub" or (
            classes.dtype.kind == "f" and bool(np.all(classes == np.round(classes)))
        ):
            label_type = TensorProto.INT64
            label_values = [int(value) for value in classes]
        else:
            label_type = TensorProto.STRING
            label_values = [str(value).encode("utf-8") for value in classes]
        initializers.append(helper.make_tensor(
            "vote_classes", label_type, [len(classes)], label_values,
        ))
        nodes.append(helper.make_node(
            "Gather", ["vote_classes", "label_index"], ["label"], axis=0, name="vote_label",
        ))
        composed = helper.make_model(
            helper.make_graph(
                nodes,
                "platform_soft_voting_ensemble",
                inputs=[helper.make_tensor_value_info("features", TensorProto.FLOAT, [None, len(features)])],
                outputs=[
                    helper.make_tensor_value_info("label", label_type, [None]),
                    helper.make_tensor_value_info("probabilities", TensorProto.FLOAT, [None, len(classes)]),
                ],
                initializer=initializers,
                value_info=value_infos,
            ),
            opset_imports=[
                helper.make_opsetid(domain, version)
                for domain, version in sorted(versions.items())
            ],
            producer_name="ml-platform-ensemble",
        )
        # IR 版本跟随成员（运行时已能加载这些成员单独转换出的模型），且不低于
        # opset 17 所需的 IR 8。
        composed.ir_version = max([8] + [int(proto.ir_version) for proto in member_protos])
        onnx.checker.check_model(composed)
        onnx.save_model(composed, str(destination))
    except WorkerError:
        raise
    except Exception:
        raise WorkerError("MODEL_CONVERSION_FAILED") from None
    return {
        "ok": True,
        "converter": "ensemble",
        "feature_schema": features,
        "output_schema": output,
        "input_names": ["features"],
        "output_names": ["label", "probabilities"],
        "opset": versions[""],
    }


def _convert(source: Path, destination: Path) -> dict[str, object]:
    try:
        package = joblib.load(source)
    except Exception:
        raise WorkerError("MODEL_CONVERSION_FAILED") from None
    if not isinstance(package, dict):
        raise WorkerError("MODEL_CONVERSION_FAILED")

    model = package.get("model")
    if model is None:
        raise WorkerError("MODEL_CONVERSION_FAILED")
    family = _model_family(model)
    scaler = package.get("scaler")
    if scaler is not None and type(scaler) is not StandardScaler:
        raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")

    features = _feature_schema(package.get("feature_schema"))
    output = _output_schema(package.get("target_schema"))

    if family == "ensemble":
        if scaler is not None:
            raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
        return _convert_ensemble(model, features, output, destination)

    if family == "catboost":
        if scaler is not None:
            raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
        try:
            from catboost import CatBoostClassifier, CatBoostRegressor

            if type(model) not in {CatBoostClassifier, CatBoostRegressor}:
                raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
            _apply_resource_limits()
            model.save_model(str(destination), format="onnx")
        except Exception:
            raise WorkerError("MODEL_CONVERSION_FAILED") from None
        return {
            "ok": True,
            "converter": "catboost",
            "feature_schema": features,
            "output_schema": output,
            "input_names": [],
            "output_names": [],
            "opset": 0,
        }

    if family in {"xgboost", "lightgbm"}:
        if scaler is not None:
            raise WorkerError("MODEL_CONVERSION_UNSUPPORTED")
        try:
            onnx, _convert_sklearn, _float_tensor_type = _onnx_dependencies()
            if family == "xgboost":
                from onnxmltools import convert_xgboost as converter
                from onnxmltools.convert.common.data_types import (
                    FloatTensorType as OnnxFloatTensorType,
                )
            else:
                from onnxmltools import convert_lightgbm as converter
                from onnxmltools.convert.common.data_types import (
                    FloatTensorType as OnnxFloatTensorType,
                )
            _apply_resource_limits()
            converted = converter(
                model,
                initial_types=[
                    ("features", OnnxFloatTensorType([None, len(features)])),
                ],
                target_opset=15,
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            onnx.save_model(converted, str(destination))
        except Exception:
            raise WorkerError("MODEL_CONVERSION_FAILED") from None
        return {
            "ok": True,
            "converter": family,
            "feature_schema": features,
            "output_schema": output,
            "input_names": [item.name for item in converted.graph.input],
            "output_names": [item.name for item in converted.graph.output],
            "opset": max((item.version for item in converted.opset_import), default=0),
        }

    estimator = model
    if scaler is not None:
        estimator = Pipeline([("scaler", scaler), ("model", model)])

    options = None
    if output["task"] == "classification":
        options = {id(model): {"zipmap": False}}
    try:
        onnx, convert_sklearn, FloatTensorType = _onnx_dependencies()
        _apply_resource_limits()
        converted = convert_sklearn(
            estimator,
            initial_types=[
                ("features", FloatTensorType([None, len(features)])),
            ],
            target_opset=17,
            options=options,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        onnx.save_model(converted, str(destination))
    except Exception:
        raise WorkerError("MODEL_CONVERSION_FAILED") from None

    return {
        "ok": True,
        "converter": "skl2onnx",
        "feature_schema": features,
        "output_schema": output,
        "input_names": [item.name for item in converted.graph.input],
        "output_names": [item.name for item in converted.graph.output],
        "opset": max(
            (item.version for item in converted.opset_import),
            default=0,
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    arguments = parser.parse_args(argv)
    # Bound CPU time during dependency loading; defer the address-space cap
    # until optional binary extensions have been imported.
    _apply_resource_limits(address_space=False)

    try:
        payload = _convert(arguments.source, arguments.destination)
        return_code = 0
    except WorkerError as error:
        payload = {"ok": False, "code": error.code}
        return_code = 2
        try:
            arguments.destination.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        arguments.result.write_text(
            json.dumps(payload, separators=(",", ":")),
            encoding="utf-8",
        )
    except (OSError, UnicodeError):
        return 3
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
