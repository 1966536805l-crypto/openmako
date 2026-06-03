from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .relay import MESSAGE_DONE, MESSAGE_FAILED, AgentMessage, mark_done, mark_failed, poll_once


HeadlessRunner = Callable[..., Any]


def run_relay_worker_once(
    project: str | Path,
    *,
    agent_id: str,
    backend: str = "headless",
    headless_runner: HeadlessRunner | None = None,
    lease_seconds: float = 300.0,
) -> dict[str, Any]:
    """Claim one relay message, run a bounded backend, and submit with the claimed lease."""

    project_path = Path(project)
    message = poll_once(project_path, agent_id, requester_agent=agent_id, lease_seconds=lease_seconds)
    if message is None:
        return {"ok": True, "status": "empty", "agent_id": agent_id, "message_id": "", "lease_id": ""}
    try:
        if backend != "headless":
            raise ValueError(f"unsupported relay worker backend: {backend}")
        if headless_runner is None:
            raise ValueError("headless_runner is required for backend=headless")
        task = _bounded_task_text(message)
        raw = headless_runner(project_path, task, agent_id=agent_id, message_id=message.id, task_id=message.task_id, message_type=message.type)
        output = _result_payload(raw)
        output.pop("lease_id", None)
        done = mark_done(project_path, agent_id, message.id, output, lease_id=message.lease_id)
        return {
            "ok": True,
            "status": MESSAGE_DONE,
            "agent_id": agent_id,
            "message_id": done.id,
            "task_id": done.task_id,
            "lease_id": message.lease_id,
            "summary": str(output.get("summary") or "done"),
        }
    except Exception as exc:  # noqa: BLE001 - worker must fail closed into relay state.
        output = {"ok": False, "summary": f"{type(exc).__name__}: {exc}", "error": str(exc)}
        try:
            failed = mark_failed(project_path, agent_id, message.id, output, lease_id=message.lease_id)
            message_id = failed.id
        except Exception:
            message_id = message.id
        return {
            "ok": False,
            "status": MESSAGE_FAILED,
            "agent_id": agent_id,
            "message_id": message_id,
            "task_id": message.task_id,
            "lease_id": message.lease_id,
            "summary": output["summary"],
        }


def _bounded_task_text(message: AgentMessage) -> str:
    payload = dict(message.payload)
    if isinstance(payload.get("lines"), list):
        lines = [str(item) for item in payload.get("lines", [])][:10]
        return "\n".join(lines)
    parts = [f"task_id: {message.task_id}", f"type: {message.type}"]
    for key in ("goal", "diff_summary", "test_result", "changed_files", "success_criteria"):
        if key in payload:
            parts.append(f"{key}: {_compact(payload[key])}")
    return "\n".join(parts[:10])


def _result_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        payload = value.to_dict()
        return dict(payload) if isinstance(payload, dict) else {"summary": str(payload)}
    if hasattr(value, "to_payload") and callable(value.to_payload):
        payload = value.to_payload()
        return dict(payload) if isinstance(payload, dict) else {"summary": str(payload)}
    ok = bool(getattr(value, "ok", True))
    summary = str(getattr(value, "summary", "done"))
    return {"ok": ok, "summary": summary}


def _compact(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value[:8])
    if isinstance(value, dict):
        return ", ".join(f"{key}={value[key]}" for key in list(value)[:8])
    return str(value)
