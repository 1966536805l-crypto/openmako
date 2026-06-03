from __future__ import annotations

import contextlib
import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from . import runtime_store
from .desktop_control import desktop_dir
from .desktop_intelligence import DesktopDaemonResult, run_desktop_daemon
from .query_runtime import QueryRuntime
from .trajectory import record_action, record_observation


NIGHT_STATUSES = frozenset({"queued", "running", "paused", "blocked", "done", "failed", "stopped"})
TERMINAL_STATUSES = frozenset({"done", "failed", "stopped"})
QUEUE_VERSION = 1
DEFAULT_RUNTIME_QUEUE = "desktop_night_daemon"
WORKER_ID_PREFIX = "desktop-night-daemon:"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass
class NightTask:
    id: str
    project: str
    goal: str
    status: str = "queued"
    priority: int = 100
    attempts: int = 0
    max_attempts: int = 1
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    started_at: str = ""
    finished_at: str = ""
    paused_reason: str = ""
    summary: str = ""
    result_status: str = ""
    result_path: str = ""
    query_events_path: str = ""
    trajectory_path: str = ""
    state_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    daemon_options: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = _coerce_status(self.status)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


@dataclass(frozen=True)
class NightDaemonResult:
    ok: bool
    status: str
    summary: str
    tasks: tuple[NightTask, ...]
    queue_path: str
    lock_path: str
    stop_file: str
    state_path: str
    query_events_path: str
    trajectory_path: str
    active_task_id: str = ""
    processed: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "active_task_id": self.active_task_id,
            "processed": self.processed,
            "queue_path": self.queue_path,
            "lock_path": self.lock_path,
            "stop_file": self.stop_file,
            "state_path": self.state_path,
            "query_events_path": self.query_events_path,
            "trajectory_path": self.trajectory_path,
            "tasks": [task.to_payload() for task in self.tasks],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


def night_daemon_dir(project: str | Path) -> Path:
    directory = desktop_dir(Path(project).expanduser().resolve(strict=False)) / "night_daemon"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def night_queue_path(project: str | Path) -> Path:
    return night_daemon_dir(project) / "queue.json"


def night_lock_path(project: str | Path) -> Path:
    return night_daemon_dir(project) / "queue.lock"


def night_stop_file(project: str | Path) -> Path:
    return night_daemon_dir(project) / "STOP"


def night_query_events_path(project: str | Path) -> Path:
    return night_daemon_dir(project) / "query_events.jsonl"


def night_trajectory_path(project: str | Path) -> Path:
    return night_daemon_dir(project) / "trajectory.jsonl"


def night_state_path(project: str | Path) -> Path:
    return night_daemon_dir(project) / "latest_state.json"


def enqueue_night_task(
    project: str | Path,
    goal: str,
    *,
    task_id: str | None = None,
    priority: int = 100,
    max_attempts: int = 1,
    metadata: dict[str, Any] | None = None,
    **daemon_options: Any,
) -> NightTask:
    project_path = Path(project).expanduser().resolve(strict=False)
    text = " ".join(goal.strip().split())
    if not text:
        raise ValueError("night task goal is required")

    task = NightTask(
        id=task_id or _new_task_id(),
        project=str(project_path),
        goal=text,
        priority=int(priority),
        max_attempts=max(1, int(max_attempts)),
        metadata=dict(metadata or {}),
        daemon_options=_clean_options(daemon_options),
    )
    with _locked_queue(project_path) as tasks:
        if any(existing.id == task.id for existing in tasks):
            raise ValueError(f"night task already exists: {task.id}")
        tasks.append(task)
    _write_state(project_path, "queued", f"queued night task {task.id}", active_task_id=task.id)
    return task


def enqueue_night_daemon(project: str | Path, goal: str, **kwargs: Any) -> NightTask:
    return enqueue_night_task(project, goal, **kwargs)


def load_night_tasks(project: str | Path) -> tuple[NightTask, ...]:
    return tuple(_read_tasks(night_queue_path(project)))


def save_night_tasks(project: str | Path, tasks: Iterable[NightTask]) -> tuple[NightTask, ...]:
    project_path = Path(project).expanduser().resolve(strict=False)
    normalized = tuple(_sorted_tasks([_normalize_task(task, project_path) for task in tasks]))
    with _queue_lock(night_lock_path(project_path)):
        _write_tasks(night_queue_path(project_path), normalized)
    _write_state(project_path, _aggregate_status(normalized), f"saved {len(normalized)} night task(s)")
    return normalized


def list_night_tasks(project: str | Path, *, statuses: Sequence[str] | None = None) -> tuple[NightTask, ...]:
    tasks = load_night_tasks(project)
    if statuses is None:
        return tasks
    wanted = {_coerce_status(status) for status in statuses}
    return tuple(task for task in tasks if task.status in wanted)


def update_night_task(project: str | Path, task_id: str, **updates: Any) -> NightTask:
    project_path = Path(project).expanduser().resolve(strict=False)
    with _locked_queue(project_path) as tasks:
        index, task = _find_task(tasks, task_id)
        updated = _replace_task(task, project_path, **updates)
        tasks[index] = updated
    _write_state(project_path, _aggregate_status(load_night_tasks(project_path)), f"updated night task {task_id}", active_task_id=task_id)
    return updated


def get_night_task(project: str | Path, task_id: str) -> NightTask:
    tasks = load_night_tasks(project)
    _, task = _find_task(list(tasks), task_id)
    return task


