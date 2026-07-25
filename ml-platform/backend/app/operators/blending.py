# -*- coding: utf-8 -*-
from app.engine.operator_contract import OperatorContext, OperatorResult
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import pandas as pd
import numpy as np


@register_operator
class JoinOp(BaseOperator):
    id = "join"
    name = "Join"
    category = "blending"
    description = "Join two datasets on key columns"
    inputs = [
        PortSpec("left", "DataTable", "Left Dataset"),
        PortSpec("right", "DataTable", "Right Dataset"),
    ]
    outputs = [PortSpec("data", "DataTable", "Joined Data")]
    parameters = [
        ParamSpec("join_type", "select", "inner", "Join Type", options=["inner", "left", "right", "outer"]),
        ParamSpec("left_keys", "str", "", "Left Key Columns", required=True),
        ParamSpec("right_keys", "str", "", "Right Key Columns", required=True),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data_left = inputs.get("left", [])
        data_right = inputs.get("right", [])
        join_type = params.get("join_type", "inner")
        left_keys_str = params.get("left_keys", "")
        right_keys_str = params.get("right_keys", "")
        left_keys = left_keys_str.split(",") if isinstance(left_keys_str, str) else []
        right_keys = right_keys_str.split(",") if isinstance(right_keys_str, str) else []
        left_keys = [key.strip() for key in left_keys]
        right_keys = [key.strip() for key in right_keys]

        if not left_keys or not right_keys or any(not key for key in left_keys + right_keys):
            raise ValueError("Join key pairs are required")

        if len(left_keys) != len(right_keys):
            raise ValueError(f"left_keys ({len(left_keys)}) and right_keys ({len(right_keys)}) count mismatch")

        left_empty = data_left.empty if isinstance(data_left, pd.DataFrame) else not data_left
        right_empty = data_right.empty if isinstance(data_right, pd.DataFrame) else not data_right
        if left_empty or right_empty:
            remaining = data_right if left_empty else data_left
            if isinstance(remaining, pd.DataFrame):
                remaining = remaining.to_dict(orient="records")
            return OperatorResult(outputs={"data": remaining if remaining else []})

        df_left = pd.DataFrame(data_left)
        df_right = pd.DataFrame(data_right)

        for lk in left_keys:
            if lk not in df_left.columns:
                raise ValueError(f"左侧中找不到 '{lk}'列: " + ", ".join(list(df_left.columns)))
        for rk in right_keys:
            if rk not in df_right.columns:
                raise ValueError(f"右侧中找不到 '{rk}'列: " + ", ".join(list(df_right.columns)))

        result = pd.merge(
            df_left,
            df_right,
            left_on=left_keys,
            right_on=right_keys,
            how=join_type,
            suffixes=("", "_y"),
        )
        dupes = [c for c in result.columns if c.endswith("_y")]
        result = result.drop(columns=dupes)

        return OperatorResult(outputs={"data": result.to_dict(orient="records")})

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}


@register_operator
class UnionOp(BaseOperator):
    id = "union"
    name = "Union"
    category = "blending"
    description = "Union datasets vertically, auto-matching columns"
    inputs = [
        PortSpec("data1", "DataTable", "First Dataset"),
        PortSpec("data2", "DataTable", "Second Dataset"),
    ]
    outputs = [PortSpec("data", "DataTable", "Unioned Data")]
    parameters = []

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data1 = inputs.get("data1", [])
        data2 = inputs.get("data2", [])

        if ((isinstance(data1, pd.DataFrame) and data1.empty) or (not isinstance(data1, pd.DataFrame) and not data1)) and ((isinstance(data2, pd.DataFrame) and data2.empty) or (not isinstance(data2, pd.DataFrame) and not data2)):
            return OperatorResult(outputs={"data": []})
        if (isinstance(data1, pd.DataFrame) and data1.empty) or (not isinstance(data1, pd.DataFrame) and not data1):
            return OperatorResult(outputs={"data": data2})
        if (isinstance(data2, pd.DataFrame) and data2.empty) or (not isinstance(data2, pd.DataFrame) and not data2):
            return OperatorResult(outputs={"data": data1})

        df1 = pd.DataFrame(data1)
        df2 = pd.DataFrame(data2)

        result = pd.concat([df1, df2], ignore_index=True)
        return OperatorResult(outputs={"data": result.to_dict(orient="records")})

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}


