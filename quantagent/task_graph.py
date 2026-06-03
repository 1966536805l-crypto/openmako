from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .event_log import RuntimeEvent, read_runtime_events
from .runtime_store import TaskRunRecord, list_task_runs


@dataclass(frozen=True)
class TaskGraphNode:
    node_id: str
    label: str
    kind: str
    status: str
    parent_id: str = ""
    progress_summary: str = ""
    terminal_outcome: str = ""
    artifacts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifacts"] = list(self.artifacts)
        return payload


@dataclass(frozen=True)
class TaskGraphEdge:
    source: str
    target: str
    relation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TaskGraph:
    nodes: tuple[TaskGraphNode, ...] = field(default_factory=tuple)
    edges: tuple[TaskGraphEdge, ...] = field(default_factory=tuple)
    events: tuple[RuntimeEvent, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "events": [event.to_dict() for event in self.events],
        }


def build_task_graph(project: str | Path, *, limit: int = 100) -> TaskGraph:
    project_path = Path(project).expanduser().resolve(strict=False)
    runs = list_task_runs(project_path, limit=limit)
    events = read_runtime_events(project_path, limit=limit)
    nodes = [_node_from_run(run) for run in runs]
    known = {node.node_id for node in nodes}
    edges: list[TaskGraphEdge] = []
    for run in runs:
        if run.parent_task_id and run.parent_task_id in known:
            edges.append(TaskGraphEdge(run.parent_task_id, run.task_id, "parent_task"))
        if run.requester_session_key:
            session_node = f"session:{run.requester_session_key}"
            if session_node not in known:
                nodes.append(
                    TaskGraphNode(
                        node_id=session_node,
                        label=run.requester_session_key,
                        kind="session",
                        status="observed",
                    )
                )
                known.add(session_node)
            edges.append(TaskGraphEdge(session_node, run.task_id, "requested"))
    for event in events:
        if event.task_id and event.task_id in known:
            edges.append(TaskGraphEdge(event.task_id, event.event_id, "emitted"))
            nodes.append(
                TaskGraphNode(
                    node_id=event.event_id,
                    label=event.summary,
                    kind=f"event:{event.kind}",
                    status=event.status,
                    parent_id=event.task_id,
                    artifacts=event.artifacts,
                )
            )
    return TaskGraph(nodes=tuple(nodes), edges=tuple(edges), events=tuple(events))


def render_task_graph(graph: TaskGraph) -> str:
    if not graph.nodes:
        return "No task graph nodes.\n"
    lines = ["# Mako Task Graph", "", "## Nodes", ""]
    for node in graph.nodes:
        parent = f" parent={node.parent_id}" if node.parent_id else ""
        outcome = f" outcome={node.terminal_outcome}" if node.terminal_outcome else ""
        lines.append(f"- [{node.status}] {node.node_id} ({node.kind}){parent}{outcome}: {node.label}")
        if node.progress_summary and node.progress_summary != node.label:
            lines.append(f"  progress: {node.progress_summary}")
    if graph.edges:
        lines.extend(["", "## Edges", ""])
        for edge in graph.edges:
            lines.append(f"- {edge.source} -[{edge.relation}]-> {edge.target}")
    return "\n".join(lines) + "\n"


def _node_from_run(run: TaskRunRecord) -> TaskGraphNode:
    return TaskGraphNode(
        node_id=run.task_id,
        label=run.label or run.task,
        kind=run.task_kind,
        status=run.status,
        parent_id=run.parent_task_id or "",
        progress_summary=run.progress_summary or "",
        terminal_outcome=run.terminal_outcome or "",
    )
