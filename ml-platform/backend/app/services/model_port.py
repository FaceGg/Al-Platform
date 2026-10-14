"""Model-port helpers for the apply_model serving operator.

`load_model_port` accepts the upstream model port bytes (a joblib-serialized
estimator, or a pickle payload marked ``__framework__: pytorch``) and returns
either a predictor or a pytorch-package marker for the caller. Predict
failures surface the model's expected feature list — the usual cause is an
invoked record whose fields don't match the training features.

Deserialization here is platform-internal by design: the bytes come from
training-operator outputs or load_model_artifact, both written by the
platform itself and resolved through project-scoped artifact access.
"""
import io
import pickle

import joblib
import pandas as pd

from app.engine.operator_contract import OperatorResult


def load_model_port(model_bytes: bytes):
    """Return (model, pytorch_pkg). Exactly one of the two is non-None."""
    try:
        return joblib.load(io.BytesIO(model_bytes)), None
    except Exception as joblib_error:
        try:
            pkg = pickle.load(io.BytesIO(model_bytes))
        except Exception as unpack_error:
            raise RuntimeError(
                f"模型端口数据无法加载（joblib: {joblib_error}；pickle: {unpack_error}）；"
                "请确认上游连接的是 load_model_artifact 或训练算子的模型输出"
            ) from unpack_error
        if not isinstance(pkg, dict) or pkg.get("__framework__") != "pytorch":
            raise RuntimeError(
                f"模型端口数据是 {type(pkg).__name__}，既无可 predict 的估计器也不是 pytorch 包"
            ) from joblib_error
        return None, pkg


def predict_with_hint(model, df: pd.DataFrame):
    """Run model.predict; on failure re-raise with the expected feature list."""
    fc = getattr(model, "feature_names_in_", None)
    if fc is not None:
        avail = [c for c in fc if c in df.columns]
        df_pred = df[avail] if avail else df
    else:
        xtra = [c for c in ["cluster", "prediction", "target"] if c in df.columns]
        df_pred = df.drop(columns=xtra, errors="ignore") if xtra else df
    try:
        return model.predict(df_pred)
    except Exception as predict_error:
        expected = list(fc) if fc is not None else getattr(model, "feature_names_", None)
        hint = (
            f"模型期望 {len(expected)} 个特征（如 {list(expected[:6])}）；"
            if expected else ""
        )
        raise RuntimeError(
            f"模型预测失败：{predict_error}。{hint}"
            "请核对调用 record 的字段名与模型训练特征完全一致"
        ) from predict_error
