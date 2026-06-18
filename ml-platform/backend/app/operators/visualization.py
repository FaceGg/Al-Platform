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
