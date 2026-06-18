from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import pandas as pd
import numpy as np
import joblib


@register_operator
class XGBoostTrainer(BaseOperator):
    id = "xgboost_train"
    name = "XGBoost Trainer"
    category = "ml"
    description = "Train an XGBoost model"
    inputs = [PortSpec("train", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("task", "select", "classification", "Task Type", options=["classification", "regression"]),
        ParamSpec("n_estimators", "int", 100, "Number of Estimators"),
        ParamSpec("max_depth", "int", 6, "Max Depth"),
        ParamSpec("learning_rate", "float", 0.1, "Learning Rate"),
        ParamSpec("random_seed", "int", 42, "Random Seed"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        import xgboost as xgb
        data = inputs.get("train", [])
        df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        task = params.get("task", "classification")
        n_estimators = int(params.get("n_estimators", 100))
        max_depth = int(params.get("max_depth", 6))
        learning_rate = float(params.get("learning_rate", 0.1))
        random_seed = int(params.get("random_seed", 42))

        X = df.drop(columns=[target])
        y = df[target]

        for col in X.select_dtypes(include=["object", "category"]).columns:
            X[col] = X[col].astype("category").cat.codes

        if task == "classification":
            model = xgb.XGBClassifier(
                n_estimators=n_estimators, max_depth=max_depth,
                learning_rate=learning_rate, random_state=random_seed,
                use_label_encoder=False, eval_metric="logloss",
            )
        else:
            model = xgb.XGBRegressor(
                n_estimators=n_estimators, max_depth=max_depth,
                learning_rate=learning_rate, random_state=random_seed,
            )
        model.fit(X, y)
        return {"model": joblib.dumps(model)}


@register_operator
class RandomForestTrainer(BaseOperator):
    id = "random_forest_train"
    name = "Random Forest Trainer"
    category = "ml"
    description = "Train a Random Forest model"
    inputs = [PortSpec("train", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("task", "select", "classification", "Task Type", options=["classification", "regression"]),
        ParamSpec("n_estimators", "int", 100, "Number of Estimators"),
        ParamSpec("max_depth", "int", 10, "Max Depth"),
        ParamSpec("random_seed", "int", 42, "Random Seed"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
        data = inputs.get("train", [])
        df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        task = params.get("task", "classification")
        n_estimators = int(params.get("n_estimators", 100))
        max_depth = int(params.get("max_depth", 10))
        random_seed = int(params.get("random_seed", 42))

        X = df.drop(columns=[target])
        y = df[target]

        for col in X.select_dtypes(include=["object", "category"]).columns:
            X[col] = X[col].astype("category").cat.codes

        if task == "classification":
            model = RandomForestClassifier(
                n_estimators=n_estimators, max_depth=max_depth, random_state=random_seed,
            )
        else:
            model = RandomForestRegressor(
                n_estimators=n_estimators, max_depth=max_depth, random_state=random_seed,
            )
        model.fit(X, y)
        return {"model": joblib.dumps(model)}


@register_operator
class LinearModelTrainer(BaseOperator):
    id = "linear_model_train"
    name = "Linear Model Trainer"
    category = "ml"
    description = "Train a linear model (regression or classification)"
    inputs = [PortSpec("train", "DataTable", "Training Data")]
    outputs = [PortSpec("model", "Model", "Trained Model")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("task", "select", "classification", "Task Type", options=["classification", "regression"]),
        ParamSpec("random_seed", "int", 42, "Random Seed"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        from sklearn.linear_model import LinearRegression, LogisticRegression
        data = inputs.get("train", [])
        df = pd.DataFrame(data)
        target = params.get("target_column", "target")
        task = params.get("task", "classification")
        random_seed = int(params.get("random_seed", 42))

        X = df.drop(columns=[target])
        y = df[target]

        for col in X.select_dtypes(include=["object", "category"]).columns:
            X[col] = X[col].astype("category").cat.codes

        if task == "classification":
            model = LogisticRegression(random_state=random_seed, max_iter=1000)
        else:
            model = LinearRegression()
        model.fit(X, y)
        return {"model": joblib.dumps(model)}
