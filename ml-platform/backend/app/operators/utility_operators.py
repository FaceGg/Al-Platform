# -*- coding: utf-8 -*-
import threading

from app.engine.operator_contract import OperatorContext, OperatorResult
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
from app.engine.export_paths import resolve_export_path
from app.services.python_script_runtime import PythonScriptRuntime
import pandas as pd

PYTHON_SCRIPT_MAX_LENGTH = 100_000
PYTHON_SCRIPT_MAX_CELLS = 1_000_000

# 固定输入/输出接口模板：编辑器预填，运行时强校验（改接口 → 拒绝运行）。
PYTHON_SCRIPT_INTERFACE_TOKEN = "输入接口（固定"
PYTHON_SCRIPT_HEADER = (
    "# ============================================================\n"
    "# 输入接口（固定，请勿修改，修改后将无法运行）\n"
    "# df : pandas.DataFrame —— 上游节点的输入数据表，平台自动注入，直接使用\n"
    "# ============================================================"
)
PYTHON_SCRIPT_FOOTER = (
    "# ============================================================\n"
    "# 输出接口（固定，请勿修改，修改后将无法运行）\n"
    "# result : 输出结果，须为 pandas.DataFrame 或 dict 记录列表，平台自动传给下游\n"
    "#          （在上方功能实现区为 result 赋值即可）\n"
    "# ============================================================"
)
PYTHON_SCRIPT_TEMPLATE = (
    PYTHON_SCRIPT_HEADER + "\n"
    "\n"
    "import pandas as pd\n"
    "\n"
    "\n"
    "def process(df: pd.DataFrame) -> pd.DataFrame:\n"
    "    \"\"\"功能实现区：把中间处理逻辑写在这里。\"\"\"\n"
    "    result = df.copy()        # 输入：以上游数据表 df 为起点\n"
    "    # ...                     # 中间：在此编写处理逻辑\n"
    "    return result             # 输出：返回最终结果（pandas.DataFrame 或 dict 记录列表）\n"
    "\n"
    "\n"
    "def main() -> pd.DataFrame:\n"
    "    return process(df)\n"
    "\n"
    "\n"
    "if __name__ == \"__main__\":\n"
    "    result = main()\n"
    "\n"
    + PYTHON_SCRIPT_FOOTER + "\n"
)


def _validate_script_interface(script: str) -> None:
    """接口强校验：模板脚本（含固定标记）必须原样保留输入/输出接口。

    无模板标记的历史脚本按旧契约放行（向后兼容存量工作流）。
    """
    normalized = script.strip()
    if not normalized or PYTHON_SCRIPT_INTERFACE_TOKEN not in normalized:
        return
    if not (
        normalized.startswith(PYTHON_SCRIPT_HEADER)
        and normalized.endswith(PYTHON_SCRIPT_FOOTER.rstrip())
    ):
        raise RuntimeError(
            "PythonScript: 输入/输出接口为固定模板，不可修改；"
            "请在功能实现区编写逻辑，或重新打开编辑器恢复模板后重试",
        )

_RUNTIME_LOCK = threading.Lock()
_RUNTIME: PythonScriptRuntime | None = None


def _python_script_runtime() -> PythonScriptRuntime:
    """Build the runtime from settings once per process."""
    global _RUNTIME
    with _RUNTIME_LOCK:
        if _RUNTIME is None:
            from app.config import settings

            sources = [
                source.strip()
                for source in str(settings.python_script_pip_sources or "").split(",")
                if source.strip()
            ]
            _RUNTIME = PythonScriptRuntime(
                venv_dir=str(settings.python_script_venv_dir or ""),
                pip_sources=sources,
                auto_install=bool(settings.python_script_auto_install),
                exec_timeout=int(settings.python_script_timeout_seconds),
                install_timeout=int(settings.python_script_install_timeout_seconds),
            )
        return _RUNTIME


def _reset_python_script_runtime() -> None:
    """Test helper: drop the cached runtime so settings changes take effect."""
    global _RUNTIME
    with _RUNTIME_LOCK:
        _RUNTIME = None


@register_operator
class PythonScript(BaseOperator):
    id = "python_script"
    name = "Python Script"
    category = "utility"
    description = (
        "Run a Python script with fixed DataFrame input df and output result "
        "in an isolated subprocess; imports missing from the script venv are "
        "auto-installed from server-configured package sources"
    )
    inputs = [PortSpec("data", "DataTable", "Input Data")]
    outputs = [PortSpec("data", "DataTable", "Output Data")]
    parameters = [
        ParamSpec("auto_install", "boolean", True, "自动安装依赖库"),
        ParamSpec(
            "script", "str", PYTHON_SCRIPT_TEMPLATE,
            "Python Script (df -> result)", required=True,
        ),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        script = str(params.get("script", ""))
        if len(script) > PYTHON_SCRIPT_MAX_LENGTH:
            raise ValueError(
                f"PythonScript: script exceeds {PYTHON_SCRIPT_MAX_LENGTH} characters",
            )
        _validate_script_interface(script)
        data = inputs.get("data", [])
        df = data.copy() if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
        auto_install = params.get("auto_install")
        result = _python_script_runtime().execute(
            script, df,
            auto_install=None if auto_install is None else bool(auto_install),
        )
        if result.shape[0] * result.shape[1] > PYTHON_SCRIPT_MAX_CELLS:
            raise ValueError("PythonScript: output is too large")
        return OperatorResult(outputs={"data": result.to_dict(orient="records")})


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
        ParamSpec("file_path", "str", "", "Legacy output file path"),
        ParamSpec("file_name", "str", "", "File Name"),
        ParamSpec("format", "select", "text", "Output Format",
                  options=["json", "csv", "text"]),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        data = inputs.get("data", [])
        fmt = params.get("format", "text")
        extension = {"json": "json", "csv": "csv", "text": "txt"}[fmt]
        file_path = resolve_export_path(
            context,
            self.id,
            params.get("file_name"),
            extension,
            legacy_file_path=params.get("file_path"),
        )

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

        context.logger.info("Export written", path=str(file_path), format=fmt)

        return OperatorResult(outputs={"data": data})
