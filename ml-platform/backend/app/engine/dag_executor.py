from __future__ import annotations

import uuid
from typing import Any, Callable

import networkx as nx

from app.engine.data_bus import DataBus
from app.engine.registry import OperatorRegistry


class DAGExecutor:
    def __init__(self, nodes: list[dict], edges: list[dict]):
        self._nodes = nodes
        self._edges = edges
        self._graph: nx.DiGraph = nx.DiGraph()

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

        try:
            cycles = list(nx.simple_cycles(self._graph))
            if cycles:
                for cycle in cycles:
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
            incoming_ports: set[str] = set()
            for src, tgt in self._graph.in_edges(node_id):
                try:
                    edge_data = self._graph.edges[src, tgt]
                    incoming_ports.add(edge_data.get("target_port", ""))
                except (KeyError, TypeError):
                    pass
            for port in op.inputs:
                if port.name not in incoming_ports:
                    errors.append(f"Node '{node_id}': missing required input '{port.name}'")

        return errors

    def execute(
        self,
        run_id: str,
        status_callback: Callable[[str, str, str, dict | None], None] | None = None,
    ) -> dict[str, Any]:
        errors = self.validate()
        if errors:
            raise RuntimeError(f"DAG validation failed: {'; '.join(errors)}")

        results: dict[str, Any] = {}
        skipped: set[str] = set()
        topo_order = list(nx.topological_sort(self._graph))

        for node_id in topo_order:
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

            if status_callback:
                status_callback(run_id, node_id, "running")

            # Check if any predecessor was skipped - if so, skip this node too
            in_edges = [(src, tgt) for src, tgt in self._graph.in_edges(node_id)]
            all_preds_skipped = all(src in skipped for src, tgt in in_edges) if in_edges else False
            if all_preds_skipped:
                skipped.add(node_id)
                if status_callback:
                    status_callback(run_id, node_id, "skipped", {"reason": "Upstream nodes skipped"})
                results[node_id] = {}
                continue

            # Collect inputs from upstream nodes
            inputs: dict[str, Any] = {}
            for src, tgt in in_edges:
                if src in skipped:
                    continue
                edge_data = self._graph.edges.get((src, tgt), {})
                target_port = edge_data.get("target_port", "")
                source_port = edge_data.get("source_port", "")
                src_results = results.get(src, {})
                upstream_path = src_results.get(source_port)
                if not upstream_path and src_results:
                    upstream_path = next(iter(src_results.values()))
                if upstream_path:
                    inputs[target_port or op.inputs[0].name if op.inputs else "data"] = DataBus.load_data(upstream_path)

            if not op.validate(inputs):
                if status_callback:
                    status_callback(run_id, node_id, "failed", {"error": "Validation failed"})
                raise RuntimeError(f"Validation failed for node '{node_id}' (op '{op_id}')")

            try:
                outputs = op.execute(inputs, params)
            except Exception as e:
                if status_callback:
                    status_callback(run_id, node_id, "failed", {"error": str(e)})
                raise RuntimeError(f"Execution failed for node '{node_id}': {e}") from e

            # Save outputs
            node_results: dict[str, str] = {}
            for port_name, data in outputs.items():
                path = DataBus.save_data(run_id, node_id, port_name, data)
                node_results[port_name] = path
            results[node_id] = node_results

            # Handle control flow: check if this node has "true"/"false" branches
            # If "false" output is empty, skip downstream nodes connected to "false" port
            if op_id in ("condition",) and "false" in outputs:
                false_data = outputs["false"]
                false_empty = (isinstance(false_data, list) and len(false_data) == 0) or \
                              (isinstance(false_data, dict) and len(false_data) == 0) or \
                              (false_data is None or false_data == "")
                if false_empty:
                    # Skip all downstream nodes that connect to "false" port
                    for src, tgt in self._graph.out_edges(node_id):
                        try:
                            edge_data = self._graph.edges[src, tgt]
                            if edge_data.get("source_port", "") == "false":
                                skipped.add(tgt)
                                # Recursively skip all descendants
                                descendants = list(nx.descendants(self._graph, tgt))
                                skipped.update(descendants)
                        except (KeyError, TypeError):
                            pass

            # Build preview
            preview: dict[str, Any] = {}
            for port_name, raw_data in outputs.items():
                if isinstance(raw_data, str) and len(raw_data) > 500:
                    preview[port_name] = raw_data[:200] + f"...({len(raw_data)} chars)"
                elif isinstance(raw_data, (list, dict)):
                    preview[port_name] = raw_data
                else:
                    preview[port_name] = str(raw_data)[:500]

            if status_callback:
                status_callback(run_id, node_id, "completed", preview)

        return results
