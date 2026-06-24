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



# ============================================================
# Control Flow Operators
# ============================================================

@register_operator
class ConditionOperator(BaseOperator):
    id = "condition"
    name = "Condition / Branch"
    category = "control"
    description = "Evaluate a Python expression and route data to true/false branch"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [
        PortSpec("true", "DataTable", "True Branch"),
        PortSpec("false", "DataTable", "False Branch"),
        PortSpec("condition_result", "Params", "Condition Result"),
    ]
    parameters = [
        ParamSpec("expression", "str", "True", "Python Expression to evaluate"),
    ]

    def validate(self, inputs):
        return "data" in inputs

    def execute(self, inputs, params):
        data = inputs.get("data", [])
        expr = params.get("expression", "True")
        try:
            # Evaluate condition in a safe context
            safe_globals = {"__builtins__": {"len": len, "sum": sum, "min": min, "max": max, "any": any, "all": all, "isinstance": isinstance, "str": str, "int": int, "float": float, "bool": bool, "list": list, "dict": dict, "True": True, "False": False, "None": None}, "data": data}
            result = eval(expr, safe_globals, {})
            condition_met = bool(result)
        except Exception as e:
            condition_met = False
        return {
            "true": data if condition_met else [],
            "false": data if not condition_met else [],
            "condition_result": {"expression": expr, "result": condition_met},
        }

    def get_preview(self, outputs):
        return outputs


@register_operator
class LoopOperator(BaseOperator):
    id = "loop"
    name = "Loop / Iterator"
    category = "control"
    description = "Iterate over data N times, useful for repeated processing"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [
        PortSpec("iteration", "DataTable", "Iteration Output"),
        PortSpec("final", "DataTable", "Final Output"),
    ]
    parameters = [
        ParamSpec("max_iterations", "int", 5, "Max Iterations"),
        ParamSpec("stop_condition", "str", "False", "Stop Condition Expression"),
    ]

    def validate(self, inputs):
        return "data" in inputs

    def execute(self, inputs, params):
        data = inputs.get("data", [])
        max_iter = params.get("max_iterations", 5)
        stop_expr = params.get("stop_condition", "False")
        iteration_results = []
        current_data = data
        for i in range(max_iter):
            try:
                safe_globals = {"__builtins__": {"len": len, "sum": sum, "any": any, "all": all, "True": True, "False": False}, "data": current_data, "iteration": i}
                should_stop = eval(stop_expr, safe_globals, {})
                if bool(should_stop):
                    break
            except:
                pass
            iteration_results.append({"iteration": i, "data_count": len(current_data) if isinstance(current_data, (list, dict)) else 1})
        return {
            "iteration": iteration_results,
            "final": current_data,
        }

    def get_preview(self, outputs):
        return outputs


