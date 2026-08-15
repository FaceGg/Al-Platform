from app.engine.operator_contract import ArtifactDraft, OperatorContext, OperatorResult
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
from app.engine.export_paths import resolve_export_path
import pandas as pd
import os
import tempfile
import urllib.request
from pathlib import Path


def _dataset_export_result(data, frame: pd.DataFrame, path: Path) -> OperatorResult:
    """Expose workflow CSV outputs as project-scoped datasets as well as files."""
    schema = [
        {
            "name": str(column),
            "dtype": str(frame[column].dtype),
            "null_count": int(frame[column].isna().sum()),
        }
        for column in frame.columns
    ]
    return OperatorResult(
        outputs={"data": data},
        artifacts=[ArtifactDraft(
            name=path.name,
            type="dataset",
            data=path,
            format="csv",
            metadata={
                "source": "workflow_export",
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "schema": schema,
            },
        )],
    )


@register_operator
class CSVImport(BaseOperator):
    id = "csv_import"
    name = "CSV/Excel Import"
    category = "io"
    description = "Import data from CSV or Excel file"
    inputs = []
    outputs = [PortSpec("data", "DataTable", "Output Data")]
    parameters = [
        ParamSpec(
            "source", "select", "local", "Source",
            options=["local", "url", "artifact"],
        ),
        ParamSpec("file_path", "file", "", "Data File", required=True, required_when={"source": "local"}),
        ParamSpec("dataset_artifact_id", "str", "", "Dataset Artifact ID", required=True, required_when={"source": "artifact"}),
        ParamSpec("url", "str", "", "File URL", required=True, required_when={"source": "url"}),
        ParamSpec("delimiter", "str", ",", "Delimiter"),
        ParamSpec("has_header", "boolean", True, "Has Header Row"),
    ]

    def validate(self, inputs):
        return True

    def _download_url(self, url, workspace_dir: Path | None = None):
        with urllib.request.urlopen(url) as response:
            suffix = ".csv"
            if ".xls" in url.lower():
                suffix = ".xlsx"
            elif ".xlsx" in url.lower():
                suffix = ".xlsx"
            download_dir = None
            if workspace_dir is not None:
                download_dir = Path(workspace_dir) / "downloads"
                download_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=suffix,
                dir=download_dir,
            ) as tmp:
                tmp.write(response.read())
                return tmp.name

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        source = params.get("source", "local")
        delimiter = params.get("delimiter", ",")
        has_header = params.get("has_header", True)
        header_arg = 0 if has_header else None

        if source == "artifact":
            artifact_id = params.get("dataset_artifact_id", "")
            if not artifact_id or context.artifact_service is None or not context.project_id:
                raise RuntimeError("Dataset Artifact ID and project context are required")
            try:
                with context.artifact_service.materialize(
                    artifact_id,
                    context.project_id,
                    expected_type="dataset",
                ) as artifact_path:
                    df = self._read_frame(artifact_path, delimiter, header_arg)
                return OperatorResult(outputs={"data": df.to_dict(orient="records")})
            except Exception as e:
                raise RuntimeError(f"Failed to import Artifact: {e}") from e
        downloaded_path = None
        try:
            if source == "url":
                url = params.get("url", "")
                if not url:
                    raise RuntimeError("URL parameter is required when source is 'url'")
                downloaded_path = self._download_url(url, context.workspace_dir)
                file_path = downloaded_path
            else:
                file_path = params.get("file_path", "")

            if not file_path:
                raise RuntimeError("File path or URL is required")
            df = self._read_frame(Path(file_path), delimiter, header_arg)
            return OperatorResult(outputs={"data": df.to_dict(orient="records")})
        except Exception as e:
            raise RuntimeError(f"Failed to import file: {e}")
        finally:
            if downloaded_path:
                Path(downloaded_path).unlink(missing_ok=True)

    @staticmethod
    def _read_frame(path: Path, delimiter: str, header_arg):
        if path.suffix.lower() in (".xls", ".xlsx"):
            return pd.read_excel(path, header=header_arg)
        return pd.read_csv(path, delimiter=delimiter, header=header_arg)

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
        ParamSpec('file_path', 'str', '', 'Legacy output file path'),
        ParamSpec('file_name', 'str', '', 'File Name'),
        ParamSpec('format', 'select', 'csv', 'Output Format', options=['csv']),
        ParamSpec('separator', 'select', ',', 'Separator', options=[',', ';', '\\t', '|']),
        ParamSpec('include_header', 'boolean', True, 'Include header'),
        ParamSpec('encoding', 'select', 'utf-8', 'Encoding', options=['utf-8', 'gbk']),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get('data', [])
        df = pd.DataFrame(data)
        path = resolve_export_path(
            context,
            self.id,
            params.get('file_name'),
            'csv',
            legacy_file_path=params.get('file_path'),
        )
        sep = params.get('separator', ',').replace('\\t', '	')
        df.to_csv(
            path,
            index=False,
            sep=sep,
            header=bool(params.get('include_header', True)),
            encoding=params.get('encoding', 'utf-8'),
        )
        context.logger.info('Export written', path=str(path), format='csv')
        return _dataset_export_result(data, df, path)

