from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .approvals import PENDING
from .chat_ui import choose_context_decision
from .checkpoints import list_checkpoints
from .context_pack import build_context_pack
from .query_runtime import load_query_events
from .runtime_store import TaskRunRecord, ToolInvocationRecord, list_approval_requests, list_task_runs, list_tool_invocations
from .sessions import latest_session
from .worktree_isolation import list_isolation_reviews


@dataclass(frozen=True)
class UXContextStatus:
    mode: str
    token_budget: int
    estimated_tokens: int = 0
    char_budget: int = 0
    chars_used: int = 0
    source_count: int = 0
    sections: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    task: str = ""
    error: str = ""


@dataclass(frozen=True)
class UXSessionStatus:
    session_id: str
    title: str
    updated_at: str
    message_count: int
    summary_preview: str = ""
    last_message_preview: str = ""


@dataclass(frozen=True)
class UXApprovalStatus:
    approval_id: str
    tool: str
    action: str
    status: str
    reason: str
    expires_at: int | None = None


@dataclass(frozen=True)
class UXToolStatus:
    invocation_id: str
    tool: str
    status: str
    summary: str
    approval_id: str = ""
    checkpoint_id: str = ""
    error_kind: str = ""
    duration_ms: int | None = None


@dataclass(frozen=True)
class UXReviewStatus:
    review_id: str
    worktree_id: str
    status: str
    changed: int
    new: int
    deleted: int


@dataclass(frozen=True)
class UXCheckpointStatus:
    checkpoint_id: str
    files: int
    reason: str = ""
    task_id: str = ""
    plan_id: str = ""


@dataclass(frozen=True)
class UXEventStatus:
    kind: str
    summary: str
    name: str = ""
    ok: bool | None = None


@dataclass(frozen=True)
class UXActiveTaskStatus:
    task_id: str
    task: str
    status: str
    runtime: str
    active_tool: str = ""
    active_tool_status: str = ""
    next_approval: str = ""
    latest_checkpoint: str = ""
    changed_files: int = 0
    last_artifact: str = ""
    blocker: str = ""
    progress_summary: str = ""


@dataclass(frozen=True)
class UXStatus:
    project: str
    context: UXContextStatus
    session: UXSessionStatus | None = None
    active_tasks: list[UXActiveTaskStatus] = field(default_factory=list)
    approvals: list[UXApprovalStatus] = field(default_factory=list)
    tools: list[UXToolStatus] = field(default_factory=list)
    reviews: list[UXReviewStatus] = field(default_factory=list)
    checkpoints: list[UXCheckpointStatus] = field(default_factory=list)
    events: list[UXEventStatus] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_ux_status(
    project: str | Path,
    *,
    task: str = "",
    limit: int = 5,
    include_context_pack: bool = True,
) -> UXStatus:
    project_path = Path(project).expanduser().resolve(strict=False)
    safe_limit = max(1, limit)
    return UXStatus(
        project=str(project_path),
        context=_context_status(project_path, task=task, include_pack=include_context_pack),
        session=_session_status(project_path),
        active_tasks=_active_task_statuses(project_path, safe_limit),
        approvals=_approval_statuses(project_path, safe_limit),
        tools=_tool_statuses(project_path, safe_limit),
        reviews=_review_statuses(project_path, safe_limit),
        checkpoints=_checkpoint_statuses(project_path, safe_limit),
        events=_event_statuses(project_path, safe_limit),
    )


def render_ux_status(status: UXStatus) -> str:
    lines = [
        "# Mako UX Status",
        "",
        f"- project: {status.project}",
        "",
        "## Context",
        "",
        _render_context(status.context),
        "",
        "## Session",
        "",
        _render_session(status.session),
        "",
        "## Active Tasks",
        "",
    ]
    lines.extend(_render_active_tasks(status.active_tasks))
    lines.extend([
        "",
        "## Approvals",
        "",
    ])
    lines.extend(_render_approvals(status.approvals))
    lines.extend(["", "## Tool Calls", ""])
    lines.extend(_render_tools(status.tools))
    lines.extend(["", "## Diff Reviews", ""])
    lines.extend(_render_reviews(status.reviews))
    lines.extend(["", "## Checkpoints", ""])
    lines.extend(_render_checkpoints(status.checkpoints))
    lines.extend(["", "## Query Events", ""])
    lines.extend(_render_events(status.events))
    return "\n".join(lines).rstrip() + "\n"


