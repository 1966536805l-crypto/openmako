from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .runtime_store import (
    list_budget_reservations,
    list_compact_events,
    list_approval_requests,
    list_model_calls,
    list_runtime_sessions,
    list_task_runs,
    list_tool_invocations,
    load_runtime_query_events,
    runtime_db_path,
    search_messages,
)


@dataclass(frozen=True)
class RuntimeLedgerSnapshot:
    project: str
    db_path: str
    sessions: list[dict[str, Any]]
    task_runs: list[dict[str, Any]]
    approvals: list[dict[str, Any]]
    tool_invocations: list[dict[str, Any]]
    model_calls: list[dict[str, Any]]
    compact_events: list[dict[str, Any]]
    budget_reservations: list[dict[str, Any]]
    query_events: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "sessions": len(self.sessions),
            "task_runs": len(self.task_runs),
            "approvals": len(self.approvals),
            "tool_invocations": len(self.tool_invocations),
            "model_calls": len(self.model_calls),
            "compact_events": len(self.compact_events),
            "budget_reservations": len(self.budget_reservations),
            "query_events": len(self.query_events),
        }


def build_runtime_ledger_snapshot(project: str | Path, *, limit: int = 20) -> RuntimeLedgerSnapshot:
    project_path = Path(project).expanduser().resolve(strict=False)
    return RuntimeLedgerSnapshot(
        project=str(project_path),
        db_path=str(runtime_db_path(project_path)),
        sessions=[asdict(item) for item in list_runtime_sessions(project_path, limit=limit)],
        task_runs=[asdict(item) for item in list_task_runs(project_path, limit=limit)],
        approvals=[asdict(item) for item in list_approval_requests(project_path, limit=limit)],
        tool_invocations=[asdict(item) for item in list_tool_invocations(project_path, limit=limit)],
        model_calls=[asdict(item) for item in list_model_calls(project_path, limit=limit)],
        compact_events=[asdict(item) for item in list_compact_events(project_path, limit=limit)],
        budget_reservations=[asdict(item) for item in list_budget_reservations(project_path, limit=limit)],
        query_events=load_runtime_query_events(project_path, limit=limit),
    )


def search_runtime_ledger(project: str | Path, query: str, *, limit: int = 20) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve(strict=False)
    return {
        "project": str(project_path),
        "query": query,
        "messages": search_messages(project_path, query, limit=limit),
    }