def night_status(project: str | Path) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve(strict=False)
    tasks = load_night_tasks(project_path)
    status_path = night_state_path(project_path)
    state: dict[str, Any] = {}
    if status_path.exists():
        state = json.loads(status_path.read_text(encoding="utf-8"))
    counts = _status_counts(tasks)
    return {
        "status": state.get("status") or _aggregate_status(tasks),
        "summary": state.get("summary") or _summary_from_counts(counts),
        "counts": counts,
        "queue_path": str(night_queue_path(project_path)),
        "lock_path": str(night_lock_path(project_path)),
        "stop_file": str(night_stop_file(project_path)),
        "state_path": str(status_path),
        "query_events_path": str(night_query_events_path(project_path)),
        "trajectory_path": str(night_trajectory_path(project_path)),
        "active_task_id": state.get("active_task_id", ""),
        "tasks": [task.to_payload() for task in tasks],
    }


def stop_night_daemon(project: str | Path, *, reason: str = "stop requested", task_id: str = "", all_tasks: bool = False) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve(strict=False)
    stop_path = night_stop_file(project_path)
    stop_path.write_text(reason.rstrip() + "\n", encoding="utf-8")
    if task_id or all_tasks:
        with _locked_queue(project_path) as tasks:
            for index, task in enumerate(tasks):
                if task_id and task.id != task_id:
                    continue
                if task.status not in TERMINAL_STATUSES:
                    tasks[index] = _replace_task(task, project_path, status="stopped", summary=reason, finished_at=_now())
    _write_state(project_path, "stopped", reason, active_task_id=task_id)
    return night_status(project_path)


def resume_night_daemon(
    project: str | Path,
    *,
    task_id: str = "",
    include_failed: bool = False,
    reason: str = "resume requested",
) -> dict[str, Any]:
    project_path = Path(project).expanduser().resolve(strict=False)
    stop_path = night_stop_file(project_path)
    if stop_path.exists():
        stop_path.unlink()

    resumable = {"paused", "blocked"}
    if include_failed:
        resumable.add("failed")

    with _locked_queue(project_path) as tasks:
        for index, task in enumerate(tasks):
            if task_id and task.id != task_id:
                continue
            if task.status in resumable:
                tasks[index] = _replace_task(
                    task,
                    project_path,
                    status="queued",
                    paused_reason="",
                    summary=reason,
                    started_at="",
                    finished_at="",
                )
    _write_state(project_path, "queued", reason, active_task_id=task_id)
    return night_status(project_path)


def status_night_daemon(project: str | Path) -> dict[str, Any]:
    return night_status(project)


def stop_night_task(
    project: str | Path,
    *,
    task_id: str = "",
    all_tasks: bool = False,
    reason: str = "stop requested",
) -> NightDaemonResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    stop_path = night_stop_file(project_path)
    stop_path.write_text(reason.rstrip() + "\n", encoding="utf-8")
    stopped = 0
    if task_id or all_tasks:
        with _locked_queue(project_path) as tasks:
            for index, task in enumerate(tasks):
                if task_id and task.id != task_id:
                    continue
                if not all_tasks and not task_id:
                    continue
                if task.status not in TERMINAL_STATUSES:
                    tasks[index] = _replace_task(task, project_path, status="stopped", summary=reason, finished_at=_now())
                    stopped += 1
    _write_state(project_path, "stopped", reason, active_task_id=task_id, stop_path=stop_path)
    return _status_result(project_path, ok=True, status="stopped", summary=reason, active_task_id=task_id, stop_path=stop_path, processed=stopped)


def resume_night_task(project: str | Path, task_id: str, **daemon_options: Any) -> NightDaemonResult:
    status = resume_night_daemon(project, task_id=task_id, reason="resume requested")
    if daemon_options:
        project_path = Path(project).expanduser().resolve(strict=False)
        with _locked_queue(project_path) as tasks:
            index, task = _find_task(tasks, task_id)
            merged = dict(task.daemon_options)
            merged.update(_clean_options(daemon_options))
            tasks[index] = _replace_task(task, project_path, daemon_options=merged)
        status = night_status(project_path)
    return _status_result(
        project,
        ok=True,
        status=str(status.get("status") or "queued"),
        summary=str(status.get("summary") or "resume requested"),
        active_task_id=task_id,
    )


