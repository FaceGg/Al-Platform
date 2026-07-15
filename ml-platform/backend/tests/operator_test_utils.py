from app.engine.operator_contract import OperatorContext


class TestLogger:
    def info(self, message, **details):
        pass

    def warning(self, message, **details):
        pass

    def error(self, message, **details):
        pass


def operator_context() -> OperatorContext:
    return OperatorContext(
        run_id="test-run", node_id="test-node", project_id=None,
        artifact_service=None, cancel_requested=lambda: False, logger=TestLogger(),
    )


def execute_operator(operator, inputs, params):
    return operator.execute(operator_context(), inputs, params).outputs
