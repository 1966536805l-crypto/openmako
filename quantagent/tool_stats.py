from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


DEFAULT_KNOWN_TOOLS = (
    "terminal",
    "read_file",
    "write_file",
    "edit",
    "test",
    "model",
    "desktop",
)


@dataclass(frozen=True)
class ToolStat:
    count: int = 0
    success: int = 0
    failure: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def build_tool_stats(
    records: Iterable[Any] | None = None,
    *,
    query_events: Iterable[Any] | None = None,
    trajectory: Iterable[Any] | None = None,
    tool_invocations: Iterable[Any] | None = None,
    known_tools: Iterable[str] = DEFAULT_KNOWN_TOOLS,
) -> dict[str, Any]:
    stats: dict[str, dict[str, int]] = {
        str(tool): {"count": 0, "success": 0, "failure": 0}
        for tool in known_tools
        if str(tool)
    }
    all_records = list(records or ())
    all_records.extend(_query_event_records(query_events or ()))
    all_records.extend(_trajectory_records(trajectory or ()))
    all_records.extend(tool_invocations or ())
    for record in all_records:
        payload = _record_payload(record)
        name = _tool_name(payload)
        if not name:
            continue
        stats.setdefault(name, {"count": 0, "success": 0, "failure": 0})
        stats[name]["count"] += 1
        ok = _record_ok(payload)
        if ok is True:
            stats[name]["success"] += 1
        elif ok is False:
            stats[name]["failure"] += 1
    errors = {name: item["failure"] for name, item in sorted(stats.items())}
    return {
        "tool_stats": {name: dict(item) for name, item in sorted(stats.items())},
        "tool_error_counts": errors,
    }


def merge_tool_stats(*summaries: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, dict[str, int]] = {}
    for summary in summaries:
        tool_stats = summary.get("tool_stats") if isinstance(summary, Mapping) else {}
        if not isinstance(tool_stats, Mapping):
            continue
        for name, raw in tool_stats.items():
            if not isinstance(raw, Mapping):
                continue
            key = str(name)
            merged.setdefault(key, {"count": 0, "success": 0, "failure": 0})
            merged[key]["count"] += _int(raw.get("count"))
            merged[key]["success"] += _int(raw.get("success"))
            merged[key]["failure"] += _int(raw.get("failure"))
    return {
        "tool_stats": {name: dict(item) for name, item in sorted(merged.items())},
        "tool_error_counts": {name: item["failure"] for name, item in sorted(merged.items())},
    }


def stats_from_query_events(events: Iterable[Any], *, known_tools: Iterable[str] = DEFAULT_KNOWN_TOOLS) -> dict[str, Any]:
    return build_tool_stats(_query_event_records(events), known_tools=known_tools)


def stats_from_trajectory_events(events: Iterable[Any], *, known_tools: Iterable[str] = DEFAULT_KNOWN_TOOLS) -> dict[str, Any]:
    return build_tool_stats(_trajectory_records(events), known_tools=known_tools)


def _query_event_records(events: Iterable[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in events:
        payload = _record_payload(event)
        if str(payload.get("kind") or "") in {"post_tool", "post_tool_batch", "post_model"}:
            records.append(payload)
    return records


def _trajectory_records(events: Iterable[Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for event in events:
        payload = _record_payload(event)
        meta = payload.get("meta") if isinstance(payload.get("meta"), Mapping) else {}
        name = meta.get("tool") or meta.get("tool_name") or meta.get("name") or payload.get("kind")
        records.append({"name": name, "ok": payload.get("ok"), "status": payload.get("status")})
    return records


def _record_payload(record: Any) -> dict[str, Any]:
    if isinstance(record, Mapping):
        return dict(record)
    if hasattr(record, "to_dict"):
        payload = record.to_dict()
        if isinstance(payload, Mapping):
            return dict(payload)
    if hasattr(record, "__dict__"):
        return dict(record.__dict__)
    return {}


def _tool_name(payload: Mapping[str, Any]) -> str:
    data = payload.get("data") if isinstance(payload.get("data"), Mapping) else {}
    for key in ("tool", "name", "tool_name"):
        value = payload.get(key) or data.get(key)
        if value:
            return str(value)
    kind = str(payload.get("kind") or "")
    if kind == "post_model":
        return "model"
    return ""


def _record_ok(payload: Mapping[str, Any]) -> bool | None:
    if isinstance(payload.get("ok"), bool):
        return bool(payload["ok"])
    status = str(payload.get("status") or payload.get("outcome") or "").strip().lower()
    if status in {"ok", "success", "succeeded", "passed", "pass", "completed", "done"}:
        return True
    if status in {"failed", "fail", "error", "blocked", "timeout", "cancelled", "canceled"}:
        return False
    if payload.get("error") or payload.get("error_kind"):
        return False
    return None


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