def run_night_daemon(
    project: str | Path,
    *,
    execute: bool = False,
    reviewed: bool = False,
    allow_actions: bool = False,
    browser: str = "Safari",
    engine: str = "google",
    max_steps: int = 20,
    max_minutes: float | None = 480.0,
    delay: float = 1.0,
    include_grid: bool = False,
    token_limit: int = 240,
    max_tasks: int | None = None,
    watch: bool = False,
    idle_sleep: float = 30.0,
    failure_pause: bool = True,
    stop_file: str | Path | None = None,
    runtime_queue: str | None = None,
    worker_id: str = "",
    lease_seconds: float = 300.0,
) -> NightDaemonResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    queue_name = _runtime_queue_for_run(project_path, runtime_queue)
    if queue_name:
        return _run_runtime_queue_night_daemon(
            project_path,
            execute=execute,
            reviewed=reviewed,
            allow_actions=allow_actions,
            browser=browser,
            engine=engine,
            max_steps=max_steps,
            max_minutes=max_minutes,
            delay=delay,
            include_grid=include_grid,
            token_limit=token_limit,
            max_tasks=max_tasks,
            watch=watch,
            idle_sleep=idle_sleep,
            failure_pause=failure_pause,
            stop_file=stop_file,
            runtime_queue=queue_name,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
    return _run_legacy_night_daemon(
        project_path,
        execute=execute,
        reviewed=reviewed,
        allow_actions=allow_actions,
        browser=browser,
        engine=engine,
        max_steps=max_steps,
        max_minutes=max_minutes,
        delay=delay,
        include_grid=include_grid,
        token_limit=token_limit,
        max_tasks=max_tasks,
        watch=watch,
        idle_sleep=idle_sleep,
        failure_pause=failure_pause,
        stop_file=stop_file,
    )


def _run_legacy_night_daemon(
    project: str | Path,
    *,
    execute: bool = False,
    reviewed: bool = False,
    allow_actions: bool = False,
    browser: str = "Safari",
    engine: str = "google",
    max_steps: int = 20,
    max_minutes: float | None = 480.0,
    delay: float = 1.0,
    include_grid: bool = False,
    token_limit: int = 240,
    max_tasks: int | None = None,
    watch: bool = False,
    idle_sleep: float = 30.0,
    failure_pause: bool = True,
    stop_file: str | Path | None = None,
) -> NightDaemonResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    stop_path = _resolve_stop_file(project_path, stop_file)
    queue_path = night_queue_path(project_path)
    lock_path = night_lock_path(project_path)
    state_path = night_state_path(project_path)
    query_events_path = night_query_events_path(project_path)
    trajectory_path = night_trajectory_path(project_path)
    runtime = QueryRuntime(project_path, event_path=query_events_path)
    processed = 0
    active_task_id = ""

    runtime.start(
        "night daemon queue",
        mode="desktop_night_daemon",
        data={
            "execute": execute,
            "reviewed": reviewed,
            "allow_actions": allow_actions,
            "max_steps": max_steps,
            "max_minutes": max_minutes,
            "max_tasks": max_tasks,
            "watch": watch,
            "failure_pause": failure_pause,
            "stop_file": str(stop_path),
            "queue_path": str(queue_path),
        },
    )
    _write_state(project_path, "running", "night daemon started", stop_path=stop_path)
    record_observation(trajectory_path, "night daemon started", ok=True, phase="start", queue_path=str(queue_path), stop_file=str(stop_path))
    deadline = None if max_minutes is None else time.monotonic() + max(0.1, min(float(max_minutes), 720.0)) * 60.0

    while True:
        if stop_path.exists():
            return _finish_run(
                project_path,
                runtime,
                processed,
                active_task_id,
                stop_path=stop_path,
                ok=False,
                status="stopped",
                summary=f"STOP file present: {stop_path}",
            )
        if deadline is not None and time.monotonic() > deadline:
            return _finish_run(
                project_path,
                runtime,
                processed,
                active_task_id,
                stop_path=stop_path,
                ok=False,
                status="paused",
                summary=f"night daemon time budget exhausted after {processed} task(s)",
                failure_class="desktop_budget_exhausted",
            )
        if max_tasks is not None and processed >= max(0, int(max_tasks)):
            return _finish_run(
                project_path,
                runtime,
                processed,
                active_task_id,
                stop_path=stop_path,
                ok=True,
                status="done",
                summary=f"processed max_tasks={max_tasks}",
            )

        task = _claim_next_task(project_path)
        if task is None:
            if not watch:
                return _finish_run(project_path, runtime, processed, active_task_id, stop_path=stop_path, ok=True, status="done", summary="no queued night task")
            _write_state(project_path, "running", "waiting for queued night task", stop_path=stop_path)
            time.sleep(max(0.0, min(float(idle_sleep), 3600.0)))
            continue

        active_task_id = task.id
        runtime.pre_tool("desktop_night_daemon", step=processed + 1, args={"task_id": task.id, "goal": task.goal})
        record_action(trajectory_path, f"night task {task.id} started", step=processed + 1, ok=None, phase="task_start", task=task.to_payload())
        _write_state(project_path, "running", f"running night task {task.id}", active_task_id=task.id, stop_path=stop_path)

        try:
            daemon = _run_task_daemon(
                project_path,
                task,
                execute=execute,
                reviewed=reviewed,
                allow_actions=allow_actions,
                browser=browser,
                engine=engine,
                max_steps=max_steps,
                delay=delay,
                include_grid=include_grid,
                token_limit=token_limit,
                stop_path=stop_path,
            )
        except Exception as exc:
            summary = f"night task {task.id} crashed: {exc}"
            final_status = "paused" if failure_pause else "failed"
            _complete_task(project_path, task.id, final_status, summary, paused_reason=summary if failure_pause else "")
            runtime.post_tool("desktop_night_daemon", step=processed + 1, ok=False, summary=summary, data={"task_id": task.id})
            record_observation(trajectory_path, summary, step=processed + 1, ok=False, phase="task_exception", task_id=task.id)
            return _finish_run(project_path, runtime, processed, task.id, stop_path=stop_path, ok=False, status=final_status, summary=summary, failure_class="night_task_exception")

        processed += 1
        mapped_status = _map_daemon_status(daemon)
        final_status = "paused" if failure_pause and mapped_status == "failed" else mapped_status
        paused_reason = daemon.summary if final_status == "paused" else ""
        updated = _complete_task(
            project_path,
            task.id,
            final_status,
            daemon.summary,
            result_status=daemon.status,
            result_path=daemon.state_path,
            query_events_path=daemon.query_events_path,
            trajectory_path=daemon.trajectory_path,
            state_path=daemon.state_path,
            paused_reason=paused_reason,
        )
        runtime.post_tool(
            "desktop_night_daemon",
            step=processed,
            ok=daemon.ok,
            summary=daemon.summary,
            data={"task_id": task.id, "task_status": updated.status, "daemon": daemon.to_payload()},
        )
        record_observation(
            trajectory_path,
            f"night task {task.id} finished as {updated.status}: {daemon.summary}",
            step=processed,
            ok=daemon.ok,
            phase="task_finish",
            task_id=task.id,
            task_status=updated.status,
            daemon_status=daemon.status,
            daemon_state_path=daemon.state_path,
            daemon_query_events_path=daemon.query_events_path,
            daemon_trajectory_path=daemon.trajectory_path,
        )
        _write_state(project_path, updated.status, daemon.summary, active_task_id=task.id, stop_path=stop_path)

        if updated.status in {"paused", "blocked", "failed", "stopped"}:
            return _finish_run(
                project_path,
                runtime,
                processed,
                task.id,
                stop_path=stop_path,
                ok=False,
                status=updated.status,
                summary=f"night daemon paused on task {task.id}: {daemon.summary}" if updated.status == "paused" else daemon.summary,
                failure_class=updated.status,
            )


def _run_runtime_queue_night_daemon(
    project: str | Path,
    *,
    execute: bool,
    reviewed: bool,
    allow_actions: bool,
    browser: str,
    engine: str,
    max_steps: int,
    max_minutes: float | None,
    delay: float,
    include_grid: bool,
    token_limit: int,
    max_tasks: int | None,
    watch: bool,
    idle_sleep: float,
    failure_pause: bool,
    stop_file: str | Path | None,
    runtime_queue: str,
    worker_id: str,
    lease_seconds: float,
) -> NightDaemonResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    queue_name = str(runtime_queue or DEFAULT_RUNTIME_QUEUE).strip() or DEFAULT_RUNTIME_QUEUE
    owner = str(worker_id or _new_worker_id())
    stop_path = _resolve_stop_file(project_path, stop_file)
    query_events_path = night_query_events_path(project_path)
    trajectory_path = night_trajectory_path(project_path)
    runtime = QueryRuntime(project_path, event_path=query_events_path)
    processed = 0
    active_task_id = ""

    runtime.start(
        "night daemon runtime queue",
        mode="desktop_night_daemon",
        data={
            "execute": execute,
            "reviewed": reviewed,
            "allow_actions": allow_actions,
            "max_steps": max_steps,
            "max_minutes": max_minutes,
            "max_tasks": max_tasks,
            "watch": watch,
            "failure_pause": failure_pause,
            "stop_file": str(stop_path),
            "runtime_queue": queue_name,
            "worker_id": owner,
            "lease_seconds": lease_seconds,
        },
    )
    _write_runtime_queue_state(project_path, queue_name, "running", "night daemon runtime queue started", stop_path=stop_path)
    record_observation(
        trajectory_path,
        "night daemon runtime queue started",
        ok=True,
        phase="start",
        queue_path=_runtime_queue_path(project_path, queue_name),
        stop_file=str(stop_path),
    )
    deadline = None if max_minutes is None else time.monotonic() + max(0.1, min(float(max_minutes), 720.0)) * 60.0

    while True:
        if stop_path.exists():
            return _finish_runtime_queue_run(
                project_path,
                runtime,
                processed,
                active_task_id,
                queue_name,
                stop_path=stop_path,
                ok=False,
                status="stopped",
                summary=f"STOP file present: {stop_path}",
            )
        if deadline is not None and time.monotonic() > deadline:
            return _finish_runtime_queue_run(
                project_path,
                runtime,
                processed,
                active_task_id,
                queue_name,
                stop_path=stop_path,
                ok=False,
                status="paused",
                summary=f"night daemon time budget exhausted after {processed} task(s)",
                failure_class="desktop_budget_exhausted",
            )
        if max_tasks is not None and processed >= max(0, int(max_tasks)):
            return _finish_runtime_queue_run(
                project_path,
                runtime,
                processed,
                active_task_id,
                queue_name,
                stop_path=stop_path,
                ok=True,
                status="done",
                summary=f"processed max_tasks={max_tasks}",
            )

        item = runtime_store.claim_runtime_queue_item(project_path, queue=queue_name, lease_owner=owner, lease_seconds=lease_seconds)
        if item is None:
            if not watch:
                return _finish_runtime_queue_run(
                    project_path,
                    runtime,
                    processed,
                    active_task_id,
                    queue_name,
                    stop_path=stop_path,
                    ok=True,
                    status="done",
                    summary="no queued runtime queue item",
                )
            _write_runtime_queue_state(project_path, queue_name, "running", "waiting for runtime queue item", stop_path=stop_path)
            time.sleep(max(0.0, min(float(idle_sleep), 3600.0)))
            continue

        active_task_id = item.task_id
        item = runtime_store.heartbeat_runtime_queue_item(project_path, item.task_id, lease_owner=owner, lease_seconds=lease_seconds)
        task = _task_from_runtime_queue_item(project_path, item)
        runtime.pre_tool("desktop_night_daemon", step=processed + 1, args={"task_id": task.id, "goal": task.goal, "runtime_queue": queue_name})
        record_action(trajectory_path, f"runtime queue task {task.id} started", step=processed + 1, ok=None, phase="task_start", task=task.to_payload())
        _write_runtime_queue_state(project_path, queue_name, "running", f"running runtime queue task {task.id}", active_task_id=task.id, stop_path=stop_path)

        if item.status == "stopped":
            return _finish_runtime_queue_run(
                project_path,
                runtime,
                processed,
                task.id,
                queue_name,
                stop_path=stop_path,
                ok=False,
                status="stopped",
                summary=item.summary or f"runtime queue item stopped: {task.id}",
                failure_class="stopped",
            )

        try:
            daemon = _run_task_daemon(
                project_path,
                task,
                execute=execute,
                reviewed=reviewed,
                allow_actions=allow_actions,
                browser=browser,
                engine=engine,
                max_steps=max_steps,
                delay=delay,
                include_grid=include_grid,
                token_limit=token_limit,
                stop_path=stop_path,
            )
        except Exception as exc:
            summary = f"night task {task.id} crashed: {exc}"
            final_status = "paused" if failure_pause else "failed"
            updated_item = _finish_runtime_queue_task(
                project_path,
                item,
                owner,
                final_status,
                summary,
                paused_reason=summary if failure_pause else "",
            )
            runtime.post_tool("desktop_night_daemon", step=processed + 1, ok=False, summary=summary, data={"task_id": task.id})
            record_observation(trajectory_path, summary, step=processed + 1, ok=False, phase="task_exception", task_id=task.id)
            return _finish_runtime_queue_run(
                project_path,
                runtime,
                processed,
                task.id,
                queue_name,
                stop_path=stop_path,
                ok=False,
                status=updated_item.status,
                summary=summary,
                failure_class="night_task_exception",
            )

        processed += 1
        heartbeat = runtime_store.heartbeat_runtime_queue_item(project_path, item.task_id, lease_owner=owner, lease_seconds=lease_seconds)
        if heartbeat.status == "stopped":
            runtime.post_tool(
                "desktop_night_daemon",
                step=processed,
                ok=False,
                summary=heartbeat.summary,
                data={"task_id": task.id, "task_status": "stopped", "daemon": daemon.to_payload()},
            )
            record_observation(
                trajectory_path,
                f"runtime queue task {task.id} stopped after daemon run: {heartbeat.summary}",
                step=processed,
                ok=False,
                phase="task_stop",
                task_id=task.id,
                daemon_status=daemon.status,
            )
            _write_runtime_queue_state(project_path, queue_name, "stopped", heartbeat.summary, active_task_id=task.id, stop_path=stop_path)
            return _finish_runtime_queue_run(
                project_path,
                runtime,
                processed,
                task.id,
                queue_name,
                stop_path=stop_path,
                ok=False,
                status="stopped",
                summary=heartbeat.summary,
                failure_class="stopped",
            )

        mapped_status = _map_daemon_status(daemon)
        final_status = "paused" if failure_pause and mapped_status == "failed" else mapped_status
        paused_reason = daemon.summary if final_status == "paused" else ""
        updated_item = _finish_runtime_queue_task(
            project_path,
            item,
            owner,
            final_status,
            daemon.summary,
            daemon=daemon,
            paused_reason=paused_reason,
        )
        updated_task = _task_from_runtime_queue_item(project_path, updated_item)
        runtime.post_tool(
            "desktop_night_daemon",
            step=processed,
            ok=daemon.ok,
            summary=daemon.summary,
            data={"task_id": task.id, "task_status": updated_task.status, "daemon": daemon.to_payload()},
        )
        record_observation(
            trajectory_path,
            f"runtime queue task {task.id} finished as {updated_task.status}: {daemon.summary}",
            step=processed,
            ok=daemon.ok,
            phase="task_finish",
            task_id=task.id,
            task_status=updated_task.status,
            daemon_status=daemon.status,
            daemon_state_path=daemon.state_path,
            daemon_query_events_path=daemon.query_events_path,
            daemon_trajectory_path=daemon.trajectory_path,
        )
        _write_runtime_queue_state(project_path, queue_name, updated_task.status, daemon.summary, active_task_id=task.id, stop_path=stop_path)

        if updated_task.status in {"paused", "blocked", "failed", "stopped"}:
            return _finish_runtime_queue_run(
                project_path,
                runtime,
                processed,
                task.id,
                queue_name,
                stop_path=stop_path,
                ok=False,
                status=updated_task.status,
                summary=f"night daemon paused on task {task.id}: {daemon.summary}" if updated_task.status == "paused" else daemon.summary,
                failure_class=updated_task.status,
            )


def render_night_status(status: dict[str, Any] | NightDaemonResult | Sequence[NightTask] | NightTask) -> str:
    if isinstance(status, NightDaemonResult):
        payload = status.to_payload()
    elif isinstance(status, NightTask):
        payload = {"status": status.status, "summary": status.summary or status.goal, "tasks": [status.to_payload()]}
    elif isinstance(status, dict):
        payload = status
    else:
        tasks = tuple(status)
        payload = {"status": _aggregate_status(tasks), "summary": _summary_from_counts(_status_counts(tasks)), "tasks": [task.to_payload() for task in tasks]}

    lines = [
        "# Night Daemon",
        "",
        f"Status: {payload.get('status', '-')}",
        f"Summary: {payload.get('summary', '-')}",
    ]
    for key, label in (
        ("queue_path", "Queue"),
        ("lock_path", "Lock"),
        ("stop_file", "STOP"),
        ("state_path", "State"),
        ("query_events_path", "Query events"),
        ("trajectory_path", "Trajectory"),
    ):
        value = payload.get(key)
        if value:
            lines.append(f"{label}: {value}")
    tasks = payload.get("tasks") or []
    if tasks:
        lines.extend(["", "Tasks:"])
        for task in tasks[-30:]:
            lines.append(f"- {task.get('id')} [{task.get('status')}] attempts={task.get('attempts', 0)}: {task.get('summary') or task.get('goal')}")
    return "\n".join(lines).rstrip() + "\n"


def render_night_tasks(tasks: Sequence[NightTask]) -> str:
    return render_night_status(tasks)


def render_night_result(result: NightDaemonResult | NightTask | dict[str, Any] | Sequence[NightTask]) -> str:
    if not isinstance(result, NightDaemonResult):
        return render_night_status(result)
    lines = [
        "# Night Daemon Result",
        "",
        f"Status: {result.status}",
        f"OK: {str(result.ok).lower()}",
        result.summary,
        f"Processed: {result.processed}",
        f"Queue: {result.queue_path}",
        f"STOP: {result.stop_file}",
        f"State: {result.state_path}",
        f"Query events: {result.query_events_path}",
        f"Trajectory: {result.trajectory_path}",
    ]
    if result.active_task_id:
        lines.append(f"Active task: {result.active_task_id}")
    if result.tasks:
        lines.extend(["", "Recent tasks:"])
        for task in result.tasks[-20:]:
            lines.append(f"- {task.id} [{task.status}/{task.result_status or '-'}] attempts={task.attempts}: {task.summary or task.goal}")
    return "\n".join(lines).rstrip() + "\n"


def _run_task_daemon(
    project: Path,
    task: NightTask,
    *,
    execute: bool,
    reviewed: bool,
    allow_actions: bool,
    browser: str,
    engine: str,
    max_steps: int,
    delay: float,
    include_grid: bool,
    token_limit: int,
    stop_path: Path,
) -> DesktopDaemonResult:
    options = dict(task.daemon_options)
    return run_desktop_daemon(
        project,
        task.goal,
        execute=_downgraded_gate(execute, options.pop("execute", execute)),
        reviewed=_downgraded_gate(reviewed, options.pop("reviewed", reviewed)),
        allow_actions=_downgraded_gate(allow_actions, options.pop("allow_actions", allow_actions)),
        browser=str(options.pop("browser", browser)),
        engine=str(options.pop("engine", engine)),
        max_steps=int(options.pop("max_steps", max_steps)),
        delay=float(options.pop("delay", delay)),
        stop_file=options.pop("stop_file", stop_path),
        include_grid=bool(options.pop("include_grid", include_grid)),
        token_limit=int(options.pop("token_limit", token_limit)),
    )


def _downgraded_gate(outer: bool, task_option: Any) -> bool:
    return bool(outer) and bool(task_option)


def _claim_next_task(project: Path) -> NightTask | None:
    with _locked_queue(project) as tasks:
        queued = [(index, task) for index, task in enumerate(tasks) if task.status == "queued"]
        if not queued:
            return None
        index, task = sorted(queued, key=lambda item: (item[1].priority, item[1].created_at, item[1].id))[0]
        claimed = _replace_task(task, project, status="running", attempts=task.attempts + 1, started_at=_now(), finished_at="", summary="running")
        tasks[index] = claimed
        return claimed


def _complete_task(
    project: Path,
    task_id: str,
    status: str,
    summary: str,
    *,
    result_status: str = "",
    result_path: str = "",
    query_events_path: str = "",
    trajectory_path: str = "",
    state_path: str = "",
    paused_reason: str = "",
) -> NightTask:
    with _locked_queue(project) as tasks:
        index, task = _find_task(tasks, task_id)
        updated = _replace_task(
            task,
            project,
            status=status,
            summary=summary,
            result_status=result_status,
            result_path=result_path,
            query_events_path=query_events_path,
            trajectory_path=trajectory_path,
            state_path=state_path,
            paused_reason=paused_reason,
            finished_at=_now() if status in TERMINAL_STATUSES or status in {"paused", "blocked"} else "",
        )
        tasks[index] = updated
        return updated


def _finish_run(
    project: Path,
    runtime: QueryRuntime,
    processed: int,
    active_task_id: str,
    stop_path: Path | None = None,
    *,
    ok: bool,
    status: str,
    summary: str,
    failure_class: str = "",
) -> NightDaemonResult:
    resolved_stop_path = stop_path or night_stop_file(project)
    _write_state(project, status, summary, active_task_id=active_task_id, stop_path=resolved_stop_path)
    runtime.stop(summary, ok=ok, failure_class=failure_class or status)
    tasks = load_night_tasks(project)
    return NightDaemonResult(
        ok=ok,
        status=status,
        summary=summary,
        tasks=tasks,
        queue_path=str(night_queue_path(project)),
        lock_path=str(night_lock_path(project)),
        stop_file=str(resolved_stop_path),
        state_path=str(night_state_path(project)),
        query_events_path=str(night_query_events_path(project)),
        trajectory_path=str(night_trajectory_path(project)),
        active_task_id=active_task_id,
        processed=processed,
    )


def _finish_runtime_queue_run(
    project: Path,
    runtime: QueryRuntime,
    processed: int,
    active_task_id: str,
    runtime_queue: str,
    stop_path: Path | None = None,
    *,
    ok: bool,
    status: str,
    summary: str,
    failure_class: str = "",
) -> NightDaemonResult:
    resolved_stop_path = stop_path or night_stop_file(project)
    _write_runtime_queue_state(project, runtime_queue, status, summary, active_task_id=active_task_id, stop_path=resolved_stop_path)
    runtime.stop(summary, ok=ok, failure_class=failure_class or status)
    tasks = tuple(_runtime_queue_tasks(project, runtime_queue))
    return NightDaemonResult(
        ok=ok,
        status=status,
        summary=summary,
        tasks=tasks,
        queue_path=_runtime_queue_path(project, runtime_queue),
        lock_path="",
        stop_file=str(resolved_stop_path),
        state_path=str(night_state_path(project)),
        query_events_path=str(night_query_events_path(project)),
        trajectory_path=str(night_trajectory_path(project)),
        active_task_id=active_task_id,
        processed=processed,
    )


def _status_result(
    project: str | Path,
    *,
    ok: bool,
    status: str,
    summary: str,
    active_task_id: str = "",
    stop_path: Path | None = None,
    processed: int = 0,
) -> NightDaemonResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    resolved_stop_path = stop_path or night_stop_file(project_path)
    return NightDaemonResult(
        ok=ok,
        status=status,
        summary=summary,
        tasks=load_night_tasks(project_path),
        queue_path=str(night_queue_path(project_path)),
        lock_path=str(night_lock_path(project_path)),
        stop_file=str(resolved_stop_path),
        state_path=str(night_state_path(project_path)),
        query_events_path=str(night_query_events_path(project_path)),
        trajectory_path=str(night_trajectory_path(project_path)),
        active_task_id=active_task_id,
        processed=processed,
    )


def _runtime_queue_for_run(project: Path, runtime_queue: str | None) -> str:
    if runtime_queue is not None:
        return str(runtime_queue).strip()
    items = runtime_store.list_runtime_queue_items(project, queue=DEFAULT_RUNTIME_QUEUE, status=("queued", "running"), limit=1)
    return DEFAULT_RUNTIME_QUEUE if items else ""


def _new_worker_id() -> str:
    return f"{WORKER_ID_PREFIX}{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _runtime_queue_path(project: Path, queue_name: str) -> str:
    return f"{runtime_store.ensure_runtime_store(project)}#runtime_queue:{queue_name}"


def _runtime_queue_tasks(project: Path, queue_name: str, *, limit: int = 200) -> tuple[NightTask, ...]:
    return tuple(_task_from_runtime_queue_item(project, item) for item in runtime_store.list_runtime_queue_items(project, queue=queue_name, limit=limit))


def _write_runtime_queue_state(
    project: Path,
    queue_name: str,
    status: str,
    summary: str,
    *,
    active_task_id: str = "",
    stop_path: Path | None = None,
) -> None:
    tasks = _runtime_queue_tasks(project, queue_name)
    counts = _status_counts(tasks)
    resolved_stop_path = stop_path or night_stop_file(project)
    payload = {
        "status": status,
        "summary": summary,
        "updated_at": _now(),
        "active_task_id": active_task_id,
        "counts": counts,
        "queue_path": _runtime_queue_path(project, queue_name),
        "lock_path": "",
        "stop_file": str(resolved_stop_path),
        "state_path": str(night_state_path(project)),
        "query_events_path": str(night_query_events_path(project)),
        "trajectory_path": str(night_trajectory_path(project)),
        "runtime_queue": queue_name,
        "tasks": [task.to_payload() for task in tasks[-200:]],
    }
    night_state_path(project).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _task_from_runtime_queue_item(project: Path, item: runtime_store.RuntimeQueueItem) -> NightTask:
    payload = item.payload
    daemon_options = payload.get("daemon_options") if isinstance(payload.get("daemon_options"), dict) else {}
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    metadata = dict(metadata or {})
    metadata.update(
        {
            "runtime_queue": item.queue,
            "runtime_task_kind": item.task_kind,
            "runtime_owner_key": item.owner_key,
            "runtime_session_lock_key": item.session_lock_key or "",
        }
    )
    goal = str(payload.get("goal") or item.task or item.task_id)
    night = payload.get("night_daemon") if isinstance(payload.get("night_daemon"), dict) else {}
    daemon = payload.get("daemon_result") if isinstance(payload.get("daemon_result"), dict) else {}
    return NightTask(
        id=item.task_id,
        project=str(project),
        goal=goal,
        status=_night_status_from_runtime_queue_status(item.status),
        priority=int(item.priority),
        attempts=int(item.attempts),
        max_attempts=max(1, int(item.max_attempts or 1)),
        created_at=_iso_from_ms(item.created_at),
        updated_at=_iso_from_ms(item.updated_at),
        started_at=_iso_from_ms(item.started_at),
        finished_at=_iso_from_ms(item.ended_at),
        paused_reason=str(night.get("paused_reason") or ""),
        summary=str(item.summary or item.error or night.get("summary") or ""),
        result_status=str(night.get("result_status") or daemon.get("status") or ""),
        result_path=str(night.get("result_path") or daemon.get("state_path") or ""),
        query_events_path=str(night.get("query_events_path") or daemon.get("query_events_path") or ""),
        trajectory_path=str(night.get("trajectory_path") or daemon.get("trajectory_path") or ""),
        state_path=str(night.get("state_path") or daemon.get("state_path") or ""),
        metadata=metadata,
        daemon_options=dict(daemon_options or {}),
    )


def _finish_runtime_queue_task(
    project: Path,
    item: runtime_store.RuntimeQueueItem,
    lease_owner: str,
    status: str,
    summary: str,
    *,
    daemon: DesktopDaemonResult | None = None,
    paused_reason: str = "",
) -> runtime_store.RuntimeQueueItem:
    payload = _runtime_queue_result_payload(item, status, summary, daemon=daemon, paused_reason=paused_reason)
    if status == "done":
        return runtime_store.complete_runtime_queue_item(project, item.task_id, lease_owner=lease_owner, result=payload)
    if status == "blocked":
        return runtime_store.block_runtime_queue_item(project, item.task_id, lease_owner=lease_owner, reason=summary, result=payload)
    if status == "paused":
        return runtime_store.pause_runtime_queue_item(project, item.task_id, lease_owner=lease_owner, reason=summary, result=payload)
    if status == "failed":
        return runtime_store.fail_runtime_queue_item(project, item.task_id, lease_owner=lease_owner, error=summary, result=payload)
    if status == "stopped":
        return runtime_store.stop_runtime_queue_item(project, item.task_id, lease_owner=lease_owner, reason=summary)
    raise ValueError(f"unsupported runtime queue night status: {status}")


def _runtime_queue_result_payload(
    item: runtime_store.RuntimeQueueItem,
    status: str,
    summary: str,
    *,
    daemon: DesktopDaemonResult | None,
    paused_reason: str,
) -> dict[str, Any]:
    payload = dict(item.payload)
    night_payload: dict[str, Any] = {
        "status": status,
        "summary": summary,
        "paused_reason": paused_reason,
        "updated_at": _now(),
    }
    if daemon is not None:
        daemon_payload = daemon.to_payload()
        payload["daemon_result"] = daemon_payload
        night_payload.update(
            {
                "result_status": daemon.status,
                "result_path": daemon.state_path,
                "query_events_path": daemon.query_events_path,
                "trajectory_path": daemon.trajectory_path,
                "state_path": daemon.state_path,
            }
        )
    payload["night_daemon"] = night_payload
    return payload


def _night_status_from_runtime_queue_status(status: str) -> str:
    value = str(status or "").strip().lower()
    if value == "lost":
        return "failed"
    return _coerce_status(value)


def _iso_from_ms(value: int | None) -> str:
    if not value:
        return ""
    return datetime.fromtimestamp(int(value) / 1000.0).isoformat(timespec="seconds")


@contextlib.contextmanager
def _locked_queue(project: Path) -> Iterator[list[NightTask]]:
    with _queue_lock(night_lock_path(project)):
        tasks = _read_tasks(night_queue_path(project))
        yield tasks
        _write_tasks(night_queue_path(project), _sorted_tasks(tasks))


@contextlib.contextmanager
def _queue_lock(path: Path, *, timeout: float = 10.0, poll: float = 0.05) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl  # type: ignore
    except ImportError:
        lockfile = path.with_suffix(path.suffix + ".held")
        deadline = time.monotonic() + timeout
        fd = -1
        while True:
            try:
                fd = os.open(str(lockfile), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("utf-8"))
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"night daemon queue lock timeout: {lockfile}")
                time.sleep(poll)
        try:
            yield
        finally:
            if fd >= 0:
                os.close(fd)
            with contextlib.suppress(FileNotFoundError):
                lockfile.unlink()
        return

    deadline = time.monotonic() + timeout
    with path.open("a+", encoding="utf-8") as handle:
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"night daemon queue lock timeout: {path}")
                time.sleep(poll)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_tasks(path: Path) -> list[NightTask]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_tasks: Any
    if isinstance(payload, dict):
        raw_tasks = payload.get("tasks", [])
    elif isinstance(payload, list):
        raw_tasks = payload
    else:
        raise ValueError(f"invalid night queue payload: {path}")
    if not isinstance(raw_tasks, list):
        raise ValueError(f"invalid night queue tasks: {path}")
    return _sorted_tasks([_task_from_payload(item) for item in raw_tasks if isinstance(item, dict)])


