from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Callable

import networkx as nx

from app.engine.data_bus import DataBus
from app.engine.registry import OperatorRegistry
from app.engine.run_control import RunCancelled, RunControl
from app.engine.run_state import ExecutionPolicy
from app.engine.operator_contract import (
    OperatorContext, OperatorResult, validate_operator_params, validate_operator_result,
)


_EXECUTION_POLICY_PARAMS = {"timeout_seconds", "max_retries", "retry_delay_seconds"}


class _OperatorLogger:
    def __init__(self):
        self.entries = []

    def _write(self, level, message, **details):
        self.entries.append({"level": level, "message": message, **details})

    def info(self, message, **details):
        self._write("info", message, **details)

    def warning(self, message, **details):
        self._write("warning", message, **details)

    def error(self, message, **details):
        self._write("error", message, **details)


class DAGExecutor:
    def __init__(
        self, nodes: list[dict], edges: list[dict], artifact_service=None,
        project_id: str | None = None,
    ):
        self._nodes = nodes
        self._edges = edges
        # Different output ports may legitimately connect the same two nodes.
        # A DiGraph overwrites the earlier edge in that case, losing its port map.
        self._graph: nx.MultiDiGraph = nx.MultiDiGraph()
        self._artifact_service = artifact_service
        self._project_id = project_id

        for node in nodes:
            self._graph.add_node(
                node["id"],
                operator_id=node.get("operator_id", ""),
                label=node.get("label", ""),
                params=node.get("params", {}),
            )

        for edge in edges:
            self._graph.add_edge(
                edge["source"],
                edge["target"],
                source_port=edge.get("source_port", ""),
                target_port=edge.get("target_port", ""),
            )

    def validate(self) -> list[str]:
        errors: list[str] = []

        # Check for non-loop cycles
        loop_node_ids: set[str] = set()
        for node_id, data in self._graph.nodes(data=True):
            op_id = data.get("operator_id", "")
            if op_id in ("loop", "merge"):
                loop_node_ids.add(node_id)

        try:
            cycles = list(nx.simple_cycles(self._graph))
            for cycle in cycles:
                # Allow cycles that involve loop nodes
                if not any(n in loop_node_ids for n in cycle):
                    errors.append(f"Cycle detected: {' -> '.join(cycle)}")
        except nx.NetworkXNoCycle:
            pass

        for node_id, data in self._graph.nodes(data=True):
            op_id = data.get("operator_id", "")
            if op_id and OperatorRegistry.get(op_id) is None:
                errors.append(f"Node '{node_id}': operator '{op_id}' not registered")

        for node_id, data in self._graph.nodes(data=True):
            op_id = data.get("operator_id", "")
            op = OperatorRegistry.get(op_id)
            if op is None:
                continue
            if not op.inputs:
                continue
            predecessors = list(self._graph.predecessors(node_id))
            if not predecessors:
                continue
            if len(op.inputs) == 1 and len(predecessors) == 1:
                continue
            incoming_ports = {
                edge_data.get("target_port", "")
                for _, _, _, edge_data in self._graph.in_edges(
                    node_id, keys=True, data=True,
                )
            }
            for port in op.inputs:
                if port.name not in incoming_ports:
                    errors.append(f"Node '{node_id}': missing required input '{port.name}'")

        return errors

    def execute(
        self,
        run_id: str,
        status_callback: Callable[[str, str, str, dict | None], None] | None = None,
        run_control: RunControl | None = None,
    ) -> dict[str, Any]:
        run_control = run_control or RunControl()
        errors = self.validate()
        if errors:
            raise RuntimeError(f"DAG validation failed: {'; '.join(errors)}")

        results: dict[str, Any] = {}
        skipped: set[str] = set()
        topo_order = list(nx.topological_sort(self._graph))

        for node_id in topo_order:
            run_control.check_cancelled()
            if node_id in skipped:
                if status_callback:
                    status_callback(run_id, node_id, "skipped", {"reason": "Condition branch not taken"})
                results[node_id] = {}
                continue

            node_data = self._graph.nodes[node_id]
            op_id = node_data["operator_id"]
            params = node_data["params"]

            op = OperatorRegistry.get(op_id)
            if op is None:
                raise RuntimeError(f"Operator '{op_id}' not found for node '{node_id}'")

            # Check if any predecessor was skipped
            in_edges = list(self._graph.in_edges(node_id, keys=True, data=True))
            all_preds_skipped = all(src in skipped for src, _, _, _ in in_edges) if in_edges else False
            if all_preds_skipped:
                skipped.add(node_id)
                if status_callback:
                    status_callback(run_id, node_id, "skipped", {"reason": "Upstream nodes skipped"})
                results[node_id] = {}
                continue

            # Collect inputs
            inputs: dict[str, Any] = {}
            for src, _, _, edge_data in in_edges:
                if src in skipped:
                    continue
                target_port = edge_data.get("target_port", "")
                source_port = edge_data.get("source_port", "")
                src_results = results.get(src, {})
                upstream_path = src_results.get(source_port)
                if not upstream_path and src_results:
                    upstream_path = next(iter(src_results.values()))
                if upstream_path:
                    inputs[target_port or (op.inputs[0].name if op.inputs else "data")] = DataBus.load_data(upstream_path)

            if not op.validate(inputs):
                if status_callback:
                    status_callback(run_id, node_id, "failed", {"error": "Validation failed"})
                raise RuntimeError(f"Validation failed for node '{node_id}' (op '{op_id}')")

            try:
                if op_id in ("loop",) and self._has_loop_body(node_id):
                    outputs = self._execute_loop(
                        node_id, inputs, params, run_id, results, status_callback, run_control,
                    )
                    completed_attempt = 1
                else:
                    operator_result, completed_attempt = self._execute_with_policy(
                        op, inputs, params, run_id, node_id, status_callback, run_control,
                    )
                    outputs = operator_result.outputs
            except RunCancelled:
                self._emit_status(status_callback, run_id, node_id, "cancelled", None, {"attempt": 0})
                raise
            except Exception as e:
                raise RuntimeError(f"Execution failed for node '{node_id}': {e}") from e

            # Persist declared artifacts before exposing a completed node.
            artifact_refs = []
            if op_id not in ("loop",):
                artifact_refs = self._persist_artifacts(
                    operator_result,
                    run_id=run_id,
                    node_id=node_id,
                )

            # Save outputs
            node_results: dict[str, str] = {}
            for port_name, data in outputs.items():
                path = DataBus.save_data(run_id, node_id, port_name, data)
                node_results[port_name] = path
            results[node_id] = node_results
            if artifact_refs:
                node_results["artifacts"] = artifact_refs

            # Handle condition branching
            if op_id in ("condition",) and "false" in outputs:
                false_data = outputs["false"]
                false_empty = (isinstance(false_data, list) and len(false_data) == 0) or \
                              (isinstance(false_data, dict) and len(false_data) == 0) or \
                              (false_data is None or false_data == "")
                if false_empty:
                    for _, target, _, edge_data in self._graph.out_edges(
                        node_id, keys=True, data=True,
                    ):
                        if edge_data.get("source_port", "") == "false":
                            skipped.add(target)
                            descendants = list(nx.descendants(self._graph, target))
                            skipped.update(descendants)

            # Build preview
            preview: dict[str, Any] = {}
            for port_name, raw_data in outputs.items():
                if isinstance(raw_data, str) and len(raw_data) > 500:
                    preview[port_name] = raw_data[:200] + f"...({len(raw_data)} chars)"
                elif isinstance(raw_data, (list, dict)):
                    preview[port_name] = raw_data
                else:
                    preview[port_name] = str(raw_data)[:500]

            completion = preview
            if op_id not in ("loop",):
                completion = {
                    **preview,
                    "metrics": operator_result.metrics,
                    "logs": operator_result.logs,
                }
            self._emit_status(
                status_callback, run_id, node_id, "completed", completion,
                {"attempt": completed_attempt},
            )

        return results

    def _persist_artifacts(
        self,
        result: OperatorResult,
        *,
        run_id: str,
        node_id: str,
    ) -> list[dict[str, Any]]:
        if not result.artifacts:
            return []
        if self._artifact_service is None or not self._project_id:
            raise RuntimeError(
                "Artifact drafts require an artifact service and project context"
            )
        references = []
        for draft in result.artifacts:
            artifact = self._artifact_service.create_from_draft(
                draft,
                project_id=self._project_id,
                run_id=run_id,
                node_id=node_id,
            )
            references.append({
                "artifact_id": str(artifact.id),
                "uri": artifact.storage_uri,
                "size": artifact.file_size,
            })
        return references

    @staticmethod
    def _emit_status(status_callback, run_id, node_id, status, result=None, metadata=None):
        if status_callback is None:
            return
        try:
            status_callback(run_id, node_id, status, result, metadata or {})
        except TypeError:
            status_callback(run_id, node_id, status, result)

    def _execute_with_policy(
        self, op, inputs, params, run_id, node_id, status_callback, run_control,
    ):
        policy = ExecutionPolicy.from_params(params)
        operator_params = {key: value for key, value in params.items() if key not in _EXECUTION_POLICY_PARAMS}
        validated_params = validate_operator_params(op.parameters, operator_params)
        last_error = None
        for attempt in range(1, policy.max_retries + 2):
            run_control.check_cancelled()
            metadata = {"attempt": attempt}
            self._emit_status(status_callback, run_id, node_id, "running", None, metadata)
            logger = _OperatorLogger()
            context = OperatorContext(
                run_id=run_id,
                node_id=node_id,
                project_id=self._project_id,
                artifact_service=self._artifact_service,
                cancel_requested=run_control.is_cancel_requested,
                logger=logger,
            )
            pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"node-{node_id}")
            future = pool.submit(op.execute, context, inputs, validated_params)
            try:
                result = future.result(timeout=policy.timeout_seconds)
                validate_operator_result(op.outputs, result)
                if logger.entries:
                    result.logs = [*result.logs, *logger.entries]
                pool.shutdown(wait=False, cancel_futures=True)
                run_control.check_cancelled()
                return result, attempt
            except FutureTimeoutError:
                last_error = TimeoutError(
                    f"Node '{node_id}' timed out after {policy.timeout_seconds:g} seconds"
                )
                self._emit_status(
                    status_callback, run_id, node_id, "timed_out",
                    {"error": str(last_error), "error_code": "NODE_TIMED_OUT"}, metadata,
                )
            except RunCancelled:
                raise
            except Exception as exc:
                last_error = exc
                self._emit_status(
                    status_callback, run_id, node_id, "failed",
                    {"error": str(exc), "error_code": "NODE_EXECUTION_FAILED"}, metadata,
                )
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

            if attempt <= policy.max_retries:
                run_control.wait(policy.retry_delay_seconds)

        raise last_error or RuntimeError(f"Node '{node_id}' failed")

    def _has_loop_body(self, node_id: str) -> bool:
        """Check if the loop node has downstream nodes forming a loop body."""
        descendants = list(nx.descendants(self._graph, node_id))
        return len(descendants) > 0

    def _execute_loop(
        self, node_id: str, inputs: dict, params: dict,
        run_id: str, results: dict,
        status_callback, run_control: RunControl,
    ) -> dict[str, Any]:
        """Execute a loop by running the loop body subgraph repeatedly."""
        op = OperatorRegistry.get("loop")
        if op is None:
            raise RuntimeError("Loop operator not found")

        max_iterations = params.get("max_iterations", 10)

        # Get the loop body subgraph: children that aren't merge nodes
        out_edges = list(self._graph.out_edges(node_id))
        body_node_ids: set[str] = set()
        for src, tgt in out_edges:
            descendants = nx.descendants(self._graph, tgt)
            body_node_ids.add(tgt)
            body_node_ids.update(descendants)

        # Find merge node (node that connects back to loop or after loop)
        merge_node_id = None
        back_edges = []
        for src, tgt in self._graph.edges:
            if src in body_node_ids and tgt == node_id:
                back_edges.append((src, tgt))
            elif src in body_node_ids and tgt not in body_node_ids and tgt != node_id:
                merge_node_id = tgt

        all_iteration_results = []
        for iteration in range(max_iterations):
            if status_callback:
                status_callback(run_id, node_id, "running",
                              {"iteration": iteration + 1, "message": f"Loop iteration {iteration + 1}/{max_iterations}"})

            # Execute loop operator for this iteration
            iter_inputs = {**inputs, "iteration": iteration}
            iter_result, _ = self._execute_with_policy(
                op, iter_inputs, params, run_id, node_id, status_callback, run_control,
            )
            iter_outputs = iter_result.outputs

            # Check if loop should continue
            should_continue = iter_outputs.get("continue", True)
            if hasattr(should_continue, "item"):
                should_continue = bool(should_continue.item())
            if not should_continue:
                break

            # Execute body nodes
            body_nodes = [n for n, d in self._graph.nodes(data=True)
                         if n in body_node_ids]
            body_topo = [n for n in nx.topological_sort(
                self._graph.subgraph(body_nodes))]

            for body_node_id in body_topo:
                body_data = self._graph.nodes[body_node_id]
                body_op_id = body_data["operator_id"]
                body_op = OperatorRegistry.get(body_op_id)
                if body_op is None:
                    continue

                if status_callback:
                    status_callback(run_id, body_node_id, "running",
                                  {"iteration": iteration + 1})

                body_inputs: dict[str, Any] = {}
                # Get inputs from iteration outputs
                for pn, pv in iter_outputs.items():
                    body_inputs[f"iter_{pn}"] = pv

                # Also check regular predecessors
                for src, _, _, edge_data in self._graph.in_edges(
                    body_node_id, keys=True, data=True,
                ):
                    if src in results:
                        target_port = edge_data.get("target_port", "")
                        if target_port:
                            body_inputs[target_port] = results[src]
                    elif src == node_id:
                        # Connection from loop node
                        for pn, pv in iter_outputs.items():
                            body_inputs[pn] = pv

                try:
                    body_result, _ = self._execute_with_policy(
                        body_op, body_inputs, body_data["params"], run_id,
                        body_node_id, status_callback, run_control,
                    )
                    body_outputs = body_result.outputs
                except Exception:
                    body_outputs = {}

                body_node_results: dict[str, str] = {}
                for pn, data in body_outputs.items():
                    path = DataBus.save_data(
                        run_id, f"{body_node_id}_iter{iteration}", pn, data)
                    body_node_results[pn] = path
                results[body_node_id] = body_node_results

                if status_callback:
                    status_callback(run_id, body_node_id, "completed",
                                  {"iteration": iteration + 1})

            all_iteration_results.append(iter_outputs.get("result", {}))

        # Merge results
        final_result = {
            "iterations": len(all_iteration_results),
            "results": all_iteration_results,
        }
        return {"result": final_result}