@register_operator
class AggregateOp(BaseOperator):
    id = "aggregate"
    name = "Aggregate"
    category = "blending"
    description = "Group by columns and compute aggregations"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Aggregated Data")]
    parameters = [
        ParamSpec("group_by", "str", "", "Group-by Columns (comma-separated)", required=True),
        ParamSpec("aggregations", "str", "", "Aggregations, e.g. col1:mean,col2:sum", required=True),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        if (isinstance(data, pd.DataFrame) and data.empty) or (not isinstance(data, pd.DataFrame) and not data):
            return OperatorResult(outputs={"data": []})

        df = pd.DataFrame(data)
        group_by_str = params.get("group_by", "")
        agg_str = params.get("aggregations", "")

        if (isinstance(group_by_str, pd.DataFrame) and group_by_str.empty) or (not isinstance(group_by_str, pd.DataFrame) and not group_by_str):
            raise ValueError("group_by is required for AggregateOp")
        if (isinstance(agg_str, pd.DataFrame) and agg_str.empty) or (not isinstance(agg_str, pd.DataFrame) and not agg_str):
            raise ValueError("aggregations is required for AggregateOp")

        group_cols = [c.strip() for c in group_by_str.split(",") if c.strip()]
        missing = [c for c in group_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Group-by columns not found: {missing}")

        agg_pairs = []
        for part in agg_str.split(","):
            part = part.strip()
            if (isinstance(part, pd.DataFrame) and part.empty) or (not isinstance(part, pd.DataFrame) and not part):
                continue
            if ":" not in part:
                raise ValueError(f"Invalid aggregation format '{part}', expected col:func")
            col, func = part.rsplit(":", 1)
            col = col.strip()
            func = func.strip()
            if col not in df.columns:
                raise ValueError(f"Aggregation column '{col}' not found in dataset")
            if func not in ("mean", "sum", "count", "min", "max", "std", "var", "nunique", "first", "last"):
                raise ValueError(f"Unsupported aggregation function '{func}'")
            agg_pairs.append((col, func))

        if (isinstance(agg_pairs, pd.DataFrame) and agg_pairs.empty) or (not isinstance(agg_pairs, pd.DataFrame) and not agg_pairs):
            raise ValueError("No valid aggregations specified")

        agg_map = {}
        for col, func in agg_pairs:
            agg_map[col] = func

        result = df.groupby(group_cols).agg(agg_map).reset_index()
        result.columns = [col[0] if isinstance(col, tuple) else col for col in result.columns]
        return OperatorResult(outputs={"data": result.to_dict(orient="records")})

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}


@register_operator
class PivotOp(BaseOperator):
    id = "pivot"
    name = "Pivot"
    category = "blending"
    description = "Pivot rows to columns. Outputs pivot table + preprocessing model for inverse transform."
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [
        PortSpec("data", "DataTable", "Pivoted Data"),
        PortSpec("preprocessing_model", "Model", "Pivot Metadata (for inverse)"),
    ]
    parameters = [
        ParamSpec("index", "str", "", "Index Column (row dimension)", required=True),
        ParamSpec("columns", "str", "", "Columns Column (pivoted to headers)", required=True),
        ParamSpec("values", "str", "", "Values Column", required=True),
        ParamSpec("agg_function", "select", "mean", "Aggregation Function", options=["mean", "sum", "count", "min", "max"]),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        import io, joblib
        data = inputs.get("data", [])
        if (isinstance(data, pd.DataFrame) and data.empty) or (not isinstance(data, pd.DataFrame) and not data):
            return OperatorResult(outputs={"data": []})

        df = pd.DataFrame(data)
        index_col = params.get("index", "")
        columns_col = params.get("columns", "")
        values_col = params.get("values", "")
        agg_func = params.get("agg_function", "mean")

        if not index_col or not columns_col or not values_col:
            raise ValueError("index, columns, and values are all required for PivotOp")

        for col in [index_col, columns_col, values_col]:
            if col not in df.columns:
                raise ValueError(f"Column '{col}' not found in dataset")

        result = df.pivot_table(index=index_col, columns=columns_col, values=values_col, aggfunc=agg_func)
        result = result.reset_index()
        result.columns = [str(c) for c in result.columns]

        pivot_model = {"type": "pivot", "index": index_col, "columns": columns_col, "values": values_col, "agg_func": agg_func}
        buf = io.BytesIO()
        joblib.dump(pivot_model, buf)
        return OperatorResult(outputs={"data": result.to_dict(orient="records"), "preprocessing_model": buf.getvalue()})

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}


@register_operator
class TransposeOp(BaseOperator):
    id = "transpose"
    name = "Transpose"
    category = "blending"
    description = "Transpose rows and columns"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Transposed Data")]
    parameters = []

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        if (isinstance(data, pd.DataFrame) and data.empty) or (not isinstance(data, pd.DataFrame) and not data):
            return OperatorResult(outputs={"data": []})

        df = pd.DataFrame(data)
        result = df.T.reset_index()
        result.columns = [str(c) for c in result.columns]
        return OperatorResult(outputs={"data": result.to_dict(orient="records")})

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}


