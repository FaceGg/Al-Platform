# -*- coding: utf-8 -*-
from app.engine.operator_contract import OperatorContext, OperatorResult
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import pandas as pd
import os as os_mod


@register_operator
class ExecutePython(BaseOperator):
    id = "execute_python"
    name = "ExecutePython"
    category = "utility"
    description = "Run custom Python script with input data as DataFrame"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Output Data")]
    parameters = [
        ParamSpec("script", "str", "", "Python Script (multi-line)"),
        ParamSpec("input_var", "str", "data", "Input Variable Name"),
        ParamSpec("output_var", "str", "result", "Output Variable Name"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        script = params.get("script", "")
        input_var = params.get("input_var", "data")
        output_var = params.get("output_var", "result")

        data = inputs.get("data", [])
        df = pd.DataFrame(data)

        local_vars = {input_var: df}
        try:
            exec(script, {"__builtins__": __builtins__}, local_vars)
        except Exception as e:
            raise RuntimeError(f"ExecutePython script error: {e}") from e

        result = local_vars.get(output_var, df)
        if isinstance(result, pd.DataFrame):
            result = result.to_dict(orient="records")
        elif not isinstance(result, list):
            raise TypeError(f"ExecutePython: output_var '{output_var}' must be a DataFrame or list")

        return OperatorResult(outputs={"data": result})


@register_operator
class CollectOp(BaseOperator):
    id = "collect"
    name = "Collect"
    category = "utility"
    description = "Collect and concatenate multiple data inputs into one"
    inputs = [
        PortSpec("data1", "DataTable", "Data Input 1"),
        PortSpec("data2", "DataTable", "Data Input 2"),
        PortSpec("data3", "DataTable", "Data Input 3"),
        PortSpec("data4", "DataTable", "Data Input 4"),
    ]
    outputs = [PortSpec("collection", "DataTable", "Collected Data")]
    parameters = []

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        dfs = []
        for key in ("data1", "data2", "data3", "data4"):
            d = inputs.get(key, [])
            if d and isinstance(d, list) and len(d) > 0:
                dfs.append(pd.DataFrame(d))
        if not dfs:
            return OperatorResult(outputs={"collection": []})
        result = pd.concat(dfs, ignore_index=True)
        return OperatorResult(outputs={"collection": result.to_dict(orient="records")})


@register_operator
class MacroOp(BaseOperator):
    id = "macro"
    name = "Macro"
    category = "utility"
    description = "Define a macro variable for pipeline configurations. Passthrough upstream data."
    inputs = [PortSpec("input", "DataTable", "Passthrough Input (optional)")]
    outputs = [PortSpec("output", "DataTable", "Passthrough Output")]
    parameters = [
        ParamSpec("macro_name", "str", "", "Macro Name"),
        ParamSpec("macro_value", "str", "", "Macro Value"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("input", [])
        macro_name = params.get("macro_name", "")
        macro_value = params.get("macro_value", "")
        result = {"output": data, "macro_name": macro_name, "macro_value": macro_value}
        if macro_name:
            result[macro_name] = macro_value
        return OperatorResult(outputs=result)


@register_operator
class WriteAsText(BaseOperator):
    id = "write_as_text"
    name = "WriteAsText"
    category = "utility"
    description = "Write data preview/summary to a text file for debugging"
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Passthrough Data")]
    parameters = [
        ParamSpec("file_path", "str", "", "Output File Path"),
        ParamSpec("format", "select", "text", "Output Format",
                  options=["json", "csv", "text"]),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        file_path = params.get("file_path", "")
        fmt = params.get("format", "text")

        if not file_path:
            raise ValueError("WriteAsText: file_path is required")

        dir_name = os_mod.path.dirname(file_path)
        if dir_name:
            os_mod.makedirs(dir_name, exist_ok=True)

        df = pd.DataFrame(data)

        if fmt == "json":
            content = df.to_json(orient="records", indent=2, force_ascii=False)
        elif fmt == "csv":
            content = df.to_csv(index=False)
        else:
            if df.empty:
                content = "(empty data)"
            else:
                lines = [f"Rows: {len(df)}, Columns: {list(df.columns)}"]
                lines.append(df.head(10).to_string(index=False))
                content = "\n".join(lines)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return OperatorResult(outputs={"data": data})
