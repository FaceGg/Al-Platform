"""One-time source migration for the Week 3 operator protocol."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "app" / "operators"
IMPORT = "from app.engine.operator_contract import OperatorContext, OperatorResult\n"


class ExecuteReturnCollector(ast.NodeVisitor):
    def __init__(self):
        self.returns = []

    def visit_FunctionDef(self, node):
        if node.name == "execute":
            for statement in node.body:
                self.visit(statement)

    def visit_AsyncFunctionDef(self, node):
        return

    def visit_Lambda(self, node):
        return

    def visit_Return(self, node):
        if node.value is not None:
            self.returns.append(node.value)


def offsets(source: str) -> list[int]:
    result = [0]
    for line in source.splitlines(keepends=True):
        result.append(result[-1] + len(line))
    return result


def migrate(path: Path) -> None:
    source = path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    collector = ExecuteReturnCollector()
    collector.visit(tree)
    line_offsets = offsets(source)
    edits = []
    for value in collector.returns:
        start = line_offsets[value.lineno - 1] + value.col_offset
        end = line_offsets[value.end_lineno - 1] + value.end_col_offset
        expression = source[start:end]
        if expression.startswith("OperatorResult("):
            continue
        edits.append((start, end, f"OperatorResult(outputs={expression})"))

    for start, end, replacement in sorted(edits, reverse=True):
        source = source[:start] + replacement + source[end:]

    source = source.replace(
        "def execute(self, inputs, params):",
        "def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:",
    )
    if IMPORT not in source:
        lines = source.splitlines(keepends=True)
        insert_at = 1 if lines and "coding" in lines[0] else 0
        lines.insert(insert_at, IMPORT)
        source = "".join(lines)
    path.write_text(source, encoding="utf-8")


def main() -> None:
    for path in sorted(ROOT.glob("*.py")):
        if path.name == "__init__.py" or "def execute(" not in path.read_text(encoding="utf-8-sig"):
            continue
        migrate(path)
        print(path.name)


if __name__ == "__main__":
    main()