def render_runtime_ledger(snapshot: RuntimeLedgerSnapshot) -> str:
    counts = snapshot.counts
    lines = [
        "# Runtime Ledger",
        "",
        f"- project: {snapshot.project}",
        f"- db_path: {snapshot.db_path}",
        f"- sessions: {counts['sessions']}",
        f"- task_runs: {counts['task_runs']}",
        f"- approvals: {counts['approvals']}",
        f"- tool_invocations: {counts['tool_invocations']}",
        f"- model_calls: {counts['model_calls']}",
        f"- compact_events: {counts['compact_events']}",
        f"- budget_reservations: {counts['budget_reservations']}",
        f"- query_events: {counts['query_events']}",
        "",
        "## Sessions",
        "",
    ]
    if not snapshot.sessions:
        lines.append("- none")
    for item in snapshot.sessions:
        lines.append(
            f"- {item.get('id')} source={item.get('source')} messages={item.get('message_count')} "
            f"tools={item.get('tool_call_count')} title={item.get('title')}"
        )
    lines.extend(["", "## Task Runs", ""])
    if not snapshot.task_runs:
        lines.append("- none")
    for item in snapshot.task_runs:
        lineage = _lineage(item)
        lines.append(
            f"- {item.get('task_id')} [{item.get('status')}] runtime={item.get('runtime')} "
            f"delivery={item.get('delivery_status')} outcome={item.get('terminal_outcome') or '-'}{lineage}: {item.get('task')}"
        )
    lines.extend(["", "## Approvals", ""])
    if not snapshot.approvals:
        lines.append("- none")
    for item in snapshot.approvals:
        lines.append(f"- {item.get('approval_id')} [{item.get('status')}] {item.get('tool')} action={item.get('action')}: {item.get('reason')}")
    lines.extend(["", "## Tool Invocations", ""])
    if not snapshot.tool_invocations:
        lines.append("- none")
    for item in snapshot.tool_invocations:
        lines.append(
            f"- {item.get('invocation_id')} [{item.get('status')}] {item.get('tool')} "
            f"duration_ms={item.get('duration_ms') or '-'} approval={item.get('approval_id') or '-'}: {item.get('summary')}"
        )
    lines.extend(["", "## Model Calls", ""])
    if not snapshot.model_calls:
        lines.append("- none")
    for item in snapshot.model_calls:
        lines.append(
            f"- {item.get('query_id') or '-'} {item.get('model')} ok={str(bool(item.get('ok'))).lower()} "
            f"task={item.get('task_id') or '-'} agent={item.get('agent_id') or '-'} "
            f"input={item.get('input_tokens')} output={item.get('output_tokens')} "
            f"reasoning={item.get('reasoning_tokens')} pressure={item.get('pressure_state') or '-'}"
        )
    lines.extend(["", "## Compact Events", ""])
    if not snapshot.compact_events:
        lines.append("- none")
    for item in snapshot.compact_events:
        lines.append(
            f"- {item.get('query_id') or item.get('session_id') or '-'} {item.get('mode')} "
            f"applied={str(bool(item.get('applied'))).lower()} saved={item.get('saved_estimated_tokens')} "
            f"reason={item.get('reason') or '-'}"
        )
    lines.extend(["", "## Budget Reservations", ""])
    if not snapshot.budget_reservations:
        lines.append("- none")
    else:
        summary = _budget_reservation_summary(snapshot.budget_reservations)
        lines.append(
            f"- summary: active={summary.get('active', 0)} committed={summary.get('committed', 0)} "
            f"released={summary.get('released', 0)} expired={summary.get('expired', 0)} "
            f"active_tokens={summary.get('active_tokens', 0)} active_cost={_money(summary.get('active_cost'))}"
        )
    now_ms = int(time.time() * 1000)
    for item in snapshot.budget_reservations:
        parts = [
            f"- {item.get('reservation_id')} [{item.get('status')}]",
            f"session={item.get('session_id')}",
            f"query={item.get('query_id') or '-'}",
            f"task={item.get('task_id') or '-'}",
            f"agent={item.get('agent_id') or '-'}",
            f"model={item.get('model') or '-'}",
            f"provider={item.get('provider') or '-'}",
            f"est_tokens={item.get('estimated_tokens')}",
            f"est_cost={_money(item.get('estimated_cost_usd'))}",
            f"ttl={_ttl(item, now_ms)}",
        ]
        if item.get("actual_tokens") or item.get("status") == "committed":
            parts.append(f"actual_tokens={item.get('actual_tokens') or 0}")
        if item.get("actual_cost_usd") is not None:
            parts.append(f"actual_cost={_money(item.get('actual_cost_usd'))}")
        if item.get("model_call_id"):
            parts.append(f"model_call={item.get('model_call_id')}")
        if item.get("release_reason"):
            parts.append(f"reason={item.get('release_reason')}")
        if item.get("completed_at"):
            parts.append(f"completed_at={item.get('completed_at')}")
        lines.append(" ".join(parts))
    lines.extend(["", "## Query Events", ""])
    if not snapshot.query_events:
        lines.append("- none")
    for item in snapshot.query_events:
        ok = item.get("ok")
        ok_text = "-" if ok is None else str(bool(ok)).lower()
        lines.append(f"- {item.get('query_id')} {item.get('kind')} ok={ok_text} step={item.get('step') or '-'}: {item.get('summary')}")
    return "\n".join(lines).rstrip() + "\n"


def render_runtime_search(result: dict[str, Any]) -> str:
    lines = [
        "# Runtime Search",
        "",
        f"- project: {result.get('project')}",
        f"- query: {result.get('query')}",
        "",
        "## Messages",
        "",
    ]
    messages = result.get("messages") or []
    if not messages:
        lines.append("- none")
    for item in messages:
        content = " ".join(str(item.get("content") or "").split())
        if len(content) > 180:
            content = content[:177] + "..."
        lines.append(f"- {item.get('session_id')} {item.get('role')} tool={item.get('tool_name') or '-'}: {content}")
    return "\n".join(lines).rstrip() + "\n"


def render_runtime_json(value: RuntimeLedgerSnapshot | dict[str, Any]) -> str:
    payload = value.to_dict() if hasattr(value, "to_dict") else value
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _lineage(item: dict[str, Any]) -> str:
    parts = []
    if item.get("parent_task_id"):
        parts.append(f"parent={item.get('parent_task_id')}")
    if item.get("child_session_key"):
        parts.append(f"child_session={item.get('child_session_key')}")
    if item.get("agent_id"):
        parts.append(f"agent={item.get('agent_id')}")
    return " " + " ".join(parts) if parts else ""


def _budget_reservation_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"active_tokens": 0, "active_cost": 0.0}
    for item in items:
        status = str(item.get("status") or "unknown")
        summary[status] = int(summary.get(status, 0)) + 1
        if status == "active":
            summary["active_tokens"] = int(summary["active_tokens"]) + int(item.get("estimated_tokens") or 0)
            summary["active_cost"] = float(summary["active_cost"]) + float(item.get("estimated_cost_usd") or 0.0)
    return summary


def _ttl(item: dict[str, Any], now_ms: int) -> str:
    if item.get("status") != "active":
        return "-"
    try:
        remaining_ms = int(item.get("expires_at") or 0) - now_ms
    except (TypeError, ValueError):
        return "-"
    if remaining_ms <= 0:
        return "expired"
    return f"{(remaining_ms + 999) // 1000}s"


def _money(value: Any) -> str:
    if value is None or value == "":
        return "-"
    try:
        text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)
    return text or "0"
