from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import pandas as pd


@register_operator
class DataTableOp(BaseOperator):
    id = "data_table"
    name = "Data Table"
    category = "visualization"
    description = "Display data in table view"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("view", "Params", "Data Preview")]
    parameters = []

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        data = inputs.get("data", [])
        return {"view": data}

    def get_preview(self, outputs):
        data = outputs.get("view", [])
        return {"data": data[:10], "total_rows": len(data)}


@register_operator
class DataStatsOp(BaseOperator):
    id = "data_stats"
    name = "Data Statistics"
    category = "visualization"
    description = "Compute statistics of dataset"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("stats", "Params", "Statistics")]
    parameters = []

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        stats = {}
        if numeric_cols:
            desc = df[numeric_cols].describe()
            stats = desc.to_dict()
        stats["row_count"] = len(df)
        stats["column_count"] = len(df.columns)
        stats["columns"] = list(df.columns)
        return {"stats": stats}

    def get_preview(self, outputs):
        return outputs

import numpy as np
import io
import base64
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from sklearn.metrics import roc_curve, auc


@register_operator
class ROCCurve(BaseOperator):
    id = "roc_curve"
    name = "ROC Curve"
    category = "visualization"
    description = "Generate ROC curve for classification model"
    inputs = [
        PortSpec("model", "Model", "Trained Model"),
        PortSpec("test", "DataTable", "Test Data"),
    ]
    outputs = [PortSpec("chart", "Chart", "ROC Curve")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("positive_class", "str", "", "Positive Class Label"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        import joblib
        model_bytes = inputs.get("model")
        test_data = inputs.get("test", [])
        target = params.get("target_column", "target")
        positive_class = params.get("positive_class", "")

        model = joblib.loads(model_bytes)
        df = pd.DataFrame(test_data)
        X_test = df.drop(columns=[target])
        y_test = df[target]

        for col in X_test.select_dtypes(include=["object", "category"]).columns:
            X_test[col] = X_test[col].astype("category").cat.codes

        if positive_class:
            y_test_bin = (y_test == positive_class).astype(int)
        else:
            y_test_bin = y_test

        if hasattr(model, "predict_proba"):
            y_score = model.predict_proba(X_test)
            if y_score.shape[1] == 2:
                y_score = y_score[:, 1]
            else:
                y_score = y_score[:, -1]
        else:
            y_score = model.predict(X_test)

        fpr, tpr, _ = roc_curve(y_test_bin, y_score)
        roc_auc = auc(fpr, tpr)

        fig, ax = plt.subplots(figsize=(7, 5))
        ax.plot(fpr, tpr, label=f"ROC curve (AUC = {roc_auc:.3f})")
        ax.plot([0, 1], [0, 1], "k--", label="Random")
        ax.set_xlabel("False Positive Rate")
        ax.set_ylabel("True Positive Rate")
        ax.set_title("ROC Curve")
        ax.legend(loc="lower right")
        ax.set_xlim([0, 1])
        ax.set_ylim([0, 1.05])

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        chart_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return {"chart": chart_b64}

    def get_preview(self, outputs):
        return outputs


@register_operator
class FeatureImportance(BaseOperator):
    id = "feature_importance"
    name = "Feature Importance"
    category = "visualization"
    description = "Plot feature importance for trained model"
    inputs = [
        PortSpec("model", "Model", "Trained Model"),
        PortSpec("train", "DataTable", "Training Data"),
    ]
    outputs = [PortSpec("chart", "Chart", "Feature Importance")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("top_n", "int", 10, "Top N Features"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        import joblib
        model_bytes = inputs.get("model")
        train_data = inputs.get("train", [])
        target = params.get("target_column", "target")
        top_n = int(params.get("top_n", 10))

        model = joblib.loads(model_bytes)
        df = pd.DataFrame(train_data)
        X = df.drop(columns=[target])

        for col in X.select_dtypes(include=["object", "category"]).columns:
            X[col] = X[col].astype("category").cat.codes

        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
        elif hasattr(model, "coef_"):
            importances = np.abs(model.coef_[0]) if model.coef_.ndim > 1 else np.abs(model.coef_)
        else:
            return {"chart": None, "error": "Model does not support feature importance"}

        feature_names = X.columns.tolist()
        indices = np.argsort(importances)[::-1][:top_n]

        fig, ax = plt.subplots(figsize=(8, 5))
        ax.barh(range(len(indices)), importances[indices][::-1])
        ax.set_yticks(range(len(indices)))
        ax.set_yticklabels([feature_names[i] for i in indices[::-1]])
        ax.set_xlabel("Importance")
        ax.set_title(f"Top {len(indices)} Feature Importance")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        chart_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return {"chart": chart_b64}

    def get_preview(self, outputs):
        return outputs


@register_operator
class DistributionPlot(BaseOperator):
    id = "distribution_plot"
    name = "Distribution Plot"
    category = "visualization"
    description = "Plot distributions of numerical columns"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("chart", "Chart", "Distribution Plot")]
    parameters = [
        ParamSpec("columns", "str", "", "Columns (comma-separated, empty=all)"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        columns_str = params.get("columns", "")
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()

        if columns_str:
            selected = [c.strip() for c in columns_str.split(",") if c.strip()]
            cols = [c for c in selected if c in numeric_cols]
        else:
            cols = numeric_cols

        if not cols:
            return {"chart": None, "error": "No numerical columns to plot"}

        n_cols = min(3, len(cols))
        n_rows = (len(cols) + n_cols - 1) // n_cols
        fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 4 * n_rows))
        axes_flat = np.atleast_1d(axes).ravel()

        for i, col in enumerate(cols):
            axes_flat[i].hist(df[col].dropna(), bins=30, edgecolor="black", alpha=0.7)
            axes_flat[i].set_title(f"Distribution of {col}")
            axes_flat[i].set_xlabel(col)
            axes_flat[i].set_ylabel("Frequency")

        for j in range(len(cols), len(axes_flat)):
            axes_flat[j].set_visible(False)

        plt.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        chart_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

        return {"chart": chart_b64}

    def get_preview(self, outputs):
        return outputs
