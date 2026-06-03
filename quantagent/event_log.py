from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .redaction import redact_for_llm


EVENT_LOG_VERSION = 2
EVENT_KINDS = frozenset(
    {
        "message",
        "tool_call",
        "tool_result",
        "approval",
        "diff",
        "test",
        "diagnostic",
        "task",
        "memory",
        "mcp",
        "lsp",
        "checkpoint",
        "system",
    }
)
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "blocked", "cancelled"})


@dataclass(frozen=True)
class RuntimeEvent:
    event_id: str
    kind: str
    summary: str
    timestamp_ms: int
    status: str = "observed"
    actor: str = "quantagent"
    session_id: str = ""
    task_id: str = ""
    parent_event_id: str = ""
    correlation_id: str = ""
    tool: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[str, ...] = ()
    schema_version: int = EVENT_LOG_VERSION

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifacts"] = list(self.artifacts)
        payload["data"] = redact_for_llm(self.data, max_items=30, max_string_chars=4000)
        return payload


@dataclass(frozen=True)
class EventLogStats:
    count: int
    by_kind: dict[str, int]
    by_status: dict[str, int]
    first_timestamp_ms: int | None = None
    last_timestamp_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def event_log_dir(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "events"


def event_log_path(project: str | Path) -> Path:
    return event_log_dir(project) / "events.jsonl"


def append_runtime_event(
    project: str | Path,
    *,
    kind: str,
    summary: str,
    status: str = "observed",
    actor: str = "quantagent",
    session_id: str = "",
    task_id: str = "",
    parent_event_id: str = "",
    correlation_id: str = "",
    tool: str = "",
    data: Mapping[str, Any] | None = None,
    artifacts: Iterable[str | Path] = (),
    event_id: str = "",
    timestamp_ms: int | None = None,
) -> RuntimeEvent:
    event = normalize_runtime_event(
        {
            "event_id": event_id or _new_event_id(),
            "kind": kind,
            "summary": summary,
            "timestamp_ms": timestamp_ms or _now_ms(),
            "status": status,
            "actor": actor,
            "session_id": session_id,
            "task_id": task_id,
            "parent_event_id": parent_event_id,
            "correlation_id": correlation_id,
            "tool": tool,
            "data": dict(data or {}),
            "artifacts": [str(item) for item in artifacts],
            "schema_version": EVENT_LOG_VERSION,
        }
    )
    path = event_log_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return event


def read_runtime_events(
    project_or_path: str | Path,
    *,
    kind: str | None = None,
    status: str | None = None,
    session_id: str | None = None,
    task_id: str | None = None,
    correlation_id: str | None = None,
    limit: int = 200,
) -> list[RuntimeEvent]:
    path = Path(project_or_path).expanduser().resolve(strict=False)
    if path.is_dir():
        path = event_log_path(path)
    if not path.exists():
        return []
    events: list[RuntimeEvent] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid event log JSONL at line {line_number}: {exc.msg}") from exc
            if not isinstance(payload, Mapping):
                raise ValueError(f"Invalid event log JSONL at line {line_number}: expected object")
            event = normalize_runtime_event(payload)
            if kind and event.kind != kind:
                continue
            if status and event.status != status:
                continue
            if session_id and event.session_id != session_id:
                continue
            if task_id and event.task_id != task_id:
                continue
            if correlation_id and event.correlation_id != correlation_id:
                continue
            events.append(event)
    if limit > 0:
        return events[-limit:]
    return events


def normalize_runtime_event(event: RuntimeEvent | Mapping[str, Any]) -> RuntimeEvent:
    if isinstance(event, RuntimeEvent):
        _validate_kind(event.kind)
        return event
    kind = str(event.get("kind") or "").strip()
    _validate_kind(kind)
    summary = " ".join(str(event.get("summary") or "").split())
    if not summary:
        raise ValueError("runtime event summary is required")
    data = event.get("data") or {}
    if not isinstance(data, Mapping):
        raise ValueError("runtime event data must be an object")
    artifacts_value = event.get("artifacts") or ()
    if not isinstance(artifacts_value, (list, tuple)):
        raise ValueError("runtime event artifacts must be an array")
    return RuntimeEvent(
        event_id=str(event.get("event_id") or event.get("id") or _new_event_id()),
        kind=kind,
        summary=summary,
        timestamp_ms=_coerce_ms(event.get("timestamp_ms") or event.get("timestamp")) or _now_ms(),
        status=str(event.get("status") or "observed"),
        actor=str(event.get("actor") or "quantagent"),
        session_id=str(event.get("session_id") or ""),
        task_id=str(event.get("task_id") or ""),
        parent_event_id=str(event.get("parent_event_id") or ""),
        correlation_id=str(event.get("correlation_id") or event.get("query_id") or ""),
        tool=str(event.get("tool") or ""),
        data=dict(data),
        artifacts=tuple(str(item) for item in artifacts_value),
        schema_version=int(event.get("schema_version") or EVENT_LOG_VERSION),
    )


def event_log_stats(events: Iterable[RuntimeEvent | Mapping[str, Any]]) -> EventLogStats:
    normalized = [normalize_runtime_event(event) for event in events]
    by_kind: dict[str, int] = {}
    by_status: dict[str, int] = {}
    timestamps: list[int] = []
    for event in normalized:
        by_kind[event.kind] = by_kind.get(event.kind, 0) + 1
        by_status[event.status] = by_status.get(event.status, 0) + 1
        timestamps.append(event.timestamp_ms)
    return EventLogStats(
        count=len(normalized),
        by_kind=dict(sorted(by_kind.items())),
        by_status=dict(sorted(by_status.items())),
        first_timestamp_ms=min(timestamps) if timestamps else None,
        last_timestamp_ms=max(timestamps) if timestamps else None,
    )


def render_event_log(events: Iterable[RuntimeEvent | Mapping[str, Any]], *, limit: int = 40) -> str:
    normalized = [normalize_runtime_event(event) for event in events]
    selected = normalized[-limit:] if limit > 0 else normalized
    if not selected:
        return "No runtime events.\n"
    lines = ["# Mako Event Log", ""]
    for event in selected:
        prefix = f"- [{event.kind}/{event.status}] {event.event_id}"
        suffix = f" tool={event.tool}" if event.tool else ""
        session = f" session={event.session_id}" if event.session_id else ""
        task = f" task={event.task_id}" if event.task_id else ""
        lines.append(f"{prefix}{suffix}{session}{task}: {event.summary}")
        if event.artifacts:
            lines.append("  artifacts: " + ", ".join(event.artifacts[:5]))
    return "\n".join(lines) + "\n"


def replay_summary(events: Iterable[RuntimeEvent | Mapping[str, Any]], *, max_lines: int = 20) -> str:
    normalized = [normalize_runtime_event(event) for event in events]
    if not normalized:
        return "No replayable events."
    terminal = [event for event in normalized if event.status in TERMINAL_STATUSES]
    failed = [event for event in normalized if event.status in {"failed", "blocked"}]
    lines = [
        f"Runtime replay has {len(normalized)} event(s), {len(terminal)} terminal event(s), {len(failed)} failure/block event(s)."
    ]
    for event in normalized[-max_lines:]:
        lines.append(f"- {event.kind}/{event.status}: {event.summary}")
    return "\n".join(lines)


def export_events(
    events: Iterable[RuntimeEvent | Mapping[str, Any]],
    *,
    output_format: str = "json",
) -> str:
    normalized = [normalize_runtime_event(event) for event in events]
    if output_format == "jsonl":
        return "".join(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n" for event in normalized)
    if output_format == "markdown":
        return render_event_log(normalized, limit=0)
    if output_format != "json":
        raise ValueError(f"unsupported event export format: {output_format}")
    return json.dumps([event.to_dict() for event in normalized], ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _validate_kind(kind: str) -> None:
    if kind not in EVENT_KINDS:
        allowed = ", ".join(sorted(EVENT_KINDS))
        raise ValueError(f"unknown runtime event kind {kind!r}; expected one of: {allowed}")


def _new_event_id() -> str:
    return "evt-" + uuid.uuid4().hex[:16]


def _now_ms() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _coerce_ms(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number > 10_000_000_000 else number * 1000
    text = str(value)
    if text.isdigit():
        return _coerce_ms(int(text))
    try:
        return int(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None
