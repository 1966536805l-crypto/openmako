from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .safety import ASK, DENY, SafetyPolicy, assess_command
from .task_state import (
    ABORTED,
    BLOCKED,
    FAILED,
    LOST,
    NOTIFY_DONE_ONLY,
    PASSED,
    QUEUED,
    RUNNING,
    SCOPE_PROJECT,
    ResearchTask,
    load_tasks,
    reconcile_task_contract,
    save_tasks,
    task_dir,
)


WORKER_CODE = r"""
import json, subprocess, sys, time
payload = json.loads(sys.argv[1])
started = time.time()
try:
    with open(payload["stdout"], "ab", buffering=0) as out, open(payload["stderr"], "ab", buffering=0) as err:
        result = subprocess.run(payload["command"], cwd=payload["cwd"], stdout=out, stderr=err)
    status = {"returncode": result.returncode, "started": started, "finished": time.time()}
except BaseException as exc:
    status = {"returncode": 127, "started": started, "finished": time.time(), "error": type(exc).__name__ + ": " + str(exc)}
with open(payload["status"], "w", encoding="utf-8") as handle:
    json.dump(status, handle, ensure_ascii=False, sort_keys=True)
    handle.write("\n")
"""


AGENT_WORKER_CODE = r"""
import contextlib, json, sys, time
from pathlib import Path

payload = json.loads(sys.argv[1])
started = time.time()
status = {"returncode": 127, "started": started}
try:
    with open(payload["stdout"], "ab", buffering=0) as out, open(payload["stderr"], "ab", buffering=0) as err:
        with contextlib.redirect_stdout(open(out.fileno(), "w", encoding="utf-8", closefd=False)), contextlib.redirect_stderr(open(err.fileno(), "w", encoding="utf-8", closefd=False)):
            from quantagent.agent_v2 import run_agent_v2

            task_text = payload["task"]
            context_path = payload.get("context_path") or ""
            if context_path:
                try:
                    context_text = Path(context_path).read_text(encoding="utf-8", errors="replace")
                    task_text = "Subagent context:\n" + context_text + "\n\nTask:\n" + task_text
                except OSError:
                    task_text = "Subagent context path unavailable: " + context_path + "\n\nTask:\n" + task_text
            result = run_agent_v2(
                Path(payload["project"]),
                task_text,
                include_validation=bool(payload.get("include_validation", True)),
                stop_on_required_failure=bool(payload.get("stop_on_failure", False)),
                agent_profile=str(payload.get("agent_profile") or "project"),
                context_path=context_path,
            )
            result_path = Path(payload["result"])
            result_path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            status = {
                "returncode": 0 if result.ok else 1,
                "started": started,
                "finished": time.time(),
                "ok": result.ok,
                "summary": result.summary,
                "failure_class": result.failure_class,
                "trajectory_path": result.trajectory_path,
                "query_events_path": result.query_events_path,
                "result_path": str(result_path),
            }
except BaseException as exc:
    status = {
        "returncode": 127,
        "started": started,
        "finished": time.time(),
        "error": type(exc).__name__ + ": " + str(exc),
    }
with open(payload["status"], "w", encoding="utf-8") as handle:
    json.dump(status, handle, ensure_ascii=False, sort_keys=True)
    handle.write("\n")
"""


