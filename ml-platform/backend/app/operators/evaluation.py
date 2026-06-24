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
class ClassificationEvalDetailed(BaseOperator):
    id = "classification_eval_detailed"
    name = "Classification Evaluation (Detailed)"
    category = "evaluation"
    description = "Detailed evaluation with per-label metrics, error analysis, F1 curve"
    inputs = [
        PortSpec("model", "Model", "Trained Model"),
        PortSpec("test", "DataTable", "Test Data"),
    ]
    outputs = [
        PortSpec("metrics", "Params", "Overall Metrics"),
        PortSpec("per_label", "Params", "Per-Label Metrics"),
        PortSpec("chart", "Chart", "Confusion Matrix + F1 Curve"),
        PortSpec("errors", "Params", "Error Analysis"),
    ]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("threshold", "float", 0.5, "Confidence Threshold"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        import joblib
        model_bytes = inputs.get("model")
        test_data = inputs.get("test", [])
        target = params.get("target_column", "target")
        threshold = params.get("threshold", 0.5)

        model = joblib.loads(model_bytes)
        df = pd.DataFrame(test_data)
        X_test = df.drop(columns=[target])
        y_test = df[target]

        for col in X_test.select_dtypes(include=["object", "category"]).columns:
            X_test[col] = X_test[col].astype("category").cat.codes

        y_pred = model.predict(X_test)
        classes = sorted(np.unique(np.concatenate([y_test, y_pred])))

        # Overall metrics
        metrics = {
            "accuracy": float(accuracy_score(y_test, y_pred)),
            "precision_macro": float(precision_score(y_test, y_pred, average="macro", zero_division=0)),
            "recall_macro": float(recall_score(y_test, y_pred, average="macro", zero_division=0)),
            "f1_macro": float(f1_score(y_test, y_pred, average="macro", zero_division=0)),
            "precision_weighted": float(precision_score(y_test, y_pred, average="weighted", zero_division=0)),
            "recall_weighted": float(recall_score(y_test, y_pred, average="weighted", zero_division=0)),
            "f1_weighted": float(f1_score(y_test, y_pred, average="weighted", zero_division=0)),
            "total_samples": len(y_test),
            "threshold": threshold,
        }

        # Per-label analysis
        per_label = []
        cm = confusion_matrix(y_test, y_pred, labels=classes)
        for i, cls in enumerate(classes):
            tp = int(cm[i, i])
            fp = int(cm[:, i].sum() - cm[i, i])
            fn = int(cm[i, :].sum() - cm[i, i])
            tn = int(cm.sum() - tp - fp - fn)
            support = int((y_test == cls).sum())
            per_label.append({
                "class": str(cls),
                "precision": round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0,
                "recall": round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0,
                "f1": round(2*tp/(2*tp+fp+fn), 4) if (2*tp+fp+fn) > 0 else 0,
                "support": support,
                "true_positives": tp, "false_positives": fp,
                "false_negatives": fn, "true_negatives": tn,
            })

        # Error analysis
        errors = []
        for idx in range(len(y_test)):
            if y_pred[idx] != y_test.iloc[idx]:
                errors.append({
                    "index": int(idx),
                    "true_label": str(y_test.iloc[idx]),
                    "predicted_label": str(y_pred[idx]),
                })
        error_stats = {
            "total_errors": len(errors),
            "error_rate": round(len(errors)/len(y_test), 4),
            "error_samples": errors[:50],  # first 50 misclassifications
        }

        # F1-Score curve (across thresholds)
        try:
            if hasattr(model, "predict_proba"):
                y_proba = model.predict_proba(X_test)
                thresholds = np.linspace(0.1, 0.9, 9)
                f1_curve = []
                for t in thresholds:
                    y_pred_t = (y_proba[:, 1] >= t).astype(int) if y_proba.shape[1] == 2 else y_proba.argmax(axis=1)
                    f1_curve.append({"threshold": round(float(t), 2),
                                     "f1": round(float(f1_score(y_test, y_pred_t, average="weighted", zero_division=0)), 4)})
            else:
                f1_curve = [{"threshold": 0.5, "f1": metrics["f1_weighted"]}]
        except:
            f1_curve = [{"threshold": 0.5, "f1": metrics["f1_weighted"]}]

        # Charts: confusion matrix + F1 curve
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
        # Confusion matrix
        im = ax1.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
        fig.colorbar(im, ax=ax1)
        ax1.set_xticks(range(len(classes)))
        ax1.set_yticks(range(len(classes)))
        ax1.set_xticklabels([str(c)[:10] for c in classes], rotation=45)
        ax1.set_yticklabels([str(c)[:10] for c in classes])
        ax1.set_xlabel("Predicted"); ax1.set_ylabel("Actual")
        ax1.set_title("Confusion Matrix")
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                ax1.text(j, i, str(cm[i,j]), ha="center", va="center", fontsize=8)
        # F1 curve
        ax2.plot([f["threshold"] for f in f1_curve], [f["f1"] for f in f1_curve], "b-o")
        ax2.set_xlabel("Threshold"); ax2.set_ylabel("F1 Score")
        ax2.set_title("F1-Score vs Threshold"); ax2.grid(True)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        chart_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return {"metrics": metrics, "per_label": per_label, "chart": chart_b64, "errors": error_stats}

    def get_preview(self, outputs):
        return outputs


@register_operator
class ModelComparison(BaseOperator):
    id = "model_comparison"
    name = "Model Comparison"
    category = "evaluation"
    description = "Compare multiple trained models on the same test set"
    inputs = [
        PortSpec("model_a", "Model", "Model A"),
        PortSpec("model_b", "Model", "Model B"),
        PortSpec("test", "DataTable", "Test Data"),
    ]
    outputs = [PortSpec("comparison", "Params", "Comparison Results")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("metric", "select", "accuracy", "Primary Metric",
                  options=["accuracy", "precision", "recall", "f1"]),
    ]

    def validate(self, inputs):
        return "model_b" in inputs

    def execute(self, inputs, params):
        import joblib
        models = {"A": joblib.loads(inputs.get("model_a")),
                  "B": joblib.loads(inputs.get("model_b"))}
        test_data = inputs.get("test", [])
        target = params.get("target_column", "target")
        metric_name = params.get("metric", "accuracy")
        df = pd.DataFrame(test_data)
        X_test = df.drop(columns=[target])
        y_test = df[target]
        for col in X_test.select_dtypes(include=["object", "category"]).columns:
            X_test[col] = X_test[col].astype("category").cat.codes

        results = {}
        metric_fn = {"accuracy": accuracy_score, "precision": lambda yt,yp: precision_score(yt,yp,average="weighted",zero_division=0),
                      "recall": lambda yt,yp: recall_score(yt,yp,average="weighted",zero_division=0),
                      "f1": lambda yt,yp: f1_score(yt,yp,average="weighted",zero_division=0)}.get(metric_name, accuracy_score)

        for label, model in models.items():
            y_pred = model.predict(X_test)
            results[label] = {
                "accuracy": float(accuracy_score(y_test, y_pred)),
                "precision": float(precision_score(y_test, y_pred, average="weighted", zero_division=0)),
                "recall": float(recall_score(y_test, y_pred, average="weighted", zero_division=0)),
                "f1": float(f1_score(y_test, y_pred, average="weighted", zero_division=0)),
            }

        winner = "A" if results["A"][metric_name] >= results["B"][metric_name] else "B"
        return {"comparison": {"results": results, "winner": winner, "metric": metric_name, "margin": round(abs(results["A"][metric_name] - results["B"][metric_name]), 4)}}
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