def render_ux_status_json(status: UXStatus) -> str:
    return json.dumps(status.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _context_status(project: Path, *, task: str, include_pack: bool) -> UXContextStatus:
    decision = choose_context_decision(task or "status")
    if not include_pack:
        return UXContextStatus(
            mode=decision.mode,
            token_budget=decision.token_budget,
            task=task,
            reasons=list(decision.reasons),
        )
    try:
        pack = build_context_pack(project, task=task or "status", token_budget=decision.token_budget)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:171", exc)
        return UXContextStatus(
            mode=decision.mode,
            token_budget=decision.token_budget,
            task=task,
            reasons=list(decision.reasons),
            error=f"{type(exc).__name__}: {exc}",
        )
    return UXContextStatus(
        mode=decision.mode,
        token_budget=pack.token_budget,
        estimated_tokens=pack.estimated_tokens,
        char_budget=pack.char_budget,
        chars_used=pack.chars_used,
        source_count=len(pack.sources),
        sections=sorted(set(pack.sections)),
        reasons=list(decision.reasons),
        task=task,
    )


def _session_status(project: Path) -> UXSessionStatus | None:
    record = latest_session(project)
    if record is None:
        return None
    last = record.messages[-1] if record.messages else None
    return UXSessionStatus(
        session_id=record.session_id,
        title=record.title,
        updated_at=record.updated_at,
        message_count=len(record.messages),
        summary_preview=_preview(record.summary),
        last_message_preview=_preview(last.content if last else ""),
    )


def _approval_statuses(project: Path, limit: int) -> list[UXApprovalStatus]:
    rows = list_approval_requests(project, status=PENDING, limit=limit)
    return [
        UXApprovalStatus(
            approval_id=row.approval_id,
            tool=row.tool,
            action=row.action,
            status=row.status,
            reason=_preview(row.reason, 120),
            expires_at=row.expires_at,
        )
        for row in rows
    ]


def _tool_statuses(project: Path, limit: int) -> list[UXToolStatus]:
    rows = list_tool_invocations(project, limit=limit)
    return [
        UXToolStatus(
            invocation_id=row.invocation_id,
            tool=row.tool,
            status=row.status,
            summary=_preview(row.summary, 140),
            approval_id=row.approval_id or "",
            checkpoint_id=row.checkpoint_id or "",
            error_kind=row.error_kind,
            duration_ms=row.duration_ms,
        )
        for row in rows
    ]


def _review_statuses(project: Path, limit: int) -> list[UXReviewStatus]:
    return [
        UXReviewStatus(
            review_id=row.review_id,
            worktree_id=row.worktree_id,
            status=row.status,
            changed=len(row.changed_paths),
            new=len(row.new_paths),
            deleted=len(row.deleted_paths),
        )
        for row in list_isolation_reviews(project, limit=limit)
    ]


def _checkpoint_statuses(project: Path, limit: int) -> list[UXCheckpointStatus]:
    return [
        UXCheckpointStatus(
            checkpoint_id=row.checkpoint_id,
            files=len(row.files),
            reason=_preview(row.reason, 120),
            task_id=row.task_id,
            plan_id=row.plan_id,
        )
        for row in list_checkpoints(project, limit=limit)
    ]


def _event_statuses(project: Path, limit: int) -> list[UXEventStatus]:
    return [
        UXEventStatus(
            kind=row.kind,
            summary=_preview(row.summary, 140),
            name=row.name,
            ok=row.ok,
        )
        for row in load_query_events(project)[-limit:]
    ]


def _active_task_statuses(project: Path, limit: int) -> list[UXActiveTaskStatus]:
    tasks = list_task_runs(project, limit=limit)
    if not tasks:
        return []
    tools = list_tool_invocations(project, limit=max(limit * 5, 10))
    approvals = _approval_statuses(project, max(limit, 5))
    checkpoints = _checkpoint_statuses(project, max(limit * 5, 10))
    reviews = _review_statuses(project, max(limit * 3, 6))
    rows: list[UXActiveTaskStatus] = []
    for task in tasks:
        matched_tools = [tool for tool in tools if _tool_matches_task(tool, task)]
        latest_tool = matched_tools[0] if matched_tools else (tools[0] if task.status == "running" and tools else None)
        task_checkpoints = [checkpoint for checkpoint in checkpoints if checkpoint.task_id == task.task_id]
        latest_checkpoint = task_checkpoints[0] if task_checkpoints else None
        next_approval = ""
        if latest_tool and latest_tool.approval_id:
            next_approval = latest_tool.approval_id
        elif task.status in {"queued", "running", "blocked"} and approvals:
            next_approval = approvals[0].approval_id
        changed_files = sum(item.changed + item.new + item.deleted for item in reviews if item.status not in {"applied", "discarded"})
        blocker = _active_task_blocker(task, latest_tool, next_approval)
        rows.append(
            UXActiveTaskStatus(
                task_id=task.task_id,
                task=_preview(task.task, 120),
                status=task.status,
                runtime=task.runtime,
                active_tool=latest_tool.tool if latest_tool else "",
                active_tool_status=latest_tool.status if latest_tool else "",
                next_approval=next_approval,
                latest_checkpoint=latest_checkpoint.checkpoint_id if latest_checkpoint else "",
                changed_files=changed_files,
                last_artifact=_last_artifact(latest_tool, latest_checkpoint),
                blocker=blocker,
                progress_summary=_preview(task.progress_summary or task.terminal_summary or task.error or "", 160),
            )
        )
    return rows


def _tool_matches_task(tool: ToolInvocationRecord, task: TaskRunRecord) -> bool:
    keys = {task.task_id, task.run_id or "", task.child_session_key or "", task.requester_session_key or ""}
    keys.discard("")
    return bool(keys and (tool.query_id in keys or tool.session_id in keys))


def _active_task_blocker(task: TaskRunRecord, tool: ToolInvocationRecord | None, next_approval: str) -> str:
    if next_approval:
        return "approval_pending"
    if task.status == "blocked":
        return _preview(task.error or task.progress_summary or "blocked", 80)
    if task.status == "lost":
        return "lost"
    if tool and tool.status not in {"ok", "passed", "completed", "success"}:
        return tool.error_kind or tool.status
    return ""


def _last_artifact(tool: ToolInvocationRecord | None, checkpoint: UXCheckpointStatus | None) -> str:
    if checkpoint:
        return f"checkpoint:{checkpoint.checkpoint_id}"
    if tool and tool.checkpoint_id:
        return f"checkpoint:{tool.checkpoint_id}"
    if tool and tool.output_preview:
        return _preview(tool.output_preview, 120)
    return ""


def _render_context(context: UXContextStatus) -> str:
    ratio = "n/a"
    if context.token_budget:
        ratio = f"{context.estimated_tokens}/{context.token_budget}"
    lines = [
        f"- mode: {context.mode}",
        f"- tokens: {ratio}",
        f"- chars: {context.chars_used}/{context.char_budget}" if context.char_budget else "- chars: n/a",
        f"- sources: {context.source_count}",
    ]
    if context.sections:
        lines.append(f"- sections: {', '.join(context.sections[:8])}")
    if context.reasons:
        lines.append(f"- reasons: {', '.join(context.reasons)}")
    if context.error:
        lines.append(f"- error: {context.error}")
    return "\n".join(lines)


def _render_session(session: UXSessionStatus | None) -> str:
    if session is None:
        return "- none"
    lines = [
        f"- {session.session_id}: {session.title}",
        f"- updated: {session.updated_at}",
        f"- messages: {session.message_count}",
    ]
    if session.summary_preview:
        lines.append(f"- summary: {session.summary_preview}")
    if session.last_message_preview:
        lines.append(f"- last: {session.last_message_preview}")
    return "\n".join(lines)


def _render_active_tasks(rows: list[UXActiveTaskStatus]) -> list[str]:
    if not rows:
        return ["- none"]
    lines: list[str] = []
    for row in rows:
        parts = [f"- [{row.status}] {row.task_id}: {row.task}"]
        if row.active_tool:
            parts.append(f"tool={row.active_tool}/{row.active_tool_status or '-'}")
        if row.next_approval:
            parts.append(f"approval={row.next_approval}")
        if row.latest_checkpoint:
            parts.append(f"checkpoint={row.latest_checkpoint}")
        if row.changed_files:
            parts.append(f"changed_files={row.changed_files}")
        if row.blocker:
            parts.append(f"blocker={row.blocker}")
        if row.progress_summary:
            parts.append(f"- {row.progress_summary}")
        lines.append(" ".join(parts))
    return lines


def _render_approvals(rows: list[UXApprovalStatus]) -> list[str]:
    if not rows:
        return ["- none pending"]
    return [
        f"- [{row.status}] {row.approval_id}: {row.tool} action={row.action}"
        + (f" expires_at={row.expires_at}" if row.expires_at else "")
        + (f" - {row.reason}" if row.reason else "")
        for row in rows
    ]


def _render_tools(rows: list[UXToolStatus]) -> list[str]:
    if not rows:
        return ["- none"]
    lines: list[str] = []
    for row in rows:
        parts = [f"- [{row.status}] {row.invocation_id}: {row.tool}"]
        if row.duration_ms is not None:
            parts.append(f"{row.duration_ms}ms")
        if row.approval_id:
            parts.append(f"approval={row.approval_id}")
        if row.checkpoint_id:
            parts.append(f"checkpoint={row.checkpoint_id}")
        if row.error_kind:
            parts.append(f"error={row.error_kind}")
        if row.summary:
            parts.append(f"- {row.summary}")
        lines.append(" ".join(parts))
    return lines


def _render_reviews(rows: list[UXReviewStatus]) -> list[str]:
    if not rows:
        return ["- none"]
    return [
        f"- [{row.status}] {row.review_id}: worktree={row.worktree_id} changed={row.changed} new={row.new} deleted={row.deleted}"
        for row in rows
    ]


def _render_checkpoints(rows: list[UXCheckpointStatus]) -> list[str]:
    if not rows:
        return ["- none"]
    return [
        f"- {row.checkpoint_id}: files={row.files} task={row.task_id or '-'} plan={row.plan_id or '-'}"
        + (f" - {row.reason}" if row.reason else "")
        for row in rows
    ]


def _render_events(rows: list[UXEventStatus]) -> list[str]:
    if not rows:
        return ["- none"]
    lines: list[str] = []
    for row in rows:
        status = "ok" if row.ok is True else "failed" if row.ok is False else "pending"
        name = f" {row.name}" if row.name else ""
        lines.append(f"- {row.kind}{name} [{status}]: {row.summary}")
    return lines


def _preview(text: str, limit: int = 180) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"