def _write_tasks(path: Path, tasks: Sequence[NightTask]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": QUEUE_VERSION,
        "updated_at": _now(),
        "tasks": [task.to_payload() for task in tasks],
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_state(project: Path, status: str, summary: str, *, active_task_id: str = "", stop_path: Path | None = None) -> None:
    tasks = load_night_tasks(project)
    counts = _status_counts(tasks)
    resolved_stop_path = stop_path or night_stop_file(project)
    payload = {
        "status": status,
        "summary": summary,
        "updated_at": _now(),
        "active_task_id": active_task_id,
        "counts": counts,
        "queue_path": str(night_queue_path(project)),
        "lock_path": str(night_lock_path(project)),
        "stop_file": str(resolved_stop_path),
        "state_path": str(night_state_path(project)),
        "query_events_path": str(night_query_events_path(project)),
        "trajectory_path": str(night_trajectory_path(project)),
        "tasks": [task.to_payload() for task in tasks[-200:]],
    }
    path = night_state_path(project)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _task_from_payload(payload: dict[str, Any]) -> NightTask:
    status = _coerce_status(str(payload.get("status") or "queued"))
    return NightTask(
        id=str(payload.get("id") or _new_task_id()),
        project=str(payload.get("project") or ""),
        goal=str(payload.get("goal") or ""),
        status=status,
        priority=int(payload.get("priority") or 100),
        attempts=int(payload.get("attempts") or 0),
        max_attempts=max(1, int(payload.get("max_attempts") or 1)),
        created_at=str(payload.get("created_at") or _now()),
        updated_at=str(payload.get("updated_at") or _now()),
        started_at=str(payload.get("started_at") or ""),
        finished_at=str(payload.get("finished_at") or ""),
        paused_reason=str(payload.get("paused_reason") or ""),
        summary=str(payload.get("summary") or ""),
        result_status=str(payload.get("result_status") or ""),
        result_path=str(payload.get("result_path") or ""),
        query_events_path=str(payload.get("query_events_path") or ""),
        trajectory_path=str(payload.get("trajectory_path") or ""),
        state_path=str(payload.get("state_path") or ""),
        metadata=dict(payload.get("metadata") or {}),
        daemon_options=dict(payload.get("daemon_options") or {}),
    )


def _replace_task(task: NightTask, project: Path, **updates: Any) -> NightTask:
    payload = task.to_payload()
    payload.update(updates)
    payload["project"] = str(project)
    payload["updated_at"] = _now()
    payload["status"] = _coerce_status(str(payload.get("status") or task.status))
    return _task_from_payload(payload)


def _normalize_task(task: NightTask, project: Path) -> NightTask:
    return _replace_task(task, project)


def _find_task(tasks: list[NightTask], task_id: str) -> tuple[int, NightTask]:
    for index, task in enumerate(tasks):
        if task.id == task_id:
            return index, task
    raise KeyError(f"night task not found: {task_id}")


def _sorted_tasks(tasks: Iterable[NightTask]) -> list[NightTask]:
    return sorted(tasks, key=lambda task: (task.status != "running", task.priority, task.created_at, task.id))


def _coerce_status(status: str) -> str:
    value = status.strip().lower()
    if value not in NIGHT_STATUSES:
        raise ValueError(f"invalid night task status: {status}")
    return value


def _map_daemon_status(result: DesktopDaemonResult) -> str:
    if result.status == "stopped":
        return "stopped"
    if result.status == "blocked":
        return "blocked"
    if result.ok:
        return "done"
    return "failed"


def _clean_options(options: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in options.items() if value is not None}


def _status_counts(tasks: Iterable[NightTask]) -> dict[str, int]:
    counts = {status: 0 for status in sorted(NIGHT_STATUSES)}
    for task in tasks:
        counts[task.status] = counts.get(task.status, 0) + 1
    return counts


def _aggregate_status(tasks: Sequence[NightTask]) -> str:
    if any(task.status == "running" for task in tasks):
        return "running"
    if any(task.status == "paused" for task in tasks):
        return "paused"
    if any(task.status == "blocked" for task in tasks):
        return "blocked"
    if any(task.status == "queued" for task in tasks):
        return "queued"
    if any(task.status == "failed" for task in tasks):
        return "failed"
    if any(task.status == "stopped" for task in tasks):
        return "stopped"
    return "done"


def _summary_from_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{status}={count}" for status, count in sorted(counts.items()) if count) or "no night tasks"


def _resolve_stop_file(project: Path, stop_file: str | Path | None) -> Path:
    if stop_file is None:
        return night_stop_file(project)
    path = Path(stop_file).expanduser()
    return path if path.is_absolute() else project / path


def _new_task_id() -> str:
    return "night-" + uuid.uuid4().hex[:12]
