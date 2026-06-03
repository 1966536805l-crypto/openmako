from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


EVENT_KINDS = frozenset({"step", "action", "observation", "edit", "test"})


@dataclass(frozen=True)
class TrajectoryEvent:
    kind: str
    content: str
    step: int | None = None
    ok: bool | None = None
    timestamp: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data["timestamp"]:
            data["timestamp"] = _utc_timestamp()
        data["meta"] = _stable_meta(data["meta"])
        return data


def append_event(path: Path | str, event: TrajectoryEvent | Mapping[str, Any]) -> TrajectoryEvent:
    """Append one trajectory event as deterministic JSONL.

    Validates:
    - kind must be in EVENT_KINDS (validated by normalize_event)
    - step must not decrease relative to previous events in the same file
    """
    normalized = normalize_event(event)
    target = Path(path)

    # Validate step ordering if file exists and event has a step
    if target.exists() and normalized.step is not None:
        existing = read_events(target)
        if existing:
            # Find the maximum step from existing events
            existing_steps = [e.step for e in existing if e.step is not None]
            if existing_steps:
                max_step = max(existing_steps)
                if normalized.step < max_step:
                    raise ValueError(
                        f"Out-of-order trajectory step: new step {normalized.step} < max existing step {max_step}"
                    )

    target.parent.mkdir(parents=True, exist_ok=True)
    payload = normalized.to_dict()
    line = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    return normalize_event(payload)


def append_events(path: Path | str, events: Iterable[TrajectoryEvent | Mapping[str, Any]]) -> list[TrajectoryEvent]:
    return [append_event(path, event) for event in events]


def read_events(path: Path | str) -> list[TrajectoryEvent]:
    target = Path(path)
    if not target.exists():
        return []

    events: list[TrajectoryEvent] = []
    with target.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid trajectory JSONL at line {line_number}: {exc.msg}") from exc
            if not isinstance(payload, Mapping):
                raise ValueError(f"Invalid trajectory JSONL at line {line_number}: expected object")
            events.append(normalize_event(payload))
    return events


def record_step(path: Path | str, content: str, *, step: int | None = None, ok: bool | None = None, **meta: Any) -> TrajectoryEvent:
    return append_event(path, TrajectoryEvent(kind="step", content=content, step=step, ok=ok, meta=meta))


def record_action(path: Path | str, content: str, *, step: int | None = None, ok: bool | None = None, **meta: Any) -> TrajectoryEvent:
    return append_event(path, TrajectoryEvent(kind="action", content=content, step=step, ok=ok, meta=meta))


def record_observation(
    path: Path | str,
    content: str,
    *,
    step: int | None = None,
    ok: bool | None = None,
    **meta: Any,
) -> TrajectoryEvent:
    return append_event(path, TrajectoryEvent(kind="observation", content=content, step=step, ok=ok, meta=meta))


def record_edit(path: Path | str, content: str, *, step: int | None = None, ok: bool | None = None, **meta: Any) -> TrajectoryEvent:
    return append_event(path, TrajectoryEvent(kind="edit", content=content, step=step, ok=ok, meta=meta))


def record_test(path: Path | str, content: str, *, step: int | None = None, ok: bool | None = None, **meta: Any) -> TrajectoryEvent:
    return append_event(path, TrajectoryEvent(kind="test", content=content, step=step, ok=ok, meta=meta))


def recent_summary(events: Iterable[TrajectoryEvent | Mapping[str, Any]], *, limit: int = 8, max_content_chars: int = 120) -> str:
    """Return a compact, deterministic summary of the most recent events."""
    normalized = [normalize_event(event) for event in events]
    if not normalized:
        return "No trajectory events."

    selected = normalized[-max(0, limit) :] if limit else []
    if not selected:
        return f"Trajectory has {len(normalized)} event(s); showing 0 recent event(s)."

    lines = [f"Trajectory has {len(normalized)} event(s); showing {len(selected)} recent event(s):"]
    start_index = len(normalized) - len(selected) + 1
    for offset, event in enumerate(selected):
        status = _status_label(event.ok)
        step = f"step={event.step}" if event.step is not None else "step=-"
        lines.append(f"- {start_index + offset}. {event.kind} {step} {status}: {_preview(event.content, max_content_chars)}")
    return "\n".join(lines)


def failed_events(events: Iterable[TrajectoryEvent | Mapping[str, Any]]) -> list[TrajectoryEvent]:
    return [event for event in (normalize_event(item) for item in events) if event.ok is False]


def failed_steps(events: Iterable[TrajectoryEvent | Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return failed events grouped by step, preserving first-seen order."""
    grouped: dict[int | None, list[TrajectoryEvent]] = {}
    for event in failed_events(events):
        grouped.setdefault(event.step, []).append(event)

    failures: list[dict[str, Any]] = []
    for step, step_events in grouped.items():
        failures.append(
            {
                "step": step,
                "count": len(step_events),
                "events": [event.to_dict() for event in step_events],
                "summary": "; ".join(f"{event.kind}: {_preview(event.content, 80)}" for event in step_events),
            }
        )
    return failures


def normalize_event(event: TrajectoryEvent | Mapping[str, Any]) -> TrajectoryEvent:
    if isinstance(event, TrajectoryEvent):
        _validate_kind(event.kind)
        return event

    kind = str(event.get("kind", "")).strip()
    _validate_kind(kind)
    content = str(event.get("content", ""))
    step_value = event.get("step")
    ok_value = event.get("ok")
    timestamp = str(event.get("timestamp") or "")
    meta_value = event.get("meta") or {}
    if not isinstance(meta_value, Mapping):
        raise ValueError("Trajectory event meta must be an object")

    return TrajectoryEvent(
        kind=kind,
        content=content,
        step=_normalize_step(step_value),
        ok=_normalize_ok(ok_value),
        timestamp=timestamp,
        meta=_stable_meta(meta_value),
    )


def _validate_kind(kind: str) -> None:
    if kind not in EVENT_KINDS:
        allowed = ", ".join(sorted(EVENT_KINDS))
        raise ValueError(f"Unknown trajectory event kind {kind!r}; expected one of: {allowed}")


def _normalize_step(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("Trajectory event step must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Trajectory event step must be an integer") from exc


def _normalize_ok(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    raise ValueError("Trajectory event ok must be true, false, or null")


def _stable_meta(meta: Mapping[str, Any]) -> dict[str, Any]:
    stable: dict[str, Any] = {}
    for key, value in sorted((str(key), value) for key, value in meta.items()):
        stable[key] = _json_safe(value)
    return stable


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        return value
    except TypeError:
        return str(value)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _status_label(ok: bool | None) -> str:
    if ok is True:
        return "ok"
    if ok is False:
        return "failed"
    return "unknown"


def _preview(text: str, max_chars: int) -> str:
    compact = " ".join(str(text).split())
    if max_chars <= 0 or len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 1)].rstrip() + "…"
