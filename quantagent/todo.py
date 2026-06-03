from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .task_state import load_tasks, save_tasks, task_dir


@dataclass
class TodoItem:
    id: str
    title: str
    status: str
    priority: str
    detail: str


@dataclass
class PlanItem:
    id: str
    title: str
    status: str = "pending"
    detail: str = ""
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


DEFAULT_TODOS = [
    TodoItem("P4", "Real 09:30 tick execution validation", "blocked_waiting_tick_data", "P0", "Use tick_data_request_deep_auc_le_9pct.csv first."),
    TodoItem("P5", "2025 decline decomposition", "done_initial", "P1", "Deep <= -9% remains viable; shallow (-9,-8] degraded."),
    TodoItem("P6", "Account equity and position model", "done_proxy", "P1", "Proxy capacity done; true tick capacity pending."),
    TodoItem("P7", "Experiment runner and result registry", "todo", "P1", "Standardize every experiment as JSON + MD."),
    TodoItem("P8", "Dual model review pipeline", "todo", "P2", "Use primary model for work and review model for audit."),
]


def todo_paths(project: Path) -> tuple[Path, Path]:
    out_dir = project / "AI_协作交接"
    if not out_dir.exists():
        out_dir = project
    return out_dir / "QUANTAGENT_TODO.json", out_dir / "QUANTAGENT_TODO.md"


def load_todos(project: Path) -> list[TodoItem]:
    json_path, _ = todo_paths(project)
    if not json_path.exists():
        return DEFAULT_TODOS
    data = json.loads(json_path.read_text(encoding="utf-8"))
    return [TodoItem(**item) for item in data.get("items", [])]


def save_todos(project: Path, items: list[TodoItem]) -> tuple[Path, Path]:
    json_path, md_path = todo_paths(project)
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "items": [asdict(item) for item in items],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Mako Todo", "", f"- updated_at: {payload['updated_at']}", ""]
    for item in items:
        lines.append(f"- [{item.status}] {item.priority} {item.id}: {item.title} - {item.detail}")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def set_todo_status(project: Path, item_id: str, status: str) -> list[TodoItem]:
    items = load_todos(project)
    found = False
    for item in items:
        if item.id == item_id:
            item.status = status
            found = True
    if not found:
        items.append(TodoItem(item_id, item_id, status, "P2", "Added from CLI."))
    save_todos(project, items)
    return items


def task_plan_path(project: Path, task_id: str) -> Path:
    return task_dir(project) / "plans" / f"{task_id}.json"


def load_task_plan(project: Path, task_id: str) -> list[PlanItem]:
    path = task_plan_path(project, task_id)
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [_plan_item(item) for item in payload.get("items", []) if isinstance(item, dict)]


def save_task_plan(project: Path, task_id: str, items: list[PlanItem], *, note: str = "plan updated") -> Path:
    path = task_plan_path(project, task_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task_id": task_id,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "items": [asdict(item) for item in items],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _mirror_plan_to_task(project, task_id, path, note)
    return path


def set_plan_item(project: Path, task_id: str, item_id: str, status: str, *, title: str = "", detail: str = "") -> list[PlanItem]:
    if status not in {"pending", "in_progress", "completed"}:
        raise ValueError(f"invalid plan status: {status}")
    items = load_task_plan(project, task_id)
    now = datetime.now().isoformat(timespec="seconds")
    for item in items:
        if item.id == item_id:
            item.status = status
            item.title = title or item.title
            item.detail = detail or item.detail
            item.updated_at = now
            break
    else:
        items.append(PlanItem(item_id, title or item_id, status, detail, now))
    save_task_plan(project, task_id, items, note=f"plan item {item_id} -> {status}")
    return items


def render_task_plan(task_id: str, items: list[PlanItem]) -> str:
    if not items:
        return f"# Task Plan {task_id}\n\nNo plan items.\n"
    lines = [f"# Task Plan {task_id}", ""]
    for status in ("in_progress", "pending", "completed"):
        selected = [item for item in items if item.status == status]
        if not selected:
            continue
        lines.append(f"## {status}")
        for item in selected:
            detail = f" - {item.detail}" if item.detail else ""
            lines.append(f"- {item.id}: {item.title}{detail}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _plan_item(payload: dict[str, Any]) -> PlanItem:
    status = str(payload.get("status") or "pending")
    if status not in {"pending", "in_progress", "completed"}:
        status = "pending"
    return PlanItem(
        id=str(payload.get("id") or ""),
        title=str(payload.get("title") or payload.get("id") or ""),
        status=status,
        detail=str(payload.get("detail") or ""),
        updated_at=str(payload.get("updated_at") or datetime.now().isoformat(timespec="seconds")),
    )


def _mirror_plan_to_task(project: Path, task_id: str, path: Path, note: str) -> None:
    tasks = load_tasks(project)
    changed = False
    rel = str(path)
    for task in tasks:
        if task.id != task_id:
            continue
        if rel not in task.evidence:
            task.evidence.append(rel)
        task.updated_at = datetime.now().isoformat(timespec="seconds")
        task.history.append({"status": task.status, "at": task.updated_at, "note": note, "plan_path": rel})
        changed = True
        break
    if changed:
        save_tasks(project, tasks)
