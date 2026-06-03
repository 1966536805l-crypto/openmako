from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .event_log import append_runtime_event
from .runtime_store import end_session, list_runtime_sessions, upsert_session
from .sessions import append_message, create_session


@dataclass(frozen=True)
class SessionBusState:
    bus_id: str
    project: str
    status: str
    started_at_ms: int
    updated_at_ms: int
    owner: str = "local"
    channels: tuple[str, ...] = ("cli",)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["channels"] = list(self.channels)
        return payload


@dataclass(frozen=True)
class BusMessage:
    message_id: str
    session_id: str
    channel: str
    sender: str
    target: str
    content: str
    created_at_ms: int
    status: str = "queued"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def session_bus_dir(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "session_bus"


def session_bus_state_path(project: str | Path) -> Path:
    return session_bus_dir(project) / "state.json"


def session_bus_messages_path(project: str | Path) -> Path:
    return session_bus_dir(project) / "messages.jsonl"


def start_session_bus(project: str | Path, *, owner: str = "local", channels: Iterable[str] = ("cli",)) -> SessionBusState:
    project_path = Path(project).expanduser().resolve(strict=False)
    old = status_session_bus(project_path)
    now = _now_ms()
    state = SessionBusState(
        bus_id=old.bus_id or "bus-" + uuid.uuid4().hex[:12],
        project=str(project_path),
        status="running",
        started_at_ms=old.started_at_ms or now,
        updated_at_ms=now,
        owner=owner,
        channels=tuple(dict.fromkeys(str(item) for item in channels if str(item).strip())) or ("cli",),
    )
    _write_state(project_path, state)
    append_runtime_event(project_path, kind="system", summary="session bus started", status="succeeded", data=state.to_dict())
    return state


def stop_session_bus(project: str | Path, *, reason: str = "") -> SessionBusState:
    project_path = Path(project).expanduser().resolve(strict=False)
    old = status_session_bus(project_path)
    now = _now_ms()
    state = SessionBusState(
        bus_id=old.bus_id or "bus-" + uuid.uuid4().hex[:12],
        project=str(project_path),
        status="stopped",
        started_at_ms=old.started_at_ms or now,
        updated_at_ms=now,
        owner=old.owner,
        channels=old.channels,
    )
    _write_state(project_path, state)
    append_runtime_event(project_path, kind="system", summary="session bus stopped", status="succeeded", data={"reason": reason})
    return state


def status_session_bus(project: str | Path) -> SessionBusState:
    project_path = Path(project).expanduser().resolve(strict=False)
    path = session_bus_state_path(project_path)
    if not path.exists():
        return SessionBusState("", str(project_path), "stopped", 0, 0, channels=())
    data = json.loads(path.read_text(encoding="utf-8"))
    return SessionBusState(
        bus_id=str(data.get("bus_id") or ""),
        project=str(data.get("project") or project_path),
        status=str(data.get("status") or "stopped"),
        started_at_ms=int(data.get("started_at_ms") or 0),
        updated_at_ms=int(data.get("updated_at_ms") or 0),
        owner=str(data.get("owner") or "local"),
        channels=tuple(str(item) for item in data.get("channels") or ()),
    )


def send_bus_message(
    project: str | Path,
    *,
    channel: str,
    sender: str,
    content: str,
    session_id: str = "",
    target: str = "agent",
    metadata: dict[str, Any] | None = None,
) -> BusMessage:
    project_path = Path(project).expanduser().resolve(strict=False)
    if not content.strip():
        raise ValueError("message content is required")
    if status_session_bus(project_path).status != "running":
        start_session_bus(project_path, channels=(channel,))
    if not session_id:
        session = create_session(project_path, title=f"{channel}:{sender}")
        session_id = session.session_id
    else:
        upsert_session(project_path, session_id=session_id, source=f"bus:{channel}", title=session_id, project_path=str(project_path))
    message = BusMessage(
        message_id="msg-" + uuid.uuid4().hex[:16],
        session_id=session_id,
        channel=channel,
        sender=sender,
        target=target,
        content=content,
        created_at_ms=_now_ms(),
        metadata=dict(metadata or {}),
    )
    _append_message_record(project_path, message)
    append_message(
        project_path,
        session_id,
        "user" if target == "agent" else "assistant",
        content,
        meta={"channel": channel, "sender": sender, "target": target, "bus_message_id": message.message_id, **message.metadata},
    )
    append_runtime_event(
        project_path,
        kind="message",
        summary=f"bus message {channel}:{sender} -> {target}",
        status="queued",
        session_id=session_id,
        correlation_id=message.message_id,
        data=message.to_dict(),
    )
    return message


def list_bus_messages(project: str | Path, *, session_id: str = "", channel: str = "", limit: int = 50) -> list[BusMessage]:
    path = session_bus_messages_path(project)
    if not path.exists():
        return []
    messages: list[BusMessage] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            data = json.loads(line)
            message = BusMessage(
                message_id=str(data.get("message_id") or ""),
                session_id=str(data.get("session_id") or ""),
                channel=str(data.get("channel") or ""),
                sender=str(data.get("sender") or ""),
                target=str(data.get("target") or ""),
                content=str(data.get("content") or ""),
                created_at_ms=int(data.get("created_at_ms") or 0),
                status=str(data.get("status") or "queued"),
                metadata=dict(data.get("metadata") or {}),
            )
            if session_id and message.session_id != session_id:
                continue
            if channel and message.channel != channel:
                continue
            messages.append(message)
    return messages[-limit:] if limit > 0 else messages


def close_bus_session(project: str | Path, session_id: str, *, reason: str = "") -> None:
    project_path = Path(project).expanduser().resolve(strict=False)
    end_session(project_path, session_id, reason=reason)
    append_runtime_event(project_path, kind="message", summary=f"session bus closed {session_id}", status="succeeded", session_id=session_id, data={"reason": reason})


def render_session_bus_state(state: SessionBusState) -> str:
    lines = [
        "# Mako Session Bus",
        "",
        f"- bus_id: {state.bus_id or '(not started)'}",
        f"- status: {state.status}",
        f"- owner: {state.owner}",
        f"- channels: {', '.join(state.channels) if state.channels else '(none)'}",
        f"- updated_at_ms: {state.updated_at_ms}",
    ]
    return "\n".join(lines) + "\n"


def render_bus_messages(messages: Iterable[BusMessage]) -> str:
    items = list(messages)
    if not items:
        return "No session bus messages.\n"
    lines = ["# Session Bus Messages", ""]
    for message in items:
        preview = " ".join(message.content.split())
        if len(preview) > 180:
            preview = preview[:177] + "..."
        lines.append(f"- [{message.status}] {message.message_id} session={message.session_id} {message.channel}:{message.sender}->{message.target}: {preview}")
    return "\n".join(lines) + "\n"


def session_bus_summary(project: str | Path) -> dict[str, Any]:
    state = status_session_bus(project)
    messages = list_bus_messages(project, limit=200)
    sessions = list_runtime_sessions(project, limit=50)
    return {
        "state": state.to_dict(),
        "messages": len(messages),
        "sessions": len(sessions),
        "channels": sorted(set(message.channel for message in messages)),
    }


def _write_state(project: Path, state: SessionBusState) -> None:
    path = session_bus_state_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_message_record(project: Path, message: BusMessage) -> None:
    path = session_bus_messages_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(message.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def _now_ms() -> int:
    return int(time.time() * 1000)
