from app.engine.operator_contract import OperatorContext, OperatorResult
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

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        return OperatorResult(outputs={"view": data})

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

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
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
        return OperatorResult(outputs={"stats": stats})

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

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        import joblib
        model_bytes = inputs.get("model")
        test_data = inputs.get("test", [])
        target = params.get("target_column", "target")
        positive_class = params.get("positive_class", "")

        model = joblib.load(io.BytesIO(model_bytes))
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

        return OperatorResult(outputs={"chart": chart_b64})

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
        PortSpec("data", "DataTable", "Training Data"),
    ]
    outputs = [PortSpec("chart", "Chart", "Feature Importance")]
    parameters = [
        ParamSpec("target_column", "str", "target", "Target Column"),
        ParamSpec("top_n", "int", 10, "Top N Features"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        import joblib
        model_bytes = inputs.get("model")
        train_data = inputs.get("data", [])
        target = params.get("target_column", "target")
        top_n = int(params.get("top_n", 10))

        model = joblib.load(io.BytesIO(model_bytes))
        df = pd.DataFrame(train_data)
        X = df.drop(columns=[target])

        for col in X.select_dtypes(include=["object", "category"]).columns:
            X[col] = X[col].astype("category").cat.codes

        if hasattr(model, "feature_importances_"):
            importances = model.feature_importances_
        elif hasattr(model, "coef_"):
            importances = np.abs(model.coef_[0]) if model.coef_.ndim > 1 else np.abs(model.coef_)
        else:
            return OperatorResult(outputs={"chart": None, "error": "Model does not support feature importance"})

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

        return OperatorResult(outputs={"chart": chart_b64})

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

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
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
            return OperatorResult(outputs={"chart": None, "error": "No numerical columns to plot"})

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

        return OperatorResult(outputs={"chart": chart_b64})

    def get_preview(self, outputs):
        return outputs


@register_operator
class ScatterPlot(BaseOperator):
    id = "scatter_plot"
    name = "Scatter Plot"
    category = "visualization"
    description = "Generate scatter plot for two numerical columns"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("chart", "Chart", "Scatter Plot")]
    parameters = [
        ParamSpec("x_column", "str", "", "X-axis Column"),
        ParamSpec("y_column", "str", "", "Y-axis Column"),
        ParamSpec("color_column", "str", "", "Color By Column (optional)"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        x_col = params.get("x_column", "")
        y_col = params.get("y_column", "")
        color_col = params.get("color_column", "")

        numeric = df.select_dtypes(include=["number"]).columns.tolist()
        if not x_col or x_col not in df.columns:
            x_col = numeric[0] if numeric else df.columns[0]
        if not y_col or y_col not in df.columns:
            y_col = numeric[1] if len(numeric) > 1 else numeric[0]

        fig, ax = plt.subplots(figsize=(7, 5))
        if color_col and color_col in df.columns:
            scatter = ax.scatter(df[x_col], df[y_col], c=pd.Categorical(df[color_col]).codes, cmap="viridis", alpha=0.7)
            plt.colorbar(scatter, label=color_col)
        else:
            ax.scatter(df[x_col], df[y_col], alpha=0.7)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.set_title(f"{x_col} vs {y_col}")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        return OperatorResult(outputs={"chart": base64.b64encode(buf.getvalue()).decode("utf-8")})


@register_operator
class Histogram(BaseOperator):
    id = "histogram"
    name = "Histogram"
    category = "visualization"
    description = "Generate histogram for a numerical column"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("chart", "Chart", "Histogram")]
    parameters = [
        ParamSpec("column", "str", "", "Column to Plot"),
        ParamSpec("bins", "int", 20, "Number of Bins"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        column = params.get("column", "")
        bins = int(params.get("bins", 20))

        numeric = df.select_dtypes(include=["number"]).columns.tolist()
        if not column or column not in numeric:
            column = numeric[0] if numeric else df.columns[0]

        fig, ax = plt.subplots(figsize=(7, 5))
        ax.hist(df[column].dropna(), bins=bins, edgecolor="black", alpha=0.7)
        ax.set_xlabel(column)
        ax.set_ylabel("Frequency")
        ax.set_title(f"Histogram of {column}")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        return OperatorResult(outputs={"chart": base64.b64encode(buf.getvalue()).decode("utf-8")})


@register_operator
class LineChart(BaseOperator):
    id = "line_chart"
    name = "Line Chart"
    category = "visualization"
    description = "Generate line chart for one or more columns"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("chart", "Chart", "Line Chart")]
    parameters = [
        ParamSpec("x_column", "str", "", "X-axis Column (default: index)"),
        ParamSpec("y_columns", "str", "", "Y Columns (comma-separated)"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        x_col = params.get("x_column", "")
        y_cols_str = params.get("y_columns", "")

        numeric = df.select_dtypes(include=["number"]).columns.tolist()
        if y_cols_str:
            y_cols = [c.strip() for c in y_cols_str.split(",") if c.strip() in numeric]
        else:
            y_cols = numeric[:3] if numeric else []

        fig, ax = plt.subplots(figsize=(8, 5))
        x = df[x_col] if x_col and x_col in df.columns else df.index
        for col in y_cols:
            ax.plot(x, df[col], label=col, marker="o", markersize=3)
        ax.set_xlabel(x_col if x_col else "Index")
        ax.set_ylabel("Value")
        ax.set_title("Line Chart")
        if y_cols:
            ax.legend()

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        return OperatorResult(outputs={"chart": base64.b64encode(buf.getvalue()).decode("utf-8")})


@register_operator
class ConfusionMatrixPlot(BaseOperator):
    id = "confusion_matrix_plot"
    name = "Confusion Matrix Plot"
    category = "visualization"
    description = "Plot confusion matrix from evaluation results"
    inputs = [PortSpec("metrics", "Params", "Evaluation Metrics")]
    outputs = [PortSpec("chart", "Chart", "Confusion Matrix")]
    parameters = [
        ParamSpec("title", "str", "Confusion Matrix", "Chart Title"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        metrics = inputs.get("metrics", {})
        title = params.get("title", "Confusion Matrix")

        # Build confusion matrix from metrics
        cm_data = metrics.get("confusion_matrix", None)
        labels = metrics.get("labels", [])

        if cm_data is None:
            # Try to create from per-label data
            per_label = metrics.get("per_label", [])
            if per_label:
                first = per_label[0]
                labels = [str(p.get("class", i)) for i, p in enumerate(per_label)]
                if "true_positives" in first and "false_positives" in first:
                    cm = np.array([[per_label[0].get("true_positives", 0), per_label[0].get("false_positives", 0)],
                                   [per_label[0].get("false_negatives", 0), per_label[0].get("true_negatives", 0)]])
                else:
                    return OperatorResult(outputs={"chart": None, "error": "per_label data missing required fields"})
            else:
                return OperatorResult(outputs={"chart": None, "error": "No confusion matrix data available"})
        else:
            cm = np.array(cm_data)

        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(cm, interpolation="nearest", cmap=plt.cm.Blues)
        ax.figure.colorbar(im, ax=ax)
        ax.set_xticks(np.arange(cm.shape[1]))
        ax.set_yticks(np.arange(cm.shape[0]))
        if labels:
            ax.set_xticklabels(labels[:cm.shape[1]], rotation=45)
            ax.set_yticklabels(labels[:cm.shape[0]])
        ax.set_xlabel("Predicted")
        ax.set_ylabel("Actual")
        ax.set_title(title)
        for i in range(cm.shape[0]):
            for j in range(cm.shape[1]):
                ax.text(j, i, str(int(cm[i, j])), ha="center", va="center")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        return OperatorResult(outputs={"chart": base64.b64encode(buf.getvalue()).decode("utf-8")})


@register_operator
class BoxPlot(BaseOperator):
    id = "box_plot"
    name = "Box Plot"
    category = "visualization"
    description = "Generate box plot for numerical columns"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("chart", "Chart", "Box Plot")]
    parameters = [
        ParamSpec("columns", "str", "", "Columns (comma-separated, empty=all numeric)"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        columns_str = params.get("columns", "")
        numeric = df.select_dtypes(include=["number"]).columns.tolist()

        if columns_str:
            cols = [c.strip() for c in columns_str.split(",") if c.strip() in numeric]
        else:
            cols = numeric

        if not cols:
            return OperatorResult(outputs={"chart": None, "error": "No numerical columns"})

        fig, ax = plt.subplots(figsize=(max(6, len(cols) * 1.2), 5))
        ax.boxplot([df[c].dropna().values for c in cols], tick_labels=cols)
        ax.set_title("Box Plot")
        ax.set_ylabel("Value")

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        return OperatorResult(outputs={"chart": base64.b64encode(buf.getvalue()).decode("utf-8")})


@register_operator
class BarChart(BaseOperator):
    id = "bar_chart"
    name = "Bar Chart"
    category = "visualization"
    description = "生成柱状图展示分类数据"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("chart", "Chart", "Bar Chart")]
    parameters = [
        ParamSpec("x_column", "str", "", "X轴列", required=True),
        ParamSpec("y_column", "str", "", "Y轴列", required=True),
        ParamSpec("title", "str", "Bar Chart", "图表标题"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        x_col = params.get("x_column", "")
        y_col = params.get("y_column", "")
        title = params.get("title", "Bar Chart")

        if not x_col or x_col not in df.columns:
            return OperatorResult(outputs={"chart": None, "error": f"X column {x_col} not found"})
        if not y_col or y_col not in df.columns:
            return OperatorResult(outputs={"chart": None, "error": f"Y column {y_col} not found"})

        import numpy as np, io, base64
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 6))
        x_data = df[x_col].astype(str).tolist()
        y_data = pd.to_numeric(df[y_col], errors="coerce").tolist()

        bars = ax.bar(range(len(x_data)), y_data, color="steelblue", edgecolor="navy")
        ax.set_xticks(range(len(x_data)))
        ax.set_xticklabels(x_data, rotation=45, ha="right", fontsize=9)
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        ax.set_title(title)
        ax.grid(axis="y", alpha=0.3)

        if len(x_data) <= 30:
            for bar, val in zip(bars, y_data):
                if val is not None:
                    ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{val:.2f}", ha="center", va="bottom", fontsize=8)

        plt.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        return OperatorResult(outputs={"chart": base64.b64encode(buf.getvalue()).decode("utf-8")})

    def get_preview(self, outputs):
        return outputs
