GENERICIZATION_BRIDGE_ONLY = True

from app.engine.operator_contract import OperatorContext, OperatorResult
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
from app.services.spot_weld_features import (
    REPORT_TABLE_FIELDS,
    WAVEFORM_FIELDS,
    build_feature_frame,
)
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
        ParamSpec("fill_value", "str", "", "Fill Value", required=True, required_when={"strategy": "constant"}),
        ParamSpec("columns", "str", "", "Columns (comma-separated)"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
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

        return OperatorResult(outputs={"data": df.to_dict(orient="records")})

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

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
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

        return OperatorResult(outputs={"data": df.to_dict(orient="records")})

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
        ParamSpec("target_column", "str", "", "Target column to exclude from scaling"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        method = params.get("method", "standard")
        columns_str = params.get("columns", "")
        columns = [c.strip() for c in columns_str.split(",") if c.strip()] if columns_str else df.select_dtypes(include=[np.number]).columns.tolist()
        target = params.get("target_column", "")
        if target and target in columns:
            columns.remove(target)

        if not columns:
            return OperatorResult(outputs={"data": df.to_dict(orient="records")})

        scaler_map = {
            "standard": StandardScaler,
            "minmax": MinMaxScaler,
            "robust": RobustScaler,
        }
        scaler_cls = scaler_map.get(method, StandardScaler)
        scaler = scaler_cls()
        df[columns] = scaler.fit_transform(df[columns])

        return OperatorResult(outputs={"data": df.to_dict(orient="records")})

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
        ParamSpec("target_column", "str", "", "Target Column", required=True, required_when={"stratify": True}),
        ParamSpec("stratify", "boolean", False, "Stratified Split"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.model_selection import train_test_split as tts
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        test_size = float(params.get("test_size", 0.2))
        random_seed = int(params.get("random_seed", 42))
        target_column = params.get("target_column", "")
        stratify = params.get("stratify", False)
        stratify_values = df[target_column] if stratify and target_column in df.columns else None
        train, test = tts(
            df, test_size=test_size, random_state=random_seed, stratify=stratify_values,
        )
        return OperatorResult(outputs={
            "train": train.to_dict(orient="records"),
            "test": test.to_dict(orient="records"),
        })

    def get_preview(self, outputs):
        train = outputs.get("train", [])
        test = outputs.get("test", [])
        return {"train": train[:10], "test": test[:10], "train_rows": len(train), "test_rows": len(test)}


@register_operator
class SpotWeldFeatureEngineering(BaseOperator):
    id = "spot_weld_feature_engineering"
    name = "Spot Weld Feature Engineering"
    category = "feature_engineering"
    description = "Decode four report waveforms and produce the fixed 73-feature schema"
    inputs = [PortSpec(
        "data", "DataTable", "Report Data",
        required_columns=REPORT_TABLE_FIELDS + WAVEFORM_FIELDS,
    )]
    outputs = [
        PortSpec("features", "DataTable", "73 Feature Data"),
        PortSpec("schema", "JSON", "Feature Schema"),
        PortSpec("statistics", "JSON", "Feature Statistics"),
    ]
    parameters = [
        ParamSpec(
            "exclude_columns", "str", "", "Columns to exclude from output",
        ),
        ParamSpec(
            "label_column", "str", "Fault", "Label column",
        ),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        frame = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
        exclude_columns = {
            column.strip()
            for column in str(params.get("exclude_columns") or "").split(",")
            if column.strip()
        }
        required_source_columns = set(REPORT_TABLE_FIELDS + WAVEFORM_FIELDS)
        forbidden = sorted(exclude_columns & required_source_columns)
        if forbidden:
            raise ValueError(
                "Cannot exclude required source column(s): "
                + ", ".join(forbidden)
            )
        features, schema, statistics = build_feature_frame(frame)
        enriched = features.copy()
        requested_label = str(params.get("label_column") or "Fault").strip() or "Fault"
        label_lookup = {str(column).casefold(): str(column) for column in frame.columns}
        actual_label = label_lookup.get(requested_label.casefold())
        label_present = actual_label is not None
        if label_present:
            label = frame[actual_label].reset_index(drop=True)
            if len(label) != len(enriched):
                raise ValueError(f"{actual_label} label length must match feature rows")
            enriched[actual_label] = label.to_numpy()
            schema.append(actual_label)
        output_exclusions = exclude_columns - {actual_label} if actual_label else exclude_columns
        enriched = enriched.drop(columns=[column for column in output_exclusions if column in enriched], errors="ignore")
        schema = [column for column in schema if column in enriched.columns]
        statistics.update({
            "label_column": actual_label or requested_label,
            "label_present": label_present,
            "label_dtype": str(frame[actual_label].dtype) if label_present else None,
            "excluded_columns": sorted(output_exclusions),
        })
        return OperatorResult(outputs={
            "features": enriched.to_dict(orient="records"),
            "schema": {
                "columns": schema,
                "label_column": actual_label or requested_label,
                "label_position": "last",
                "label_present": label_present,
                "label_dtype": str(frame[actual_label].dtype) if label_present else None,
                "excluded_columns": sorted(output_exclusions),
            },
            "statistics": statistics,
        })


@register_operator
class TightenFeatureEngineering(BaseOperator):
    id = "tighten_feature_engineering"
    name = "Tighten Feature Engineering"
    category = "feature_engineering"
    description = (
        "Derive tightening quality features: torque deviation, tolerance band "
        "position, limit margins and dual-axis torque difference"
    )
    inputs = [PortSpec("data", "DataTable", "Tighten Record Data")]
    outputs = [
        PortSpec("features", "DataTable", "Data With Derived Features"),
        PortSpec("schema", "JSON", "Feature Schema"),
        PortSpec("statistics", "JSON", "Feature Statistics"),
    ]
    parameters = [
        ParamSpec("torque_column", "str", "ACTUAL_TORQUE", "Actual torque column"),
        ParamSpec("target_torque_column", "str", "TARGET_TORQUE", "Target torque column"),
        ParamSpec("upper_limit_column", "str", "UPPER_LIMIT", "Upper limit column"),
        ParamSpec("lower_limit_column", "str", "LOWER_LIMIT", "Lower limit column"),
        ParamSpec(
            "torque_two_column", "str", "ACTUAL_TORQUE_TWO",
            "Second axis torque column (empty to skip)",
        ),
        ParamSpec("output_prefix", "str", "TIGHTEN_", "Derived feature name prefix"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        df = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
        if df.empty:
            raise ValueError("Tighten feature engineering requires non-empty input data")

        lookup = {str(column).casefold(): str(column) for column in df.columns}

        def resolve_column(name) -> str | None:
            key = str(name or "").strip()
            return lookup.get(key.casefold()) if key else None

        torque_col = resolve_column(params.get("torque_column") or "ACTUAL_TORQUE")
        target_col = resolve_column(params.get("target_torque_column") or "TARGET_TORQUE")
        if torque_col is None or target_col is None:
            raise ValueError(
                "Tighten feature engineering requires both actual torque column "
                f"({params.get('torque_column') or 'ACTUAL_TORQUE'}) and target "
                f"torque column ({params.get('target_torque_column') or 'TARGET_TORQUE'})"
            )
        upper_col = resolve_column(params.get("upper_limit_column") or "UPPER_LIMIT")
        lower_col = resolve_column(params.get("lower_limit_column") or "LOWER_LIMIT")
        torque_two_col = resolve_column(params.get("torque_two_column") or "ACTUAL_TORQUE_TWO")
        prefix = str(params.get("output_prefix") or "").strip() or "TIGHTEN_"

        torque = pd.to_numeric(df[torque_col], errors="coerce")
        target = pd.to_numeric(df[target_col], errors="coerce")
        features = df.copy()
        schema: list[str] = []
        statistics: dict = {"rows": int(len(df))}
        skipped: dict[str, str] = {}

        deviation_name = f"{prefix}TORQUE_DEVIATION"
        features[deviation_name] = torque - target
        schema.append(deviation_name)

        if upper_col is not None and lower_col is not None:
            upper = pd.to_numeric(df[upper_col], errors="coerce")
            lower = pd.to_numeric(df[lower_col], errors="coerce")
            band = upper - lower
            ratio_name = f"{prefix}DEVIATION_RATIO"
            features[ratio_name] = (torque - target) / band.replace(0, np.nan)
            upper_margin_name = f"{prefix}UPPER_MARGIN"
            lower_margin_name = f"{prefix}LOWER_MARGIN"
            features[upper_margin_name] = upper - torque
            features[lower_margin_name] = torque - lower
            schema.extend([ratio_name, upper_margin_name, lower_margin_name])
            statistics["band_width_zero_rows"] = int((band == 0).sum())
        else:
            skipped["band_features"] = "UPPER_LIMIT / LOWER_LIMIT column missing"

        if torque_two_col is not None:
            torque_two = pd.to_numeric(df[torque_two_col], errors="coerce")
            if torque_two.notna().any():
                diff_name = f"{prefix}DUAL_AXIS_DIFF"
                features[diff_name] = torque - torque_two
                schema.append(diff_name)
            else:
                skipped["dual_axis_diff"] = f"Column {torque_two_col} has no numeric values"
        else:
            skipped["dual_axis_diff"] = "Second axis torque column not configured"

        for name in schema:
            statistics[f"{name}_non_null"] = int(features[name].notna().sum())
        statistics["derived_features"] = schema
        statistics["skipped"] = skipped

        return OperatorResult(outputs={
            "features": features.to_dict(orient="records"),
            "schema": {"derived_columns": schema, "output_prefix": prefix},
            "statistics": statistics,
        })

    def get_preview(self, outputs):
        features = outputs.get("features", [])
        return {"features": features[:10], "total_rows": len(features)}



# ============================================================
# Control Flow Operators
# ============================================================

@register_operator
class AutoFeatureEngineering(BaseOperator):
    id = "auto_feature_engineering"
    name = "Auto Feature Engineering"
    category = "processing"
    description = "Automatically generate and select features: interaction terms, polynomial features, feature selection"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [
        PortSpec("data", "DataTable", "Engineered Data"),
        PortSpec("feature_report", "JSON", "Feature Report"),
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

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
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

        return OperatorResult(outputs={"data": df.to_dict(orient="records"), "feature_report": report})

    def get_preview(self, outputs):
        return {"feature_report": outputs.get("feature_report", {}), "data_shape": f"{len(outputs.get('data', []))} rows"}


# === Auto-generated Processing operators ===

@register_operator
class NormalizeOp(BaseOperator):
    id = "normalize"; name = "Normalize"; category = "processing"
    description = "Normalize / standardize numeric columns"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Normalized Data")]
    parameters = [
        ParamSpec("method", "select", "zscore", "Method", options=["zscore", "minmax", "robust"]),
        ParamSpec("columns", "str", "", "Columns (comma-separated, empty=all numeric)"),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.preprocessing import StandardScaler, MinMaxScaler, RobustScaler
        data = inputs.get("data", []); df = pd.DataFrame(data)
        method = params.get("method", "zscore")
        col_str = params.get("columns", "")
        if col_str: columns = [c.strip() for c in col_str.split(",") if c.strip() in df.columns]
        else: columns = df.select_dtypes(include=[np.number]).columns.tolist()
        scaler_map = {"zscore": StandardScaler, "minmax": MinMaxScaler, "robust": RobustScaler}
        scaler = scaler_map.get(method, StandardScaler)()
        if columns: df[columns] = scaler.fit_transform(df[columns])
        return OperatorResult(outputs={"data": df.to_dict(orient="records")})

@register_operator
class DiscretizeOp(BaseOperator):
    id = "discretize"; name = "Discretize"; category = "processing"
    description = "Discretize continuous values into bins"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Discretized Data")]
    parameters = [
        ParamSpec("columns", "str", "", "Columns (comma-separated)"),
        ParamSpec("bins", "int", 5, "Number of Bins"),
        ParamSpec("method", "select", "equal_width", "Method", options=["equal_width", "equal_frequency"]),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", []); df = pd.DataFrame(data)
        col_str = params.get("columns", ""); bins = int(params.get("bins", 5))
        if col_str: columns = [c.strip() for c in col_str.split(",") if c.strip() in df.columns]
        else: columns = df.select_dtypes(include=[np.number]).columns.tolist()
        for col in columns:
            if params.get("method") == "equal_frequency":
                df[col + "_bin"] = pd.qcut(df[col], q=bins, duplicates="drop", labels=False)
            else: df[col + "_bin"] = pd.cut(df[col], bins=bins, labels=False)
        return OperatorResult(outputs={"data": df.to_dict(orient="records")})

@register_operator
class OutlierDetector(BaseOperator):
    id = "detect_outliers"; name = "Detect Outliers"; category = "processing"
    description = "Detect outliers in numeric data"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Data with outlier flags")]
    parameters = [
        ParamSpec("method", "select", "isolation_forest", "Method", options=["isolation_forest", "iqr", "zscore"]),
        ParamSpec("contamination", "float", 0.1, "Expected outlier ratio"),
        ParamSpec("exclude_columns", "str", "", "Columns excluded from detection"),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.ensemble import IsolationForest
        data = inputs.get("data", []); df = pd.DataFrame(data)
        excluded = {
            column.strip() for column in params.get("exclude_columns", "").split(",")
            if column.strip()
        }
        num_cols = [
            column for column in df.select_dtypes(include=[np.number]).columns
            if column not in excluded
        ]
        if not num_cols:
            raise ValueError("No numeric columns available for outlier detection")
        method = params.get("method", "isolation_forest")
        contamination = float(params.get("contamination", 0.1))
        if method == "isolation_forest":
            clf = IsolationForest(contamination=contamination, random_state=42)
            df["outlier"] = clf.fit_predict(df[num_cols])
            df["outlier"] = (df["outlier"] == -1)
        elif method == "zscore":
            z = np.abs((df[num_cols] - df[num_cols].mean()) / df[num_cols].std())
            df["outlier"] = (z > 3).any(axis=1)
        else:
            Q1 = df[num_cols].quantile(0.25); Q3 = df[num_cols].quantile(0.75); IQR = Q3 - Q1
            df["outlier"] = ((df[num_cols] < (Q1 - 1.5*IQR)) | (df[num_cols] > (Q3 + 1.5*IQR))).any(axis=1)
        return OperatorResult(outputs={"data": df.to_dict(orient="records")})

@register_operator
class SelectAttributes(BaseOperator):
    id = "select_attributes"; name = "Select Attributes"; category = "processing"
    description = "Select / filter columns from dataset"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Filtered Data")]
    parameters = [
        ParamSpec("columns", "str", "", "Columns to keep (comma-separated)"),
        ParamSpec("invert", "boolean", False, "Invert selection"),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", []); df = pd.DataFrame(data)
        col_str = params.get("columns", ""); invert = params.get("invert", False)
        if col_str:
            requested = [c.strip() for c in str(col_str).split(",") if c.strip()]
            missing = [column for column in requested if column not in df.columns]
            if missing:
                raise ValueError(f"SelectAttributes: unknown columns: {', '.join(missing)}")
            cols = requested
            if invert: cols = [c for c in df.columns if c not in cols]
            df = df[cols]
        return OperatorResult(outputs={"data": df.to_dict(orient="records")})

@register_operator
class SetRoleOp(BaseOperator):
    id = "set_role"; name = "Set Role"; category = "processing"
    description = "Set the role of a column (label, id, weight, etc.)"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Data with role metadata")]
    parameters = [
        ParamSpec("column", "str", "", "Target Column", required=True),
        ParamSpec("role", "select", "label", "Role", options=["label", "id", "weight", "feature", "ignore"]),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        return OperatorResult(outputs={"data": data})

@register_operator
class FilterExamples(BaseOperator):
    id = "filter_examples"; name = "Filter Examples"; category = "processing"
    description = "Filter rows by expression"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Filtered Data")]
    parameters = [ParamSpec("expression", "str", "", "Filter expression (e.g., column > 0)", required=True)]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", []); df = pd.DataFrame(data)
        expr = params.get("expression", "")
        if expr:
            try: df = df.query(expr)
            except: pass
        return OperatorResult(outputs={"data": df.to_dict(orient="records")})

@register_operator
class SampleOp(BaseOperator):
    id = "sample"; name = "Sample"; category = "processing"
    description = "Random sample of data"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Sampled Data")]
    parameters = [
        ParamSpec("sample_size", "int", 100, "Sample Size"),
        ParamSpec("with_replacement", "boolean", False, "With Replacement"),
        ParamSpec("random_seed", "int", 42, "Random Seed"),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", []); df = pd.DataFrame(data)
        n = min(int(params.get("sample_size", 100)), len(df))
        replace = params.get("with_replacement", False)
        seed = int(params.get("random_seed", 42))
        df = df.sample(n=n, replace=replace, random_state=seed)
        return OperatorResult(outputs={"data": df.to_dict(orient="records")})

@register_operator
class ImputeMissingAdvanced(BaseOperator):
    id = "impute_missing_advanced"; name = "Impute Missing (Advanced)"; category = "processing"
    description = "Advanced missing value imputation"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Imputed Data")]
    parameters = [
        ParamSpec("strategy", "select", "mean", "Strategy", options=["mean", "median", "most_frequent", "constant"]),
        ParamSpec("fill_value", "str", "0", "Fill value (constant strategy)"),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from sklearn.impute import SimpleImputer
        data = inputs.get("data", []); df = pd.DataFrame(data)
        strategy = params.get("strategy", "mean")
        fill_val = params.get("fill_value", "0")
        num_cols = df.select_dtypes(include=[np.number]).columns
        if strategy == "constant":
            try: fv = float(fill_val)
            except: fv = fill_val
            imp = SimpleImputer(strategy=strategy, fill_value=fv)
        else: imp = SimpleImputer(strategy=strategy)
        if len(num_cols) > 0: df[num_cols] = imp.fit_transform(df[num_cols])
        return OperatorResult(outputs={"data": df.to_dict(orient="records")})


def build_fixed_feature_frame(frame: pd.DataFrame):
    """Generic entry for the fixed report feature schema (bridge helper).

    Platform services that need the frozen report→feature decoding call this
    wrapper instead of reaching into the legacy feature module themselves.
    """
    features, schema, statistics = build_feature_frame(frame)
    return features, schema, statistics
