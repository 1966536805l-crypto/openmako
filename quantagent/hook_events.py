from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


QUERY_EVENT_KINDS = frozenset(
    {
        "query_start",
        "hook",
        "user_prompt_submit",
        "pre_model",
        "post_model",
        "pre_tool",
        "post_tool",
        "post_tool_batch",
        "stop",
        "stop_failure",
        "file_changed",
        "pre_compact",
        "post_compact",
        "session_end",
        "resume_snapshot",
        "edit_auto",
        "code_index_diagnostic",
        "plugin_diagnostic",
        "worktree_isolation",
        "ux_status",
    }
)


@dataclass(frozen=True)
class QueryEvent:
    kind: str
    query_id: str
    summary: str = ""
    step: int | None = None
    name: str = ""
    ok: bool | None = None
    timestamp: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=lambda: "qevt-" + uuid.uuid4().hex[:16])

    def to_dict(self) -> dict[str, Any]:
        _validate_kind(self.kind)
        payload = asdict(self)
        if not payload["timestamp"]:
            payload["timestamp"] = utc_timestamp()
        payload["data"] = stable_json_data(payload["data"])
        return payload


def normalize_query_event(event: QueryEvent | Mapping[str, Any]) -> QueryEvent:
    if isinstance(event, QueryEvent):
        _validate_kind(event.kind)
        return event
    kind = str(event.get("kind") or "")
    _validate_kind(kind)
    data = event.get("data") or {}
    if not isinstance(data, Mapping):
        raise ValueError("query event data must be an object")
    return QueryEvent(
        kind=kind,
        query_id=str(event.get("query_id") or ""),
        summary=str(event.get("summary") or ""),
        step=_normalize_step(event.get("step")),
        name=str(event.get("name") or ""),
        ok=_normalize_ok(event.get("ok")),
        timestamp=str(event.get("timestamp") or ""),
        data=stable_json_data(data),
        event_id=str(event.get("event_id") or ""),
    )


def append_query_event(path: str | Path, event: QueryEvent | Mapping[str, Any]) -> QueryEvent:
    normalized = normalize_query_event(event)
    if not normalized.event_id:
        normalized = replace(normalized, event_id="qevt-" + uuid.uuid4().hex[:16])
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = normalized.to_dict()
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    return normalize_query_event(payload)


def read_query_events(path: str | Path) -> list[QueryEvent]:
    target = Path(path)
    if not target.exists():
        return []
    events: list[QueryEvent] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid query event JSONL at line {line_number}: {exc.msg}") from exc
            if not isinstance(payload, Mapping):
                raise ValueError(f"Invalid query event JSONL at line {line_number}: expected object")
            events.append(normalize_query_event(payload))
    return events


def stable_json_data(data: Mapping[str, Any]) -> dict[str, Any]:
    stable: dict[str, Any] = {}
    for key, value in sorted((str(key), value) for key, value in data.items()):
        stable[key] = _json_safe(value)
    return stable


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _validate_kind(kind: str) -> None:
    if kind not in QUERY_EVENT_KINDS:
        allowed = ", ".join(sorted(QUERY_EVENT_KINDS))
        raise ValueError(f"Unknown query event kind {kind!r}; expected one of: {allowed}")


def _normalize_step(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("query event step must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("query event step must be an integer") from exc


def _normalize_ok(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    raise ValueError("query event ok must be true, false, or null")


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        return value
    except TypeError:
        return str(value)
