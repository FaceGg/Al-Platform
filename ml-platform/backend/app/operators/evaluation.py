from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import pandas as pd
import numpy as np
import io
import base64
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, confusion_matrix, mean_squared_error, mean_absolute_error, r2_score


@register_operator
class ClassificationEval(BaseOperator):
    id = "classification_eval"
    name = "Classification Evaluation"
    category = "evaluation"
    description = "Evaluate classification model performance"
    inputs = [
        PortSpec("model", "Model", "Trained Model"),
        PortSpec("test", "DataTable", "Test Data"),
    ]
    outputs = [
        PortSpec("metrics", "Params", "Metrics"),
        PortSpec("chart", "Chart", "Confusion Matrix"),
    ]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        import joblib
        model_bytes = inputs.get("model")
        test_data = inputs.get("test", [])
        target = params.get("target_column", "target")

        model = joblib.loads(model_bytes)
        df = pd.DataFrame(test_data)
        X_test = df.drop(columns=[target])
        y_test = df[target]

        for col in X_test.select_dtypes(include=["object", "category"]).columns:
            X_test[col] = X_test[col].astype("category").cat.codes

        y_pred = model.predict(X_test)

        metrics = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision": float(precision_score(y_test, y_pred, average="weighted", zero_division=0)),
            "recall": float(recall_score(y_test, y_pred, average="weighted", zero_division=0)),
            "f1_score": float(f1_score(y_test, y_pred, average="weighted", zero_division=0)),
        }

        cm = confusion_matrix(y_test, y_pred)
        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
        ax.figure.colorbar(im, ax=ax)
        ax.set_xticks(np.arange(len(np.unique(y_test))))
        ax.set_yticks(np.arange(len(np.unique(y_test))))
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual")
        ax.set_title("Confusion Matrix")
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                ax.text(j, i, str(cm[i, j]), ha="center", va="center")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        chart_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return {"metrics": metrics, "chart": chart_b64}

    def get_preview(self, outputs):
        return outputs


@register_operator
class RegressionEval(BaseOperator):
    id = "regression_eval"
    name = "Regression Evaluation"
    category = "evaluation"
    description = "Evaluate regression model performance"
    inputs = [
        PortSpec("model", "Model", "Trained Model"),
        PortSpec("test", "DataTable", "Test Data"),
    ]
    outputs = [PortSpec("metrics", "Params", "Metrics")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        import joblib
        model_bytes = inputs.get("model")
        test_data = inputs.get("test", [])
        target = params.get("target_column", "target")

        model = joblib.loads(model_bytes)
        df = pd.DataFrame(test_data)
        X_test = df.drop(columns=[target])
        y_test = df[target]

        for col in X_test.select_dtypes(include=["object", "category"]).columns:
            X_test[col] = X_test[col].astype("category").cat.codes

        y_pred = model.predict(X_test)
        mse = mean_squared_error(y_test, y_pred)
        rmse = float(np.sqrt(mse))

        metrics = {
            "mse": float(mse),
            "rmse": rmse,
            "mae": float(mean_absolute_error(y_test, y_pred)),
            "r2": float(r2_score(y_test, y_pred)),
        }

        return {"metrics": metrics}
