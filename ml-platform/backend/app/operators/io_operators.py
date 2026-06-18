from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import pandas as pd


@register_operator
class CSVImport(BaseOperator):
    id = "csv_import"
    name = "CSV/Excel Import"
    category = "data_io"
    description = "Import data from CSV or Excel file"
    inputs = []
    outputs = [PortSpec("data", "DataTable", "Output Data")]
    parameters = [
        ParamSpec("file_path", "file", "", "Data File"),
        ParamSpec("delimiter", "str", ",", "Delimiter"),
        ParamSpec("has_header", "boolean", True, "Has Header Row"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, inputs, params):
        file_path = params.get("file_path", "")
        delimiter = params.get("delimiter", ",")
        has_header = params.get("has_header", True)
        try:
            if file_path.endswith((".xls", ".xlsx")):
                df = pd.read_excel(file_path, header=0 if has_header else None)
            else:
                df = pd.read_csv(file_path, delimiter=delimiter, header=0 if has_header else None)
            return {"data": df.to_dict(orient="records")}
        except Exception as e:
            raise RuntimeError(f"Failed to import file: {e}")

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}
