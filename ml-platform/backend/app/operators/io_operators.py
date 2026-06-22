from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
import pandas as pd
import os
import tempfile
import urllib.request


@register_operator
class CSVImport(BaseOperator):
    id = "csv_import"
    name = "CSV/Excel Import"
    category = "data_io"
    description = "Import data from CSV or Excel file"
    inputs = []
    outputs = [PortSpec("data", "DataTable", "Output Data")]
    parameters = [
        ParamSpec("source", "select", "local", "Source", options=["local", "url"]),
        ParamSpec("file_path", "file", "", "Data File"),
        ParamSpec("url", "str", "", "File URL"),
        ParamSpec("delimiter", "str", ",", "Delimiter"),
        ParamSpec("has_header", "boolean", True, "Has Header Row"),
    ]

    def validate(self, inputs):
        return True

    def _download_url(self, url):
        with urllib.request.urlopen(url) as response:
            suffix = ".csv"
            if ".xls" in url.lower():
                suffix = ".xlsx"
            elif ".xlsx" in url.lower():
                suffix = ".xlsx"
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tmp.write(response.read())
            tmp.close()
            return tmp.name

    def execute(self, inputs, params):
        source = params.get("source", "local")
        delimiter = params.get("delimiter", ",")
        has_header = params.get("has_header", True)
        header_arg = 0 if has_header else None

        if source == "url":
            url = params.get("url", "")
            if not url:
                raise RuntimeError("URL parameter is required when source is 'url'")
            file_path = self._download_url(url)
        else:
            file_path = params.get("file_path", "")

        if not file_path:
            raise RuntimeError("File path or URL is required")

        try:
            if file_path.endswith((".xls", ".xlsx")):
                df = pd.read_excel(file_path, header=header_arg)
            else:
                df = pd.read_csv(file_path, delimiter=delimiter, header=header_arg)
            return {"data": df.to_dict(orient="records")}
        except Exception as e:
            raise RuntimeError(f"Failed to import file: {e}")
        finally:
            if source == "url" and os.path.exists(file_path):
                os.unlink(file_path)

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}
