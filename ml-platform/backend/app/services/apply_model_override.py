# -*- coding: utf-8 -*-
"""Apply-model override installer, layered on app.services.model_port.

The legacy apply_model implementation treated ANY failure — including a plain
feature mismatch between the invoked record and the training features — as a
load failure and fell into a pickle fallback, surfacing "invalid load key"
instead of the real cause. This module swaps the registered operator's
handler (the registry keeps the last assignment) so predict failures carry
the model's expected feature list. The legacy path remains only for pytorch
packages.
"""
import pandas as pd

from app.engine.operator_contract import OperatorResult
from app.engine.registry import OperatorRegistry
from app.services.model_port import load_model_port, predict_with_hint


def install_apply_model_override():
    op = OperatorRegistry.get("apply_model")
    if op is None or getattr(op, "_model_port_override_installed", False):
        return
    original = op.execute

    def run_with_feature_hint(context, inputs, params):
        model, pytorch_pkg = load_model_port(inputs.get("model"))
        if isinstance(model, dict):
            # Model-library/AutoML packages wrap the estimator; older graphs
            # may wire a package directly into the model port.
            for key in ("model", "estimator", "clf", "pipeline", "best_model"):
                candidate = model.get(key)
                if candidate is not None and hasattr(candidate, "predict"):
                    model = candidate
                    break
        if pytorch_pkg is not None:
            return original(context, inputs, params)
        data = inputs.get("data", [])
        if isinstance(data, pd.DataFrame):
            frame = data.copy()
        else:
            records = data if isinstance(data, list) else [data]
            frame = pd.json_normalize(list(records or []))
        frame = frame.apply(
            lambda col: col.astype("category").cat.codes
            if str(col.dtype) in ("object", "category") else col
        )
        predictions = predict_with_hint(model, frame)
        rows = frame.to_dict(orient="records")
        return OperatorResult(outputs={
            "data": [
                {**row, "prediction": pred}
                for row, pred in zip(rows, predictions)
            ]
        })

    op.execute = run_with_feature_hint
    op._model_port_override_installed = True
