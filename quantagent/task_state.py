from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path
from typing import Any


QUEUED = "queued"
RUNNING = "running"
PASSED = "passed"
FAILED = "failed"
BLOCKED = "blocked"
ABORTED = "aborted"
LOST = "lost"
VALID_STATUSES = {QUEUED, RUNNING, PASSED, FAILED, BLOCKED, ABORTED, LOST}
TERMINAL_STATUSES = {PASSED, FAILED, BLOCKED, ABORTED, LOST}

SCOPE_PROJECT = "project"
SCOPE_SESSION = "session"
SCOPE_SYSTEM = "system"
VALID_SCOPE_KINDS = {SCOPE_PROJECT, SCOPE_SESSION, SCOPE_SYSTEM}

DELIVERY_PENDING = "pending"
DELIVERY_DELIVERED = "delivered"
DELIVERY_SESSION_QUEUED = "session_queued"
DELIVERY_FAILED = "failed"
DELIVERY_PARENT_MISSING = "parent_missing"
DELIVERY_NOT_APPLICABLE = "not_applicable"
DELIVERY_READY_LEGACY = "ready"
VALID_DELIVERY_STATUSES = {
    DELIVERY_PENDING,
    DELIVERY_DELIVERED,
    DELIVERY_SESSION_QUEUED,
    DELIVERY_FAILED,
    DELIVERY_PARENT_MISSING,
    DELIVERY_NOT_APPLICABLE,
    DELIVERY_READY_LEGACY,
}

NOTIFY_DONE_ONLY = "done_only"
NOTIFY_STATE_CHANGES = "state_changes"
NOTIFY_SILENT = "silent"
NOTIFY_ON_COMPLETE_LEGACY = "on_complete"
VALID_NOTIFY_POLICIES = {NOTIFY_DONE_ONLY, NOTIFY_STATE_CHANGES, NOTIFY_SILENT, NOTIFY_ON_COMPLETE_LEGACY}

TERMINAL_SUCCEEDED = "succeeded"
TERMINAL_BLOCKED = "blocked"
VALID_TERMINAL_OUTCOMES = {TERMINAL_SUCCEEDED, TERMINAL_BLOCKED, "success", FAILED, ABORTED, LOST}


@dataclass
class ResearchTask:
    id: str
    title: str
    status: str = QUEUED
    detail: str = ""
    kind: str = "manual"
    requester_session_key: str = ""
    owner_key: str = "local"
    scope_kind: str = SCOPE_PROJECT
    child_session_key: str = ""
    parent_task_id: str = ""
    delivery_status: str = DELIVERY_PENDING
    notify_policy: str = NOTIFY_DONE_ONLY
    terminal_summary: str = ""
    terminal_outcome: str = ""
    cleanup_after: int | None = None
    pid: int | None = None
    command: list[str] = field(default_factory=list)
    output_path: str = ""
    error_path: str = ""
    status_path: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    evidence: list[str] = field(default_factory=list)
    history: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.status = str(self.status or QUEUED)
        self.requester_session_key = str(self.requester_session_key or "")
        self.owner_key = str(self.owner_key or "local")
        self.scope_kind = _valid_or_default(str(self.scope_kind or ""), VALID_SCOPE_KINDS, SCOPE_PROJECT)
        self.child_session_key = str(self.child_session_key or "")
        self.parent_task_id = str(self.parent_task_id or "")
        self.delivery_status = _valid_or_default(str(self.delivery_status or ""), VALID_DELIVERY_STATUSES, DELIVERY_PENDING)
        self.notify_policy = normalize_notify_policy(self.notify_policy)
        self.terminal_summary = str(self.terminal_summary or "")
        self.terminal_outcome = str(self.terminal_outcome or "")
        if self.cleanup_after is not None:
            try:
                self.cleanup_after = int(self.cleanup_after)
            except (TypeError, ValueError):
                self.cleanup_after = None


def task_dir(project: Path) -> Path:
    base = project / "AI_协作交接"
    legacy = project / "quantagent_tasks"
    if legacy.exists():
        return legacy
    return (base if base.exists() else project) / "quantagent_tasks"


def task_file(project: Path) -> Path:
    return task_dir(project) / "tasks.json"


def load_tasks(project: Path) -> list[ResearchTask]:
    path = task_file(project)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [_task_from_payload(item) for item in data.get("tasks", []) if isinstance(item, dict)]


