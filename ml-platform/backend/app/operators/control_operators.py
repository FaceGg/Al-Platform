# -*- coding: utf-8 -*-
from app.engine.operator_contract import OperatorContext, OperatorResult
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import pandas as pd


@register_operator
class ConditionOperator(BaseOperator):
    id = "condition"
    name = "Condition"
    category = "control"
    description = "Conditional branch: route data based on conditions"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [
        PortSpec("true_branch", "DataTable", "True Branch"),
        PortSpec("false_branch", "DataTable", "False Branch"),
    ]
    parameters = [
        ParamSpec("column", "str", "", "Column to Check", required=True),
        ParamSpec("operator", "select", ">", "Operator", options=[">", "<", ">=", "<=", "==", "!=", "contains"]),
        ParamSpec("value", "str", "", "Compare Value", required=True),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        df = pd.DataFrame(data)
        column = params.get("column", "")
        op = params.get("operator", ">")
        value = params.get("value", "")

        if not column or column not in df.columns:
            return OperatorResult(outputs={"true_branch": [], "false_branch": data})

        col_data = df[column]

        if op == ">":
            mask = pd.to_numeric(col_data, errors="coerce") > float(value)
        elif op == "<":
            mask = pd.to_numeric(col_data, errors="coerce") < float(value)
        elif op == ">=":
            mask = pd.to_numeric(col_data, errors="coerce") >= float(value)
        elif op == "<=":
            mask = pd.to_numeric(col_data, errors="coerce") <= float(value)
        elif op == "==":
            mask = col_data.astype(str) == str(value)
        elif op == "!=":
            mask = col_data.astype(str) != str(value)
        elif op == "contains":
            mask = col_data.astype(str).str.contains(str(value), na=False)
        else:
            mask = pd.Series(True, index=df.index)

        return OperatorResult(outputs={
            "true_branch": df[mask].to_dict(orient="records"),
            "false_branch": df[~mask].to_dict(orient="records"),
        })


@register_operator
class MergeOperator(BaseOperator):
    id = "merge"
    name = "Merge"
    category = "control"
    description = "Merge multiple data streams into one"
    inputs = [
        PortSpec("data_a", "DataTable", "Data Stream A"),
        PortSpec("data_b", "DataTable", "Data Stream B"),
    ]
    outputs = [PortSpec("merged", "DataTable", "Merged Data")]
    parameters = [
        ParamSpec("merge_type", "select", "concat_rows", "Merge Type",
                  options=["concat_rows", "concat_columns", "inner_join", "outer_join"]),
        ParamSpec(
            "key_column", "str", "", "Join Key Column (for join types)", required=True,
            required_when={"merge_type": ["inner_join", "outer_join"]},
        ),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data_a = inputs.get("data_a", [])
        data_b = inputs.get("data_b", [])
        merge_type = params.get("merge_type", "concat_rows")
        key_col = params.get("key_column", "")

        df_a = pd.DataFrame(data_a) if len(data_a) > 0 else pd.DataFrame()
        df_b = pd.DataFrame(data_b) if len(data_b) > 0 else pd.DataFrame()

        if df_a.empty and df_b.empty:
            return OperatorResult(outputs={"merged": []})
        if df_a.empty:
            return OperatorResult(outputs={"merged": df_b.to_dict(orient="records")})
        if df_b.empty:
            return OperatorResult(outputs={"merged": df_a.to_dict(orient="records")})

        if merge_type == "concat_rows":
            result = pd.concat([df_a, df_b], ignore_index=True)
        elif merge_type == "concat_columns":
            result = pd.concat([df_a.reset_index(drop=True), df_b.reset_index(drop=True)], axis=1)
        elif merge_type in ("inner_join", "outer_join"):
            how = "inner" if merge_type == "inner_join" else "outer"
            if key_col and key_col in df_a.columns and key_col in df_b.columns:
                result = pd.merge(df_a, df_b, on=key_col, how=how)
            else:
                # Fallback to concat
                result = pd.concat([df_a, df_b], ignore_index=True)
        else:
            result = pd.concat([df_a, df_b], ignore_index=True)

        return OperatorResult(outputs={"merged": result.to_dict(orient="records")})


@register_operator
class LoopOperator(BaseOperator):
    id = "loop"
    name = "Loop"
    category = "control"
    description = "Loop execution: iterate over data with configurable iterations"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [
        PortSpec("result", "Params", "Loop Results"),
        PortSpec("continue", "boolean", "Continue Flag"),
    ]
    parameters = [
        ParamSpec("max_iterations", "int", 10, "Max Iterations"),
        ParamSpec("condition", "select", "count", "Loop Condition",
                  options=["count", "while_true"]),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        max_iter = int(params.get("max_iterations", 10))
        iteration = int(inputs.get("iteration", 0))

        should_continue = iteration < max_iter
        result = {
            "iteration": iteration,
            "max_iterations": max_iter,
            "data_count": len(data) if isinstance(data, list) else 1,
        }

        return OperatorResult(outputs={"result": result, "continue": should_continue})
