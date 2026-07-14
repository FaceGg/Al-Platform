from app.engine.operator_contract import OperatorContext, OperatorResult
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
    category = "io"
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

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
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
            return OperatorResult(outputs={"data": df.to_dict(orient="records")})
        except Exception as e:
            raise RuntimeError(f"Failed to import file: {e}")
        finally:
            if source == "url" and os.path.exists(file_path):
                os.unlink(file_path)

    def get_preview(self, outputs):
        data = outputs.get("data", [])
        return {"data": data[:10], "total_rows": len(data)}

@register_operator
class CSVExport(BaseOperator):
    id = 'csv_export'
    name = 'CSV Export'
    category = 'io'
    description = 'Export data to a CSV file'
    inputs = [PortSpec('data', 'DataTable', 'Data to export')]
    outputs = [PortSpec('data', 'DataTable', 'Passthrough')]
    parameters = [
        ParamSpec('file_path', 'str', '', 'Output file path'),
        ParamSpec('separator', 'select', ',', 'Separator', options=[',', ';', '\\t', '|']),
        ParamSpec('include_header', 'bool', True, 'Include header'),
        ParamSpec('encoding', 'select', 'utf-8', 'Encoding', options=['utf-8', 'gbk']),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get('data', [])
        df = pd.DataFrame(data)
        path = params.get('file_path', '')
        if path:
            sep = params.get('separator', ',').replace('\\t', '	')
            df.to_csv(path, index=False, sep=sep, encoding=params.get('encoding', 'utf-8'))
        return OperatorResult(outputs={'data': data})

@register_operator
class ImageImport(BaseOperator):
    id = 'image_import'
    name = 'Image Import'
    category = 'io'
    description = 'Import image files metadata'
    inputs = []
    outputs = [PortSpec('data', 'DataTable', 'Image metadata')]
    parameters = [
        ParamSpec('file_path', 'str', '', 'Image file or directory path'),
        ParamSpec('pattern', 'str', '*.png', 'File pattern'),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        import glob as _glob
        path = params.get('file_path', '')
        pattern = params.get('pattern', '*.png')
        files = _glob.glob(os.path.join(path, pattern)) if os.path.isdir(path) else ([path] if os.path.isfile(path) else [])
        return OperatorResult(outputs={'data': [{'filename': os.path.basename(f), 'path': f} for f in files]})

@register_operator
class JSONImport(BaseOperator):
    id = 'json_import'
    name = 'JSON Import'
    category = 'io'
    description = 'Import data from JSON file'
    inputs = []
    outputs = [PortSpec('data', 'DataTable', 'Imported data')]
    parameters = [
        ParamSpec('file_path', 'str', '', 'JSON file path'),
        ParamSpec('orient', 'select', 'records', 'Orientation', options=['records', 'columns', 'index', 'split']),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        path = params.get('file_path', '')
        orient = params.get('orient', 'records')
        if path and os.path.isfile(path):
            df = pd.read_json(path, orient=orient)
            return OperatorResult(outputs={'data': df.to_dict(orient='records')})
        return OperatorResult(outputs={'data': []})

@register_operator
class ReadExcel(BaseOperator):
    id = 'read_excel'
    name = 'Read Excel'
    category = 'io'
    description = 'Read data from Excel file'
    inputs = []
    outputs = [PortSpec('data', 'DataTable', 'Imported data')]
    parameters = [
        ParamSpec('file_path', 'str', '', 'Excel file path'),
        ParamSpec('sheet_name', 'str', '0', 'Sheet name or index'),
        ParamSpec('header_row', 'int', 0, 'Header row index'),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        path = params.get('file_path', '')
        sheet = params.get('sheet_name', '0')
        try: sheet = int(sheet)
        except ValueError: pass
        header = int(params.get('header_row', 0))
        if path and os.path.isfile(path):
            df = pd.read_excel(path, sheet_name=sheet, header=header)
            return OperatorResult(outputs={'data': df.to_dict(orient='records')})
        return OperatorResult(outputs={'data': []})

@register_operator
class ReadDatabase(BaseOperator):
    id = 'read_database'
    name = 'Read Database'
    category = 'io'
    description = 'Read data from database via SQL'
    inputs = []
    outputs = [PortSpec('data', 'DataTable', 'Query result')]
    parameters = [
        ParamSpec('connection_string', 'str', '', 'Database connection string'),
        ParamSpec('query', 'str', 'SELECT * FROM table LIMIT 100', 'SQL Query'),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        conn_str = params.get('connection_string', '')
        query = params.get('query', '')
        if conn_str and query:
            try:
                import sqlalchemy as sa
                engine = sa.create_engine(conn_str)
                df = pd.read_sql(query, engine)
                return OperatorResult(outputs={'data': df.to_dict(orient='records')})
            except: pass
        return OperatorResult(outputs={'data': []})

@register_operator
class ReadURL(BaseOperator):
    id = 'read_url'
    name = 'Read URL'
    category = 'io'
    description = 'Read data from a URL'
    inputs = []
    outputs = [PortSpec('data', 'DataTable', 'Downloaded data')]
    parameters = [
        ParamSpec('url', 'str', '', 'URL to fetch'),
        ParamSpec('method', 'select', 'GET', 'HTTP Method', options=['GET', 'POST']),
        ParamSpec('file_type', 'select', 'csv', 'File Type', options=['csv', 'json', 'excel']),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        url = params.get('url', '')
        if not url: return OperatorResult(outputs={'data': []})
        try:
            import urllib.request
            with urllib.request.urlopen(url) as resp:
                content = resp.read()
            ft = params.get('file_type', 'csv')
            buf = io.BytesIO(content)
            df = pd.read_csv(buf) if ft == 'csv' else (pd.read_excel(buf) if ft == 'excel' else pd.read_json(buf))
            return OperatorResult(outputs={'data': df.to_dict(orient='records')})
        except: return OperatorResult(outputs={'data': []})

@register_operator
class WriteCSV(BaseOperator):
    id = 'write_csv'
    name = 'Write CSV'
    category = 'io'
    description = 'Write data to a CSV file'
    inputs = [PortSpec('data', 'DataTable', 'Data to write')]
    outputs = [PortSpec('data', 'DataTable', 'Passthrough')]
    parameters = [
        ParamSpec('file_path', 'str', '', 'Output file path'),
        ParamSpec('separator', 'select', ',', 'Separator', options=[',', ';', '\\t']),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get('data', [])
        df = pd.DataFrame(data)
        path = params.get('file_path', '')
        if path:
            sep = params.get('separator', ',').replace('\\t', '	')
            df.to_csv(path, index=False, sep=sep)
        return OperatorResult(outputs={'data': data})

@register_operator
class Retrieve(BaseOperator):
    id = 'retrieve'
    name = 'Retrieve'
    category = 'io'
    description = 'Retrieve stored dataset from repository'
    inputs = []
    outputs = [PortSpec('data', 'DataTable', 'Retrieved data')]
    parameters = [ParamSpec('repository_entry', 'str', '', 'Repository path')]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        path = params.get('repository_entry', '')
        if path and os.path.isfile(path):
            df = pd.read_csv(path)
            return OperatorResult(outputs={'data': df.to_dict(orient='records')})
        return OperatorResult(outputs={'data': []})

@register_operator
class Store(BaseOperator):
    id = 'store'
    name = 'Store'
    category = 'io'
    description = 'Store dataset to repository'
    inputs = [PortSpec('data', 'DataTable', 'Data to store')]
    outputs = [PortSpec('data', 'DataTable', 'Passthrough')]
    parameters = [
        ParamSpec('repository_entry', 'str', '', 'Repository path'),
        ParamSpec('overwrite', 'bool', False, 'Overwrite existing'),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get('data', [])
        df = pd.DataFrame(data)
        path = params.get('repository_entry', '')
        if path: df.to_csv(path, index=False)
        return OperatorResult(outputs={'data': data})
