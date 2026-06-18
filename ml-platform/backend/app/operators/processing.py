from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import pandas as pd
import numpy as np


@register_operator
class MissingValueHandler(BaseOperator):
    id = "missing_value_handler"
    name = "Missing Value Handler"
    category = "processing"
    description = "Handle missing values in dataset"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Cleaned Data")]
    parameters = [
        ParamSpec("strategy", "select", "drop", "Strategy", options=["drop", "mean", "median", "most_frequent", "constant"]),
        ParamSpec("fill_value", "str", "", "Fill Value"),
        ParamSpec("columns", "str", "", "Columns (comma-separated)"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        strategy = params.get("strategy", "drop")
        fill_value = params.get("fill_value", "")
        columns_str = params.get("columns", "")
        columns = [c.strip() for c in columns_str.split(",") if c.strip()] if columns_str else df.columns.tolist()

        if strategy == "drop":
            df = df.dropna(subset=columns)
        elif strategy == "mean":
            for col in columns:
                if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
                    df[col] = df[col].fillna(df[col].mean())
        elif strategy == "median":
            for col in columns:
                if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
                    df[col] = df[col].fillna(df[col].median())
        elif strategy == "most_frequent":
            for col in columns:
                if col in df.columns:
                    df[col] = df[col].fillna(df[col].mode().iloc[0] if not df[col].mode().empty else "")
        elif strategy == "constant":
            for col in columns:
                if col in df.columns:
                    df[col] = df[col].fillna(fill_value)

        return {"data": df.to_dict(orient="records")}

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}


@register_operator
class LabelEncoderOp(BaseOperator):
    id = "label_encoder"
    name = "Label Encoder"
    category = "processing"
    description = "Encode categorical columns"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Encoded Data")]
    parameters = [
        ParamSpec("columns", "str", "", "Columns to encode (comma-separated)"),
        ParamSpec("encoding_type", "select", "label", "Encoding Type", options=["label", "onehot"]),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        columns_str = params.get("columns", "")
        encoding_type = params.get("encoding_type", "label")
        columns = [c.strip() for c in columns_str.split(",") if c.strip()] if columns_str else df.select_dtypes(include=["object", "category"]).columns.tolist()

        if encoding_type == "label":
            for col in columns:
                if col in df.columns:
                    df[col] = df[col].astype("category").cat.codes
        elif encoding_type == "onehot":
            df = pd.get_dummies(df, columns=columns)

        return {"data": df.to_dict(orient="records")}

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}


@register_operator
class ScalerOp(BaseOperator):
    id = "scaler"
    name = "Scaler"
    category = "processing"
    description = "Scale numerical features"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Scaled Data")]
    parameters = [
        ParamSpec("method", "select", "standard", "Scaling Method", options=["standard", "minmax", "robust"]),
        ParamSpec("columns", "str", "", "Columns to scale (comma-separated)"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        method = params.get("method", "standard")
        columns_str = params.get("columns", "")
        columns = [c.strip() for c in columns_str.split(",") if c.strip()] if columns_str else df.select_dtypes(include=[np.number]).columns.tolist()

        if not columns:
            return {"data": df.to_dict(orient="records")}

        scaler_map = {
            "standard": StandardScaler,
            "minmax": MinMaxScaler,
            "robust": RobustScaler,
        }
        scaler_cls = scaler_map.get(method, StandardScaler)
        scaler = scaler_cls()
        df[columns] = scaler.fit_transform(df[columns])

        return {"data": df.to_dict(orient="records")}

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}


@register_operator
class TrainTestSplit(BaseOperator):
    id = "train_test_split"
    name = "Train/Test Split"
    category = "processing"
    description = "Split data into training and test sets"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [
        PortSpec("train", "DataTable", "Training Data"),
        PortSpec("test", "DataTable", "Test Data"),
    ]
    parameters = [
        ParamSpec("test_size", "float", 0.2, "Test Size"),
        ParamSpec("random_seed", "int", 42, "Random Seed"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        from sklearn.model_selection import train_test_split as tts
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        test_size = float(params.get("test_size", 0.2))
        random_seed = int(params.get("random_seed", 42))
        train, test = tts(df, test_size=test_size, random_state=random_seed)
        return {
            "train": train.to_dict(orient="records"),
            "test": test.to_dict(orient="records"),
        }

    def get_preview(self, outputs):
        train = outputs.get("train", [])
        test = outputs.get("test", [])
        return {"train": train[:10], "test": test[:10], "train_rows": len(train), "test_rows": len(test)}
