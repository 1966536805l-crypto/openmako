from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .hook_events import QueryEvent, read_query_events
from .trajectory import TrajectoryEvent, read_events


ROLE_MAP = {
    "system": "system",
    "developer": "system",
    "user": "human",
    "human": "human",
    "assistant": "gpt",
    "gpt": "gpt",
    "tool": "tool",
    "function": "tool",
}


def build_hermes_trajectory_entry(
    messages: Iterable[Any] | None = None,
    *,
    model: str = "",
    completed: bool | None = None,
    timestamp: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    query_events: Iterable[Any] | None = None,
    trajectory_events: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Build one ShareGPT-compatible Hermes trajectory JSONL object."""
    query_list = [_normalize_query_event(event) for event in (query_events or [])]
    trajectory_list = [_normalize_trajectory_event(event) for event in (trajectory_events or [])]
    conversation_source = list(messages or [])
    if not conversation_source:
        conversation_source = _messages_from_query_events(query_list)
    if not conversation_source:
        conversation_source = _messages_from_trajectory_events(trajectory_list)

    resolved_completed = _resolve_completed(completed, query_list, trajectory_list)
    entry_metadata = _stable_json_data(metadata or {})
    if query_list:
        entry_metadata.setdefault("query_id", _last_nonempty(event.query_id for event in query_list))
        entry_metadata.setdefault("query_event_count", len(query_list))
        failure_class = _last_nonempty(str(event.data.get("failure_class") or "") for event in query_list)
        if failure_class:
            entry_metadata.setdefault("failure_class", failure_class)
    if trajectory_list:
        entry_metadata.setdefault("trajectory_event_count", len(trajectory_list))
        failed_count = sum(1 for event in trajectory_list if event.ok is False)
        if failed_count:
            entry_metadata.setdefault("failed_trajectory_events", failed_count)

    return {
        "conversations": normalize_sharegpt_conversations(conversation_source),
        "timestamp": timestamp or _utc_timestamp(),
        "model": str(model or _model_from_query_events(query_list)),
        "completed": resolved_completed,
        "metadata": entry_metadata,
    }


def normalize_sharegpt_conversations(messages: Iterable[Any]) -> list[dict[str, str]]:
    conversations: list[dict[str, str]] = []
    for item in messages:
        message = _to_mapping(item)
        role = _map_role(str(message.get("role") or message.get("from") or ""))
        if not role:
            continue
        value = _message_value(message, role)
        if value == "" and role != "tool":
            continue
        conversations.append({"from": role, "value": value})
    return conversations


def append_hermes_jsonl(path: str | Path, entry: Mapping[str, Any]) -> None:
    normalized = normalize_hermes_entry(entry)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def read_hermes_jsonl(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    entries: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid Hermes trajectory JSONL at line {line_number}: {exc.msg}") from exc
            if not isinstance(payload, Mapping):
                raise ValueError(f"Invalid Hermes trajectory JSONL at line {line_number}: expected object")
            entries.append(normalize_hermes_entry(payload))
    return entries


def export_hermes_jsonl(
    path: str | Path,
    *,
    messages: Iterable[Any] | None = None,
    model: str = "",
    completed: bool | None = None,
    timestamp: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    query_events: Iterable[Any] | None = None,
    trajectory_events: Iterable[Any] | None = None,
) -> dict[str, Any]:
    entry = build_hermes_trajectory_entry(
        messages,
        model=model,
        completed=completed,
        timestamp=timestamp,
        metadata=metadata,
        query_events=query_events,
        trajectory_events=trajectory_events,
    )
    append_hermes_jsonl(path, entry)
    return entry


def export_hermes_jsonl_from_paths(
    path: str | Path,
    *,
    query_events_path: str | Path | None = None,
    trajectory_path: str | Path | None = None,
    model: str = "",
    completed: bool | None = None,
    timestamp: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    query_events = read_query_events(query_events_path) if query_events_path else []
    trajectory_events = read_events(trajectory_path) if trajectory_path else []
    return export_hermes_jsonl(
        path,
        model=model,
        completed=completed,
        timestamp=timestamp,
        metadata=metadata,
        query_events=query_events,
        trajectory_events=trajectory_events,
    )


def normalize_hermes_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    conversations = entry.get("conversations") or []
    if not isinstance(conversations, list):
        raise ValueError("Hermes trajectory entry conversations must be a list")
    metadata = entry.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        raise ValueError("Hermes trajectory entry metadata must be an object")
    return {
        "conversations": normalize_sharegpt_conversations(conversations),
        "timestamp": str(entry.get("timestamp") or ""),
        "model": str(entry.get("model") or ""),
        "completed": bool(entry.get("completed")),
        "metadata": _stable_json_data(metadata),
    }


def _message_value(message: Mapping[str, Any], role: str) -> str:
    content = _string_content(message.get("value") if "value" in message else message.get("content"))
    reasoning = str(message.get("reasoning") or message.get("reasoning_summary") or "").strip()
    parts: list[str] = []
    if role == "gpt" and reasoning:
        parts.append(_xml_block("think", reasoning))
    if content:
        parts.append(convert_scratchpad_to_think(content))
    if role == "gpt":
        parts.extend(_tool_call_blocks(message.get("tool_calls")))
    if role == "tool":
        return _tool_response_block(message, content)
    return "\n\n".join(part for part in parts if part).strip()


def convert_scratchpad_to_think(content: str) -> str:
    text = str(content or "")
    return text.replace("<scratchpad>", "<think>").replace("</scratchpad>", "</think>")


def _tool_call_blocks(tool_calls: Any) -> list[str]:
    if not tool_calls:
        return []
    if isinstance(tool_calls, str):
        try:
            tool_calls = json.loads(tool_calls)
        except json.JSONDecodeError:
            return [_xml_block("tool_call", tool_calls)]
    if isinstance(tool_calls, Mapping):
        tool_calls = [tool_calls]
    if not isinstance(tool_calls, list):
        return []

    blocks: list[str] = []
    for tool_call in tool_calls:
        if not isinstance(tool_call, Mapping):
            continue
        payload = _normalize_tool_call(tool_call)
        blocks.append(_xml_block("tool_call", json.dumps(payload, ensure_ascii=False, sort_keys=True)))
    return blocks


def _normalize_tool_call(tool_call: Mapping[str, Any]) -> dict[str, Any]:
    function = tool_call.get("function")
    if isinstance(function, Mapping):
        name = str(function.get("name") or tool_call.get("name") or "")
        arguments = function.get("arguments", {})
    else:
        name = str(tool_call.get("name") or tool_call.get("tool") or "")
        arguments = tool_call.get("arguments", tool_call.get("args", {}))
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments.strip() else {}
        except json.JSONDecodeError:
            arguments = {"raw": arguments}
    return {
        "id": str(tool_call.get("id") or tool_call.get("tool_call_id") or ""),
        "name": name,
        "arguments": _json_safe(arguments),
    }


def _tool_response_block(message: Mapping[str, Any], content: str) -> str:
    payload = {
        "tool_call_id": str(message.get("tool_call_id") or ""),
        "name": str(message.get("name") or message.get("tool_name") or message.get("tool") or ""),
        "content": _json_content(content),
    }
    if "ok" in message:
        payload["ok"] = message.get("ok")
    data = message.get("data")
    if isinstance(data, Mapping) and data:
        payload["data"] = _stable_json_data(data)
    return _xml_block("tool_response", json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _messages_from_query_events(events: list[QueryEvent]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for event in events:
        if event.kind == "query_start":
            task = str(event.data.get("task") or event.summary or "")
            if task:
                messages.append({"role": "user", "content": task})
        elif event.kind == "user_prompt_submit":
            prompt = str(event.data.get("prompt") or event.data.get("preview") or event.summary or "")
            if prompt:
                messages.append({"role": "user", "content": prompt})
        elif event.kind == "post_model" and event.summary:
            messages.append({"role": "assistant", "content": event.summary})
        elif event.kind == "pre_tool":
            messages.append({"role": "assistant", "tool_calls": [{"name": event.name, "arguments": event.data.get("args") or {}}]})
        elif event.kind == "post_tool":
            messages.append({"role": "tool", "name": event.name, "content": event.summary, "ok": event.ok, "data": event.data})
    return messages


def _messages_from_trajectory_events(events: list[TrajectoryEvent]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for event in events:
        if event.kind == "observation":
            messages.append({"role": "tool", "name": str(event.meta.get("tool") or event.kind), "content": event.content, "ok": event.ok, "data": event.meta})
        else:
            content = event.content
            if event.step is not None:
                content = f"[{event.kind} step={event.step}] {content}"
            messages.append({"role": "assistant", "content": content})
    return messages


def _resolve_completed(completed: bool | None, query_events: list[QueryEvent], trajectory_events: list[TrajectoryEvent]) -> bool:
    if completed is not None:
        return bool(completed)
    for event in reversed(query_events):
        if event.kind in {"stop", "stop_failure"} and event.ok is not None:
            return bool(event.ok)
    if any(event.ok is False for event in trajectory_events):
        return False
    return True


def _model_from_query_events(events: list[QueryEvent]) -> str:
    for event in reversed(events):
        model = str(event.data.get("model") or "")
        if model:
            return model
    return ""


def _normalize_query_event(event: Any) -> QueryEvent:
    if isinstance(event, QueryEvent):
        return event
    data = _to_mapping(event)
    return QueryEvent(
        kind=str(data.get("kind") or "query_start"),
        query_id=str(data.get("query_id") or ""),
        summary=str(data.get("summary") or ""),
        step=_optional_int(data.get("step")),
        name=str(data.get("name") or ""),
        ok=data.get("ok") if isinstance(data.get("ok"), bool) else None,
        timestamp=str(data.get("timestamp") or ""),
        data=_stable_json_data(data.get("data") or {}),
    )


def _normalize_trajectory_event(event: Any) -> TrajectoryEvent:
    if isinstance(event, TrajectoryEvent):
        return event
    data = _to_mapping(event)
    return TrajectoryEvent(
        kind=str(data.get("kind") or "step"),
        content=str(data.get("content") or ""),
        step=_optional_int(data.get("step")),
        ok=data.get("ok") if isinstance(data.get("ok"), bool) else None,
        timestamp=str(data.get("timestamp") or ""),
        meta=_stable_json_data(data.get("meta") or {}),
    )


def _map_role(role: str) -> str:
    return ROLE_MAP.get(role.strip().lower(), "")


def _to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    return {}


def _string_content(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        text_parts: list[str] = []
        for item in value:
            if isinstance(item, Mapping):
                text = item.get("text") or item.get("content")
                if text:
                    text_parts.append(str(text))
            elif item is not None:
                text_parts.append(str(item))
        return "\n".join(text_parts)
    return str(value)


def _json_content(content: str) -> Any:
    text = str(content or "")
    try:
        if text.strip().startswith(("{", "[")):
            return json.loads(text)
    except json.JSONDecodeError:
        return text
    return text


def _xml_block(name: str, value: str) -> str:
    return f"<{name}>\n{value}\n</{name}>"


def _stable_json_data(data: Mapping[str, Any]) -> dict[str, Any]:
    stable: dict[str, Any] = {}
    for key, value in sorted((str(key), value) for key, value in data.items()):
        stable[key] = _json_safe(value)
    return stable


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        return value
    except TypeError:
        return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _last_nonempty(values: Iterable[str]) -> str:
    found = ""
    for value in values:
        if value:
            found = value
    return found


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