@register_operator
class GenerateAttributesOp(BaseOperator):
    id = "generate_attributes"
    name = "Generate Attributes"
    category = "blending"
    description = "Create a new column via a Python expression"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Data with New Column")]
    parameters = [
        ParamSpec("new_column_name", "str", "", "New Column Name", required=True),
        ParamSpec("expression", "str", "", "Python Expression (use 'row' dict)", required=True),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        if (isinstance(data, pd.DataFrame) and data.empty) or (not isinstance(data, pd.DataFrame) and not data):
            return OperatorResult(outputs={"data": []})

        new_col = params.get("new_column_name", "")
        expression = params.get("expression", "")

        if (isinstance(new_col, pd.DataFrame) and new_col.empty) or (not isinstance(new_col, pd.DataFrame) and not new_col):
            raise ValueError("new_column_name is required for GenerateAttributesOp")
        if (isinstance(expression, pd.DataFrame) and expression.empty) or (not isinstance(expression, pd.DataFrame) and not expression):
            raise ValueError("expression is required for GenerateAttributesOp")

        df = pd.DataFrame(data)
        results = []
        for _, row in df.iterrows():
            row_dict = row.to_dict()
            try:
                row_dict[new_col] = eval(expression, {"__builtins__": {}}, {"row": row_dict})
            except Exception as e:
                raise ValueError(f"Expression evaluation failed at row with expression '{expression}': {e}")
            results.append(row_dict)

        return OperatorResult(outputs={"data": results})

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}


@register_operator
class SortOp(BaseOperator):
    id = "sort"
    name = "Sort"
    category = "blending"
    description = "Sort data by a column"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Sorted Data")]
    parameters = [
        ParamSpec("sort_column", "str", "", "Sort Column", required=True),
        ParamSpec("ascending", "boolean", True, "Ascending Order"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        if (isinstance(data, pd.DataFrame) and data.empty) or (not isinstance(data, pd.DataFrame) and not data):
            return OperatorResult(outputs={"data": []})

        df = pd.DataFrame(data)
        sort_col = params.get("sort_column", "")
        ascending = params.get("ascending", True)

        if (isinstance(sort_col, pd.DataFrame) and sort_col.empty) or (not isinstance(sort_col, pd.DataFrame) and not sort_col):
            raise ValueError("sort_column is required for SortOp")
        if sort_col not in df.columns:
            raise ValueError(f"Sort column '{sort_col}' not found in dataset")

        result = df.sort_values(by=sort_col, ascending=ascending)
        return OperatorResult(outputs={"data": result.to_dict(orient="records")})

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}