@register_operator
class ImageImport(BaseOperator):
    id = 'image_import'
    name = 'Image Import'
    category = 'io'
    description = 'Import image files metadata'
    inputs = []
    outputs = [PortSpec('data', 'DataTable', 'Image metadata')]
    parameters = [
        ParamSpec('file_path', 'str', '', 'Image file or directory path', required=True),
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
        ParamSpec('file_path', 'str', '', 'JSON file path', required=True),
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
        ParamSpec('file_path', 'file', '', 'Excel file path', required=True),
        ParamSpec('sheet_name', 'str', '0', 'Sheet name or index'),
        ParamSpec('header_row', 'int', 0, 'Header row index'),
        ParamSpec('skiprows', 'int', 0, 'Rows to skip before header'),
        ParamSpec('usecols', 'str', '', 'Columns to read (for example A:C)'),
        ParamSpec('nrows', 'int', 0, 'Maximum rows (0 means all)'),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        path = params.get('file_path', '')
        sheet = params.get('sheet_name', '0')
        try: sheet = int(sheet)
        except ValueError: pass
        header = int(params.get('header_row', 0))
        if not path:
            raise RuntimeError('Excel file path is required')
        if not os.path.isfile(path):
            raise RuntimeError(f'Excel file not found: {path}')
        skiprows = int(params.get('skiprows', 0))
        usecols = str(params.get('usecols', '')).strip() or None
        nrows = int(params.get('nrows', 0)) or None
        df = pd.read_excel(
            path,
            sheet_name=sheet,
            header=header,
            skiprows=skiprows or None,
            usecols=usecols,
            nrows=nrows,
        )
        return OperatorResult(outputs={'data': df.to_dict(orient='records')})

@register_operator
class ReadDatabase(BaseOperator):
    id = 'read_database'
    name = 'Read Database'
    category = 'io'
    description = 'Read data from database via SQL'
    inputs = []
    outputs = [PortSpec('data', 'DataTable', 'Query result')]
    parameters = [
        ParamSpec('connection_string', 'str', '', 'Database connection string', required=True),
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
        ParamSpec('url', 'str', '', 'URL to fetch', required=True),
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
        ParamSpec('file_path', 'str', '', 'Legacy output file path'),
        ParamSpec('file_name', 'str', '', 'File Name'),
        ParamSpec('format', 'select', 'csv', 'Output Format', options=['csv']),
        ParamSpec('separator', 'select', ',', 'Separator', options=[',', ';', '\\t']),
        ParamSpec('include_header', 'boolean', True, 'Include header'),
        ParamSpec('encoding', 'select', 'utf-8', 'Encoding', options=['utf-8', 'gbk']),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get('data', [])
        df = pd.DataFrame(data)
        path = resolve_export_path(
            context,
            self.id,
            params.get('file_name'),
            'csv',
            legacy_file_path=params.get('file_path'),
        )
        sep = params.get('separator', ',').replace('\\t', '	')
        df.to_csv(
            path,
            index=False,
            sep=sep,
            header=bool(params.get('include_header', True)),
            encoding=params.get('encoding', 'utf-8'),
        )
        context.logger.info('Export written', path=str(path), format='csv')
        return _dataset_export_result(data, df, path)

@register_operator
class Retrieve(BaseOperator):
    id = 'retrieve'
    name = 'Retrieve'
    category = 'io'
    description = 'Retrieve stored dataset from repository'
    inputs = []
    outputs = [PortSpec('data', 'DataTable', 'Retrieved data')]
    parameters = [ParamSpec('repository_entry', 'str', '', 'Repository path', required=True)]
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
        ParamSpec('repository_entry', 'str', '', 'Repository path', required=True),
        ParamSpec('overwrite', 'bool', False, 'Overwrite existing'),
    ]
    def validate(self, inputs): return True
    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get('data', [])
        df = pd.DataFrame(data)
        path = params.get('repository_entry', '')
        if path: df.to_csv(path, index=False)
        return OperatorResult(outputs={'data': data})
