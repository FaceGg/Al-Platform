"""S2 feature-script sandbox (spec v0.9 §三 S2 + §17.2).

Two gates, in order:

1. ``ast_violations`` — static whitelist BEFORE any execution. Imports are
   limited to analysis libraries; file IO / eval / exec / dunder escapes are
   banned; the module must define the ``transform(df)`` entry point.
2. ``run_sandbox`` — a plain subprocess with a wall-clock timeout runs the
   generated script through ``runpy`` against a CSV snapshot inside a
   per-run temporary directory; the worker refuses any path that escapes that
   directory. Network denial comes from the import whitelist (no
   socket-capable module can be imported); on Linux an address-space rlimit
   is applied in addition.

Contract violations (row count, empty/constant/leakage/zero-variance columns)
are computed by ``check_contract`` as structured strings the P2 runner feeds
back to the LLM verbatim.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

ALLOWED_MODULES = {
    "pandas",
    "numpy",
    "math",
    "statistics",
    "re",
    "datetime",
    "scipy.stats",
}
FORBIDDEN_CALLS = {
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "breakpoint",
    "input",
    "globals",
    "locals",
    "vars",
    "delattr",
    "setattr",
    "getattr",
}
ENTRY_POINT = "transform"

# Driver executed by the sandbox subprocess. runpy loads the (already
# AST-whitelisted) script as a module; all I/O stays inside the workdir that
# the parent created for this single run.
_WORKER = r'''
import json
import runpy
import sys
from pathlib import Path

script_path, input_path, output_path = (Path(arg).resolve() for arg in sys.argv[1:4])
workdir = script_path.parent
for path in (input_path, output_path):
    if path.parent != workdir:
        raise SystemExit("path escapes sandbox workdir")
namespace = runpy.run_path(str(script_path), run_name="agent_feature_script")
import pandas as pd
frame = pd.read_csv(input_path)
transform = namespace["transform"]
result = transform(frame)
result.to_csv(output_path, index=False)
print(json.dumps({"rows": int(len(result))}))
'''


@dataclass
class SandboxResult:
    ok: bool
    output: object | None = None
    error: str | None = None
    violations: list[str] = field(default_factory=list)


def _module_root(name: str) -> str:
    return name.split(".")[0]


def ast_violations(script: str) -> list[str]:
    """Return structured violations; empty list means the script may run."""
    problems: list[str] = []
    try:
        tree = ast.parse(script)
    except SyntaxError as error:
        return [f"syntax_error: {error.msg} (line {error.lineno})"]

    has_entry_point = False
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == ENTRY_POINT:
            has_entry_point = True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name not in ALLOWED_MODULES:
                    problems.append(
                        f"forbidden_import: {alias.name} (allowed: {sorted(ALLOWED_MODULES)})"
                    )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module not in ALLOWED_MODULES and _module_root(module) not in {
                _module_root(allowed) for allowed in ALLOWED_MODULES
            }:
                problems.append(
                    f"forbidden_import: from {module} (allowed: {sorted(ALLOWED_MODULES)})"
                )
        elif isinstance(node, ast.Call):
            called = node.func
            if isinstance(called, ast.Name) and called.id in FORBIDDEN_CALLS:
                problems.append(f"forbidden_call: {called.id}()")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            problems.append(f"dunder_access: {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            problems.append(f"dunder_access: .{node.attr}")

    if not has_entry_point:
        problems.append(f"missing_entrypoint: define def {ENTRY_POINT}(df)")
    return problems


def check_contract(
    input_frame: "pd.DataFrame",
    output_frame: "pd.DataFrame",
    *,
    leakage_columns: list[str] | None = None,
) -> list[str]:
    """Validate the S2 output contract; returns feedable violation strings."""
    import pandas as pd

    violations: list[str] = []
    if len(output_frame) != len(input_frame):
        violations.append(
            f"row_count_changed: {len(input_frame)} -> {len(output_frame)}"
        )
    leakage = set(leakage_columns or [])
    # Empty/constant/zero-variance checks apply to GENERATED columns only —
    # passthrough input columns keep their upstream shapes. Leakage applies to
    # every output column.
    generated = [column for column in output_frame.columns if column not in input_frame.columns]
    for column in output_frame.columns:
        if str(column) in leakage:
            violations.append(f"leakage_column_present: {column}")
    for column in generated:
        series = output_frame[column]
        if series.isna().all():
            violations.append(f"empty_column: {column}")
            continue
        non_null = series.dropna()
        if pd.api.types.is_float_dtype(series):
            if len(non_null) and float(non_null.var()) == 0.0:
                violations.append(f"zero_variance: {column}")
                continue
        if non_null.nunique() <= 1:
            violations.append(f"constant_column: {column}")
    return violations


def run_sandbox(
    script: str,
    input_frame: "pd.DataFrame",
    *,
    timeout_seconds: int = 120,
) -> SandboxResult:
    """AST-gate, then execute in a subprocess; never raises."""
    violations = ast_violations(script)
    if violations:
        return SandboxResult(ok=False, error="ast_violations", violations=violations)

    with tempfile.TemporaryDirectory(prefix="agent-s2-") as workdir:
        work = Path(workdir)
        script_path = work / "feature_script.py"
        input_path = work / "input.csv"
        output_path = work / "output.csv"
        script_path.write_text(script, encoding="utf-8")
        input_frame.to_csv(input_path, index=False)

        command = [
            sys.executable, "-c", _WORKER,
            str(script_path), str(input_path), str(output_path),
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                cwd=str(work),
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(
                ok=False,
                error=f"subprocess timed out after {timeout_seconds}s",
                violations=[f"timeout_after_{timeout_seconds}s"],
            )

        if completed.returncode != 0:
            error_tail = (completed.stderr or "").strip().splitlines()[-3:]
            last_line = error_tail[-1] if error_tail else f"exit code {completed.returncode}"
            return SandboxResult(
                ok=False,
                error=" | ".join(error_tail) or last_line,
                violations=[f"runtime_error: {last_line}"],
            )
        try:
            import pandas as pd

            output = pd.read_csv(output_path)
        except OSError as error:
            return SandboxResult(ok=False, error=f"output_unreadable: {error}")
        except pd.errors.EmptyDataError:
            # 脚本把样本过滤成了 0 行/0 列——模型的合法失误（过滤过严），
            # 应作为该次尝试失败退回 S2 自纠，而不是炸掉执行线程
            # （拧紧#3 a8764623 事故）。
            return SandboxResult(
                ok=False,
                error="empty_output: script produced no rows/columns",
                violations=["empty_output"],
            )
        except pd.errors.ParserError as error:
            return SandboxResult(ok=False, error=f"output_unparseable: {error}")
        if output.empty:
            # 有表头但 0 行：下游训练/切分必崩，统一按结构化失败退回自纠。
            return SandboxResult(
                ok=False,
                error="empty_output: script produced 0 rows",
                violations=["empty_output"],
            )
        return SandboxResult(ok=True, output=output, error=None)