def runtime_dir(project: str | Path) -> Path:
    directory = task_dir(Path(project)) / "runtime"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def start_shell_task(
    project: str | Path,
    command: list[str],
    *,
    title: str = "",
    allow_risky: bool = False,
    requester_session_key: str = "",
    owner_key: str = "local",
    scope_kind: str = SCOPE_PROJECT,
    child_session_key: str = "",
    parent_task_id: str = "",
    notify_policy: str = NOTIFY_DONE_ONLY,
    cleanup_after: int | None = None,
) -> ResearchTask:
    project_path = Path(project).expanduser().resolve(strict=False)
    argv = [str(item) for item in command]
    if not argv:
        raise ValueError("command is empty")
    rendered = shlex.join(argv)
    decision = assess_command(rendered, cwd=project_path, policy=SafetyPolicy(project=project_path))
    if decision.action == DENY or (decision.action == ASK and not allow_risky):
        return _create_blocked_task(
            project_path,
            title or rendered,
            argv,
            decision.render(),
            requester_session_key=requester_session_key,
            owner_key=owner_key,
            scope_kind=scope_kind,
            child_session_key=child_session_key,
            parent_task_id=parent_task_id,
            notify_policy=notify_policy,
            cleanup_after=cleanup_after,
        )

    tasks = load_tasks(project_path)
    task_id = _next_runtime_id(tasks)
    out_dir = runtime_dir(project_path) / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    stdout = out_dir / "stdout.txt"
    stderr = out_dir / "stderr.txt"
    status = out_dir / "status.json"
    payload = {
        "command": argv,
        "cwd": str(project_path),
        "stdout": str(stdout),
        "stderr": str(stderr),
        "status": str(status),
    }
    proc = subprocess.Popen(
        [sys.executable, "-c", WORKER_CODE, json.dumps(payload, ensure_ascii=False)],
        cwd=project_path,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid = proc.pid
    proc._child_created = False  # type: ignore[attr-defined]
    now = datetime.now().isoformat(timespec="seconds")
    task = ResearchTask(
        id=task_id,
        title=title or rendered,
        detail=decision.render(),
        kind="shell",
        status=RUNNING,
        pid=pid,
        command=argv,
        output_path=str(stdout),
        error_path=str(stderr),
        status_path=str(status),
        requester_session_key=requester_session_key,
        owner_key=owner_key,
        scope_kind=scope_kind,
        child_session_key=child_session_key,
        parent_task_id=parent_task_id,
        notify_policy=notify_policy,
        cleanup_after=cleanup_after,
        created_at=now,
        updated_at=now,
        evidence=[str(stdout), str(stderr), str(status)],
        history=[{"status": RUNNING, "at": now, "note": "started shell task", "pid": pid}],
    )
    reconcile_task_contract(task)
    tasks.append(task)
    save_tasks(project_path, tasks)
    return task


def start_agent_task(
    project: str | Path,
    task_text: str,
    *,
    title: str = "",
    include_validation: bool = True,
    stop_on_failure: bool = False,
    agent_profile: str = "project",
    context_path: str = "",
    runtime_project: str | Path | None = None,
    requester_session_key: str = "",
    owner_key: str = "local",
    scope_kind: str = SCOPE_PROJECT,
    child_session_key: str = "",
    parent_task_id: str = "",
    notify_policy: str = NOTIFY_DONE_ONLY,
    cleanup_after: int | None = None,
) -> ResearchTask:
    project_path = Path(project).expanduser().resolve(strict=False)
    runtime_project_path = Path(runtime_project).expanduser().resolve(strict=False) if runtime_project else project_path
    task_text = task_text.strip()
    if not task_text:
        raise ValueError("agent task is empty")

    tasks = load_tasks(project_path)
    task_id = _next_runtime_id(tasks)
    out_dir = runtime_dir(project_path) / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    stdout = out_dir / "stdout.txt"
    stderr = out_dir / "stderr.txt"
    status = out_dir / "status.json"
    result = out_dir / "agent_result.json"
    payload = {
        "project": str(runtime_project_path),
        "task": task_text,
        "stdout": str(stdout),
        "stderr": str(stderr),
        "status": str(status),
        "result": str(result),
        "include_validation": include_validation,
        "stop_on_failure": stop_on_failure,
        "agent_profile": agent_profile,
        "context_path": context_path,
    }
    env = os.environ.copy()
    repo_root = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = repo_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    proc = subprocess.Popen(
        [sys.executable, "-c", AGENT_WORKER_CODE, json.dumps(payload, ensure_ascii=False)],
        cwd=project_path,
        env=env,
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    pid = proc.pid
    proc._child_created = False  # type: ignore[attr-defined]
    now = datetime.now().isoformat(timespec="seconds")
    evidence = [str(stdout), str(stderr), str(status), str(result)]
    if context_path:
        evidence.append(context_path)
    task = ResearchTask(
        id=task_id,
        title=title or task_text,
        detail="background local agent",
        kind="local_agent",
        status=RUNNING,
        pid=pid,
        command=["agent_v2", "--profile", agent_profile, task_text],
        output_path=str(stdout),
        error_path=str(stderr),
        status_path=str(status),
        requester_session_key=requester_session_key,
        owner_key=owner_key,
        scope_kind=scope_kind,
        child_session_key=child_session_key,
        parent_task_id=parent_task_id,
        notify_policy=notify_policy,
        cleanup_after=cleanup_after,
        created_at=now,
        updated_at=now,
        evidence=evidence,
        history=[{"status": RUNNING, "at": now, "note": "started local agent task", "pid": pid, "agent_profile": agent_profile, "context_path": context_path}],
    )
    if runtime_project_path != project_path:
        task.history[0]["runtime_project"] = str(runtime_project_path)
        task.detail = f"background local agent in isolated runtime project: {runtime_project_path}"
    reconcile_task_contract(task)
    tasks.append(task)
    save_tasks(project_path, tasks)
    return task


def refresh_runtime_tasks(project: str | Path) -> list[ResearchTask]:
    return reconcile_runtime_tasks(project)


def reconcile_runtime_tasks(project: str | Path) -> list[ResearchTask]:
    project_path = Path(project).expanduser().resolve(strict=False)
    tasks = load_tasks(project_path)
    changed = False
    for task in tasks:
        if task.kind not in {"shell", "local_agent"} or task.status != RUNNING:
            continue
        status = _read_status(task)
        if status:
            returncode = int(status.get("returncode", 127))
            task.status = PASSED if returncode == 0 else FAILED
            task.updated_at = datetime.now().isoformat(timespec="seconds")
            summary = _status_terminal_summary(status, returncode=returncode)
            reconcile_task_contract(task, summary=summary)
            task.history.append(
                {
                    "status": task.status,
                    "at": task.updated_at,
                    "note": summary,
                    "returncode": returncode,
                }
            )
            changed = True
        elif (task.pid and not _pid_alive(task.pid)) or not task.pid:
            task.status = LOST
            task.updated_at = datetime.now().isoformat(timespec="seconds")
            summary = "process ended without status file"
            reconcile_task_contract(task, summary=summary)
            task.history.append({"status": LOST, "at": task.updated_at, "note": summary})
            changed = True
    if changed:
        save_tasks(project_path, tasks)
    return tasks


def stop_runtime_task(project: str | Path, task_id: str) -> ResearchTask:
    project_path = Path(project).expanduser().resolve(strict=False)
    tasks = refresh_runtime_tasks(project_path)
    for task in tasks:
        if task.id != task_id:
            continue
        if task.kind in {"shell", "local_agent"} and task.status == RUNNING and task.pid:
            try:
                os.killpg(task.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        task.status = ABORTED
        task.updated_at = datetime.now().isoformat(timespec="seconds")
        reconcile_task_contract(task, summary="stop requested")
        task.history.append({"status": ABORTED, "at": task.updated_at, "note": "stop requested"})
        save_tasks(project_path, tasks)
        return task
    raise KeyError(f"task not found: {task_id}")


def get_runtime_task(project: str | Path, task_id: str, *, refresh: bool = True) -> ResearchTask:
    tasks = refresh_runtime_tasks(project) if refresh else load_tasks(Path(project).expanduser().resolve(strict=False))
    for task in tasks:
        if task.id == task_id:
            return task
    raise KeyError(f"task not found: {task_id}")


def resume_runtime_task(
    project: str | Path,
    task_id: str,
    *,
    title: str = "",
    allow_risky: bool = False,
    include_validation: bool = True,
    stop_on_failure: bool = False,
) -> ResearchTask:
    project_path = Path(project).expanduser().resolve(strict=False)
    task = get_runtime_task(project_path, task_id, refresh=True)
    if task.status == RUNNING:
        raise ValueError(f"task is already running: {task_id}")
    if task.kind == "shell" and task.command:
        return start_shell_task(
            project_path,
            task.command,
            title=title or f"resume: {task.title}",
            allow_risky=allow_risky,
        )
    if task.kind == "local_agent":
        profile, task_text = _agent_resume_spec(task)
        if not task_text:
            raise ValueError(f"local_agent task cannot be resumed without task text: {task_id}")
        return start_agent_task(
            project_path,
            task_text,
            title=title or f"resume: {task.title}",
            include_validation=include_validation,
            stop_on_failure=stop_on_failure,
            agent_profile=profile or "project",
            context_path=_latest_history_value(task, "context_path"),
            runtime_project=_latest_history_value(task, "runtime_project") or None,
        )
    if task.status == QUEUED:
        task.status = RUNNING
        task.updated_at = datetime.now().isoformat(timespec="seconds")
        task.history.append({"status": RUNNING, "at": task.updated_at, "note": "manual resume requested"})
        tasks = load_tasks(project_path)
        for index, item in enumerate(tasks):
            if item.id == task.id:
                tasks[index] = task
                save_tasks(project_path, tasks)
                return task
    raise ValueError(f"task kind cannot be resumed automatically: {task.kind}")


def read_task_output(project: str | Path, task_id: str, *, stream: str = "stdout", tail_chars: int = 4000) -> str:
    tasks = refresh_runtime_tasks(project)
    for task in tasks:
        if task.id == task_id:
            raw_path = task.error_path if stream == "stderr" else task.output_path
            if not raw_path:
                return _fallback_task_output(task, tail_chars=tail_chars)
            path = Path(raw_path)
            if not path.exists() or path.is_dir():
                if task.kind == "local_agent" and stream == "stdout":
                    return _render_agent_task_status(task, tail_chars=tail_chars)
                return _fallback_task_output(task, tail_chars=tail_chars)
            text = path.read_text(encoding="utf-8", errors="replace")
            if not text and task.kind == "local_agent" and stream == "stdout":
                return _render_agent_task_status(task, tail_chars=tail_chars)
            return text[-max(0, tail_chars) :]
    raise KeyError(f"task not found: {task_id}")


def render_task_detail(task: ResearchTask, *, output_preview: str = "", subagent: dict[str, Any] | None = None) -> str:
    lines = [
        "# Mako Task",
        "",
        f"- id: {task.id}",
        f"- status: {task.status}",
        f"- kind: {task.kind}",
        f"- title: {task.title}",
        f"- pid: {task.pid if task.pid is not None else '-'}",
        f"- created_at: {task.created_at}",
        f"- updated_at: {task.updated_at}",
    ]
    lines.extend(
        [
            "",
            "## Registry",
            "",
            f"- owner_key: {task.owner_key}",
            f"- scope_kind: {task.scope_kind}",
            f"- requester_session_key: {task.requester_session_key or '-'}",
            f"- child_session_key: {task.child_session_key or '-'}",
            f"- parent_task_id: {task.parent_task_id or '-'}",
            f"- delivery_status: {task.delivery_status}",
            f"- notify_policy: {task.notify_policy}",
            f"- terminal_outcome: {task.terminal_outcome or '-'}",
            f"- terminal_summary: {task.terminal_summary or '-'}",
            f"- cleanup_after: {task.cleanup_after if task.cleanup_after is not None else '-'}",
        ]
    )
    if task.detail:
        lines.extend(["", "## Detail", "", task.detail])
    if task.command:
        lines.extend(["", "## Command", "", "```", shlex.join(task.command), "```"])
    if task.output_path or task.error_path or task.status_path:
        lines.extend(["", "## Runtime Paths", ""])
        if task.output_path:
            lines.append(f"- stdout: {task.output_path}")
        if task.error_path:
            lines.append(f"- stderr: {task.error_path}")
        if task.status_path:
            lines.append(f"- status: {task.status_path}")
    if subagent:
        lines.extend(["", "## Subagent", ""])
        for key in ("subagent_id", "parent_task_id", "child_session_id", "agent_profile", "context_mode", "review_id", "terminal_outcome"):
            value = subagent.get(key)
            if value:
                lines.append(f"- {key}: {value}")
    lines.extend(["", "## Evidence", ""])
    lines.extend(f"- {item}" for item in task.evidence) if task.evidence else lines.append("- none")
    lines.extend(["", "## History", ""])
    if task.history:
        for item in task.history[-20:]:
            note = f" note={item.get('note')}" if item.get("note") else ""
            lines.append(f"- {item.get('at', '-')} status={item.get('status', '-')}{note}")
    else:
        lines.append("- none")
    if output_preview:
        lines.extend(["", "## Output Preview", "", "```", output_preview.rstrip(), "```"])
    return "\n".join(lines).rstrip() + "\n"


def _create_blocked_task(
    project: Path,
    title: str,
    command: list[str],
    reason: str,
    *,
    requester_session_key: str = "",
    owner_key: str = "local",
    scope_kind: str = SCOPE_PROJECT,
    child_session_key: str = "",
    parent_task_id: str = "",
    notify_policy: str = NOTIFY_DONE_ONLY,
    cleanup_after: int | None = None,
) -> ResearchTask:
    tasks = load_tasks(project)
    task_id = _next_runtime_id(tasks)
    now = datetime.now().isoformat(timespec="seconds")
    task = ResearchTask(
        id=task_id,
        title=title,
        detail=reason,
        kind="shell",
        status=BLOCKED,
        command=command,
        requester_session_key=requester_session_key,
        owner_key=owner_key,
        scope_kind=scope_kind,
        child_session_key=child_session_key,
        parent_task_id=parent_task_id,
        notify_policy=notify_policy,
        cleanup_after=cleanup_after,
        created_at=now,
        updated_at=now,
        history=[{"status": BLOCKED, "at": now, "note": reason}],
    )
    reconcile_task_contract(task, summary=reason)
    tasks.append(task)
    save_tasks(project, tasks)
    return task


def _next_runtime_id(tasks: list[ResearchTask]) -> str:
    max_id = 0
    for task in tasks:
        if task.id.startswith("qrt-"):
            try:
                max_id = max(max_id, int(task.id.removeprefix("qrt-")))
            except ValueError:
                pass
    return f"qrt-{max_id + 1:04d}"


def _read_status(task: ResearchTask) -> dict[str, Any]:
    if not task.status_path:
        return {}
    path = Path(task.status_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _render_agent_task_status(task: ResearchTask, *, tail_chars: int) -> str:
    status = _read_status(task)
    if not status:
        return ""
    lines = [
        f"status: {task.status}",
        f"returncode: {status.get('returncode', '')}",
    ]
    if status.get("summary"):
        lines.extend(["summary:", str(status["summary"])])
    if status.get("failure_class"):
        lines.append(f"failure_class: {status['failure_class']}")
    for key in ("result_path", "trajectory_path", "query_events_path"):
        if status.get(key):
            lines.append(f"{key}: {status[key]}")
    return ("\n".join(lines) + "\n")[-max(0, tail_chars) :]


def _status_terminal_summary(status: dict[str, Any], *, returncode: int) -> str:
    summary = str(status.get("summary") or "").strip()
    if summary:
        return summary
    error = str(status.get("error") or "").strip()
    if error:
        return error
    return f"finished with returncode {returncode}"


def _fallback_task_output(task: ResearchTask, *, tail_chars: int) -> str:
    pieces = []
    if task.detail:
        pieces.append(task.detail)
    if task.history:
        latest = task.history[-1]
        note = latest.get("note")
        if note:
            pieces.append(str(note))
    return ("\n".join(dict.fromkeys(pieces)) + ("\n" if pieces else ""))[-max(0, tail_chars) :]


def _agent_resume_spec(task: ResearchTask) -> tuple[str, str]:
    profile = "project"
    task_text = ""
    if task.command:
        if "--profile" in task.command:
            index = task.command.index("--profile")
            if index + 1 < len(task.command):
                profile = task.command[index + 1]
        if task.command[0] == "agent_v2" and len(task.command) >= 4:
            task_text = task.command[-1]
    return profile, task_text


def _latest_history_value(task: ResearchTask, key: str) -> str:
    for item in reversed(task.history):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