def save_tasks(project: Path, tasks: list[ResearchTask]) -> Path:
    directory = task_dir(project)
    directory.mkdir(parents=True, exist_ok=True)
    path = task_file(project)
    path.write_text(json.dumps({"tasks": [asdict(item) for item in tasks]}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _mirror_tasks_to_runtime_store(project, tasks)
    return path


def next_task_id(tasks: list[ResearchTask]) -> str:
    max_id = 0
    for task in tasks:
        if task.id.startswith("qa-"):
            try:
                max_id = max(max_id, int(task.id.removeprefix("qa-")))
            except ValueError:
                pass
    return f"qa-{max_id + 1:04d}"


def add_task(
    project: Path,
    title: str,
    detail: str = "",
    status: str = QUEUED,
    *,
    requester_session_key: str = "",
    owner_key: str = "local",
    scope_kind: str = SCOPE_PROJECT,
    child_session_key: str = "",
    parent_task_id: str = "",
    delivery_status: str = DELIVERY_PENDING,
    notify_policy: str = NOTIFY_DONE_ONLY,
    terminal_summary: str = "",
    terminal_outcome: str = "",
    cleanup_after: int | None = None,
) -> ResearchTask:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    tasks = load_tasks(project)
    task = ResearchTask(
        id=next_task_id(tasks),
        title=title,
        detail=detail,
        status=status,
        requester_session_key=requester_session_key,
        owner_key=owner_key,
        scope_kind=scope_kind,
        child_session_key=child_session_key,
        parent_task_id=parent_task_id,
        delivery_status=delivery_status,
        notify_policy=notify_policy,
        terminal_summary=terminal_summary,
        terminal_outcome=terminal_outcome,
        cleanup_after=cleanup_after,
    )
    reconcile_task_contract(task, summary=terminal_summary)
    task.history.append({"status": status, "at": task.created_at, "note": "created"})
    tasks.append(task)
    save_tasks(project, tasks)
    return task


def update_task(
    project: Path,
    task_id: str,
    status: str | None = None,
    note: str = "",
    evidence: str | None = None,
    *,
    requester_session_key: str | None = None,
    owner_key: str | None = None,
    scope_kind: str | None = None,
    child_session_key: str | None = None,
    parent_task_id: str | None = None,
    delivery_status: str | None = None,
    notify_policy: str | None = None,
    terminal_summary: str | None = None,
    terminal_outcome: str | None = None,
    cleanup_after: int | None = None,
) -> ResearchTask:
    if status is not None and status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    tasks = load_tasks(project)
    for task in tasks:
        if task.id == task_id:
            if status is not None:
                task.status = status
            if evidence:
                task.evidence.append(evidence)
            if requester_session_key is not None:
                task.requester_session_key = requester_session_key
            if owner_key is not None:
                task.owner_key = owner_key
            if scope_kind is not None:
                task.scope_kind = _valid_or_default(scope_kind, VALID_SCOPE_KINDS, SCOPE_PROJECT)
            if child_session_key is not None:
                task.child_session_key = child_session_key
            if parent_task_id is not None:
                task.parent_task_id = parent_task_id
            if delivery_status is not None:
                task.delivery_status = _valid_or_default(delivery_status, VALID_DELIVERY_STATUSES, DELIVERY_PENDING)
            if notify_policy is not None:
                task.notify_policy = normalize_notify_policy(notify_policy)
            if terminal_summary is not None:
                task.terminal_summary = terminal_summary
            if terminal_outcome is not None:
                task.terminal_outcome = terminal_outcome
            if cleanup_after is not None:
                task.cleanup_after = cleanup_after
            task.updated_at = datetime.now().isoformat(timespec="seconds")
            reconcile_task_contract(task, summary=terminal_summary if terminal_summary is not None else note)
            task.history.append({"status": task.status, "at": task.updated_at, "note": note, "evidence": evidence})
            save_tasks(project, tasks)
            return task
    raise KeyError(f"task not found: {task_id}")


def render_tasks(tasks: list[ResearchTask]) -> str:
    if not tasks:
        return "No Mako tasks.\n"
    lines = ["# Mako Tasks", ""]
    for task in tasks:
        evidence = f" evidence={len(task.evidence)}" if task.evidence else ""
        detail = f" - {task.detail}" if task.detail else ""
        lines.append(f"- [{task.status}] {task.id}: {task.title}{detail}{evidence}")
    return "\n".join(lines) + "\n"


def normalize_notify_policy(value: str | None) -> str:
    policy = str(value or "").strip()
    if policy == NOTIFY_ON_COMPLETE_LEGACY:
        return NOTIFY_DONE_ONLY
    return policy if policy in VALID_NOTIFY_POLICIES else NOTIFY_DONE_ONLY


def terminal_outcome_for_status(status: str) -> str:
    if status == PASSED:
        return TERMINAL_SUCCEEDED
    if status in {FAILED, BLOCKED, ABORTED, LOST}:
        return TERMINAL_BLOCKED
    return ""


def default_delivery_status(task: ResearchTask) -> str:
    if task.notify_policy == NOTIFY_SILENT:
        return DELIVERY_NOT_APPLICABLE
    if task.status not in TERMINAL_STATUSES:
        return DELIVERY_PENDING
    if task.child_session_key or task.requester_session_key or task.parent_task_id:
        return DELIVERY_PENDING
    return DELIVERY_NOT_APPLICABLE


def reconcile_task_contract(
    task: ResearchTask,
    *,
    summary: str = "",
    delivery_status: str | None = None,
) -> ResearchTask:
    task.owner_key = str(task.owner_key or "local")
    task.scope_kind = _valid_or_default(task.scope_kind, VALID_SCOPE_KINDS, SCOPE_PROJECT)
    task.notify_policy = normalize_notify_policy(task.notify_policy)
    if delivery_status is not None:
        task.delivery_status = _valid_or_default(delivery_status, VALID_DELIVERY_STATUSES, DELIVERY_PENDING)
    elif task.delivery_status in {"", DELIVERY_PENDING, DELIVERY_READY_LEGACY}:
        task.delivery_status = default_delivery_status(task)
    if task.status in TERMINAL_STATUSES:
        if summary and not task.terminal_summary:
            task.terminal_summary = summary
        if not task.terminal_outcome:
            task.terminal_outcome = terminal_outcome_for_status(task.status)
    else:
        task.terminal_summary = ""
        task.terminal_outcome = ""
    return task


def mark_task_delivered(task: ResearchTask, *, at: str | None = None, note: str = "delivered") -> ResearchTask:
    task.delivery_status = DELIVERY_DELIVERED
    task.updated_at = at or datetime.now().isoformat(timespec="seconds")
    task.history.append({"status": task.status, "at": task.updated_at, "note": note, "delivery_status": DELIVERY_DELIVERED})
    return task


def _mirror_tasks_to_runtime_store(project: Path, tasks: list[ResearchTask]) -> None:
    from .runtime_store import record_task_run

    for task in tasks:
        record_task_run(
            project,
            task,
            owner_key=task.owner_key,
            scope_kind=task.scope_kind,
            requester_session_key=task.requester_session_key or None,
            child_session_key=task.child_session_key or None,
            parent_task_id=task.parent_task_id or None,
            notify_policy=task.notify_policy,
            terminal_summary=task.terminal_summary or None,
            cleanup_after=task.cleanup_after,
        )


def _task_from_payload(item: dict[str, Any]) -> ResearchTask:
    payload = dict(item)
    aliases = {
        "taskId": "id",
        "task_id": "id",
        "requesterSessionKey": "requester_session_key",
        "ownerKey": "owner_key",
        "scopeKind": "scope_kind",
        "childSessionKey": "child_session_key",
        "parentTaskId": "parent_task_id",
        "deliveryStatus": "delivery_status",
        "notifyPolicy": "notify_policy",
        "terminalSummary": "terminal_summary",
        "terminalOutcome": "terminal_outcome",
        "cleanupAfter": "cleanup_after",
        "createdAt": "created_at",
        "updatedAt": "updated_at",
        "outputPath": "output_path",
        "errorPath": "error_path",
        "statusPath": "status_path",
    }
    for source, target in aliases.items():
        if source in payload and target not in payload:
            payload[target] = payload[source]
    if "title" not in payload:
        payload["title"] = str(payload.get("label") or payload.get("task") or payload.get("id") or "task")
    if "id" not in payload:
        payload["id"] = str(payload.get("taskId") or payload.get("task_id") or payload["title"])
    names = {item.name for item in fields(ResearchTask)}
    task = ResearchTask(**{key: value for key, value in payload.items() if key in names})
    if task.status in TERMINAL_STATUSES and not task.terminal_outcome:
        reconcile_task_contract(task, summary=task.terminal_summary)
    return task


def _valid_or_default(value: str, allowed: set[str], default: str) -> str:
    return value if value in allowed else default
