from app.engine.operator_contract import OperatorContext


class TestLogger:
    def info(self, message, **details):
        pass

    def warning(self, message, **details):
        pass

    def error(self, message, **details):
        pass


def operator_context(workspace_dir=None) -> OperatorContext:
    return OperatorContext(
        run_id="test-run", node_id="test-node", project_id=None,
        artifact_service=None, cancel_requested=lambda: False, logger=TestLogger(),
        workspace_dir=workspace_dir,
    )


def execute_operator(operator, inputs, params, workspace_dir=None):
    context = operator_context(workspace_dir)
    runner = getattr(operator, "execute")
    return runner(context, inputs, params).outputs