@register_operator
class MergeOperator(BaseOperator):
    id = "merge"
    name = "Merge / Concatenate"
    category = "control"
    description = "Merge multiple data streams into one"
    inputs = [
        PortSpec("data_a", "DataTable", "Data Stream A"),
        PortSpec("data_b", "DataTable", "Data Stream B"),
    ]
    outputs = [PortSpec("merged", "DataTable", "Merged Data")]
    parameters = [
        ParamSpec("merge_type", "select", "concat", "Merge Type",
                  options=["concat", "union", "intersection"]),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        a = inputs.get("data_a", [])
        b = inputs.get("data_b", [])
        merge_type = params.get("merge_type", "concat")
        if merge_type == "concat":
            result = a + b if isinstance(a, list) and isinstance(b, list) else [a, b]
        elif merge_type == "union":
            if isinstance(a, list) and isinstance(b, list):
                result = list({str(x): x for x in a + b}.values())
            else:
                result = [a, b]
        else:
            result = a if isinstance(a, list) else [a]
        return {"merged": result}

    def get_preview(self, outputs):
        return outputs



@register_operator
class AutoFeatureEngineering(BaseOperator):
    id = "auto_feature_engineering"
    name = "Auto Feature Engineering"
    category = "processing"
    description = "Automatically generate and select features: interaction terms, polynomial features, feature selection"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [
        PortSpec("data", "DataTable", "Engineered Data"),
        PortSpec("feature_report", "Params", "Feature Report"),
    ]
    parameters = [
        ParamSpec("target_column", "str", "", "Target Column"),
        ParamSpec("interactions", "boolean", True, "Generate Interaction Terms"),
        ParamSpec("polynomial_degree", "int", 2, "Polynomial Degree"),
        ParamSpec("feature_selection", "select", "mutual_info", "Selection Method",
                  options=["mutual_info", "f_classif", "variance_threshold", "none"]),
        ParamSpec("max_features", "int", 50, "Max Features to Keep"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        import pandas as pd
        import numpy as np
        from sklearn.preprocessing import PolynomialFeatures
        from sklearn.feature_selection import mutual_info_classif, f_classif, VarianceThreshold

        data = inputs.get("data", [])
        df = pd.DataFrame(data) if not isinstance(data, pd.DataFrame) else data
        target_col = params.get("target_column", "")
        interactions = params.get("interactions", True)
        poly_degree = params.get("polynomial_degree", 2)
        sel_method = params.get("feature_selection", "mutual_info")
        max_features = params.get("max_features", 50)

        original_cols = list(df.columns)
        num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        if target_col and target_col in num_cols:
            num_cols = [c for c in num_cols if c != target_col]

        report = {"original_features": len(num_cols), "steps": []}

        # Step 1: Polynomial features
        if interactions and len(num_cols) >= 2:
            try:
                poly = PolynomialFeatures(degree=min(poly_degree, 3), include_bias=False, interaction_only=True)
                X_num = df[num_cols].fillna(0).values
                poly_features = poly.fit_transform(X_num)
                poly_names = [f"poly_{i}" for i in range(poly_features.shape[1] - len(num_cols))]
                poly_df = pd.DataFrame(poly_features[:, len(num_cols):], columns=poly_names, index=df.index)
                df = pd.concat([df, poly_df], axis=1)
                report["steps"].append({"step": "polynomial_interactions", "features_added": len(poly_names)})
            except Exception as e:
                report["steps"].append({"step": "polynomial_interactions", "error": str(e)})

        # Step 2: Feature selection
        new_num_cols = [c for c in df.columns if c not in original_cols and df[c].dtype in [np.float64, np.float32, np.int64, np.int32]]
        all_num = num_cols + new_num_cols
        if target_col and target_col in df.columns and len(all_num) > max_features:
            try:
                X = df[all_num].fillna(0)
                y = df[target_col].fillna(0)
                if sel_method == "mutual_info":
                    scores = mutual_info_classif(X, y.astype(int) if y.dtype == object else y, random_state=42)
                elif sel_method == "f_classif":
                    scores, _ = f_classif(X, y.astype(int) if y.dtype == object else y)
                elif sel_method == "variance_threshold":
                    sel = VarianceThreshold(threshold=0.01)
                    sel.fit(X)
                    scores = sel.variances_
                else:
                    scores = np.ones(len(all_num))

                score_df = pd.DataFrame({"feature": all_num, "score": scores}).sort_values("score", ascending=False)
                selected = score_df.head(max_features)["feature"].tolist()
                keep_cols = selected + ([target_col] if target_col in df.columns else []) + \
                            [c for c in df.columns if c not in all_num + ([target_col] if target_col else [])]
                df = df[keep_cols]
                report["steps"].append({"step": "feature_selection", "method": sel_method, "selected": len(selected), "dropped": len(all_num) - len(selected)})
                report["top_features"] = [{"feature": r["feature"], "score": round(r["score"], 4)} for _, r in score_df.head(10).iterrows()]
            except Exception as e:
                report["steps"].append({"step": "feature_selection", "error": str(e)})

        report["final_features"] = len([c for c in df.columns if c != target_col])

        return {"data": df.to_dict(orient="records"), "feature_report": report}

    def get_preview(self, outputs):
        return {"feature_report": outputs.get("feature_report", {}), "data_shape": f"{len(outputs.get('data', []))} rows"}
