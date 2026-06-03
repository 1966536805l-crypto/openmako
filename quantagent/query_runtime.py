from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hook_events import QueryEvent, append_query_event, read_query_events
from .query_guard import QueryGuard
from .runtime_store import record_query_event


@dataclass
class QueryRuntime:
    project: Path
    query_id: str = field(default_factory=lambda: "qa-" + uuid.uuid4().hex[:12])
    event_path: Path | None = None
    persist: bool = True
    guard: QueryGuard | None = None
    events: list[QueryEvent] = field(default_factory=list)
    state: str = "initialized"
    stop_reason: str = ""
    failure_reason: str = ""
    transitions: list[dict[str, str]] = field(default_factory=list)
    _guard_generation: int | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.project = Path(self.project).expanduser().resolve(strict=False)
        if self.event_path is None:
            self.event_path = query_event_path(self.project)

    def transition(self, state: str, *, reason: str = "", failure_reason: str = "") -> dict[str, str]:
        target = str(state or "").strip().lower()
        reason = str(reason or "").strip()
        failure_reason = str(failure_reason or "").strip()
        current = self.state
        if current in {"completed", "failed"}:
            raise RuntimeError(f"query runtime already terminal: {current}")
        if target not in {"initialized", "running", "retrying", "completed", "failed"}:
            raise ValueError(f"unknown query runtime state: {state!r}")
        allowed = {
            "initialized": {"running", "completed", "failed"},
            "running": {"retrying", "completed", "failed"},
            "retrying": {"running", "failed"},
        }
        if target not in allowed.get(current, set()):
            raise RuntimeError(f"illegal query runtime transition: {current} -> {target}")
        if target == "completed":
            if not reason:
                raise ValueError("completed query runtime transition requires stop_reason")
            self.stop_reason = reason
        elif target == "failed":
            if not failure_reason:
                raise ValueError("failed query runtime transition requires failure_reason")
            self.failure_reason = failure_reason
        elif target == "retrying" and not reason:
            raise ValueError("retrying query runtime transition requires reason")
        record = {
            "from": current,
            "to": target,
            "reason": reason,
            "failure_reason": failure_reason,
        }
        self.transitions.append(record)
        self.state = target
        return record

    def retry(self, reason: str) -> dict[str, str]:
        retry_transition = self.transition("retrying", reason=reason)
        self.transition("running", reason=reason)
        return retry_transition

    def emit(
        self,
        kind: str,
        summary: str = "",
        *,
        step: int | None = None,
        name: str = "",
        ok: bool | None = None,
        data: dict[str, Any] | None = None,
    ) -> QueryEvent:
        event = QueryEvent(
            kind=kind,
            query_id=self.query_id,
            summary=summary[:500],
            step=step,
            name=name,
            ok=ok,
            data=data or {},
        )
        if self.persist and self.event_path is not None:
            try:
                event = append_query_event(self.event_path, event)
                record_query_event(self.project, event)
            except Exception as exc:
                # Query events are observability. Disk/SQLite failures must not
                # block the primary code edit, test, or repair path.
                audit_suppressed_exception(f"{__name__}:51", exc)
                pass
        self.events.append(event)
        return event

    def start(self, task: str, *, mode: str = "", data: dict[str, Any] | None = None) -> QueryEvent:
        payload = {"task": task, "mode": mode}
        payload.update(data or {})
        payload.setdefault("status", "running")
        if self.state != "initialized":
            raise RuntimeError(f"illegal query runtime transition: {self.state} -> running")
        if self.guard is not None:
            generation = self.guard.start()
            if generation is None:
                raise RuntimeError(f"query guard is busy: {self.guard.state}")
            self._guard_generation = generation
            payload.update({"guard_generation": generation, "guard_state": self.guard.state})
        transition = self.transition("running", reason="query_start")
        payload.update({"runtime_state": self.state, "transition": transition})
        return self.emit("query_start", f"query started: {task}"[:500], data=payload)

    def user_prompt(self, prompt: str) -> QueryEvent:
        return self.emit("user_prompt_submit", "user prompt submitted", data={"preview": _preview(prompt)})

    def pre_model(
        self,
        model: str,
        *,
        system: str = "",
        prompt: str = "",
        name: str = "model",
    ) -> QueryEvent:
        return self.emit(
            "pre_model",
            f"model start: {model}",
            name=name,
            data={
                "model": model,
                "system_chars": len(system),
                "prompt_chars": len(prompt),
                "prompt_preview": _preview(prompt),
            },
        )

    def post_model(
        self,
        model: str,
        *,
        ok: bool,
        summary: str,
        provider: str = "",
        usage: dict[str, Any] | None = None,
        name: str = "model",
        error_kind: str = "",
        retryable: bool | None = None,
        should_compress: bool = False,
        should_rotate_credential: bool = False,
        should_fallback: bool = False,
        compression: dict[str, Any] | None = None,
        token_budget: dict[str, Any] | None = None,
    ) -> QueryEvent:
        data = {
            "model": model,
            "provider": provider,
            "usage": usage or {},
        }
        if compression:
            data["compression"] = compression
        if token_budget:
            data["token_budget"] = token_budget
        if error_kind:
            data.update(
                {
                    "error_kind": error_kind,
                    "retryable": retryable,
                    "should_compress": should_compress,
                    "should_rotate_credential": should_rotate_credential,
                    "should_fallback": should_fallback,
                }
            )
        return self.emit(
            "post_model",
            summary,
            name=name,
            ok=ok,
            data=data,
        )

    def pre_tool(self, name: str, *, step: int | None = None, args: dict[str, Any] | None = None) -> QueryEvent:
        return self.emit("pre_tool", f"tool start: {name}", step=step, name=name, data={"args": args or {}})

    def post_tool(
        self,
        name: str,
        *,
        step: int | None = None,
        ok: bool,
        summary: str,
        data: dict[str, Any] | None = None,
    ) -> QueryEvent:
        return self.emit("post_tool", summary, step=step, name=name, ok=ok, data=data or {})

    def post_tool_batch(self, *, ok: bool, count: int) -> QueryEvent:
        return self.emit("post_tool_batch", f"{count} tool result(s)", ok=ok, data={"count": count})

    def stop(self, summary: str, *, ok: bool = True, failure_class: str = "", status: str = "") -> QueryEvent:
        kind = "stop" if ok else "stop_failure"
        stop_reason = str(summary or status or "done").strip() if ok else ""
        failure_reason = str(failure_class or status or summary or "").strip() if not ok else ""
        transition = self.transition(
            "completed" if ok else "failed",
            reason=stop_reason,
            failure_reason=failure_reason,
        )
        data: dict[str, Any] = {
            "failure_class": failure_class,
            "status": status or _derive_stop_status(ok, failure_class),
            "runtime_state": self.state,
            "transition": transition,
            "transitions": list(self.transitions),
        }
        if ok:
            data["stop_reason"] = stop_reason
        else:
            data["failure_reason"] = failure_reason
        if self.guard is not None and self._guard_generation is not None:
            generation = self._guard_generation
            data["guard_generation"] = generation
            data["guard_ended"] = self.guard.end(generation)
            data["guard_state"] = self.guard.state
            self._guard_generation = None
        return self.emit(kind, summary, ok=ok, data=data)


def query_event_path(project: str | Path) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    out_dir = project_path / "AI_协作交接"
    if not out_dir.exists():
        out_dir = project_path / ".quantagent"
    return out_dir / "query_events.jsonl"


def load_query_events(project: str | Path) -> list[QueryEvent]:
    return read_query_events(query_event_path(project))


def render_query_events(events: list[QueryEvent], *, limit: int = 12) -> str:
    if not events:
        return "No query events."
    selected = events[-max(0, limit) :] if limit else []
    lines = [f"Query events: {len(events)} total, showing {len(selected)}."]
    for event in selected:
        status = "ok" if event.ok is True else "failed" if event.ok is False else "pending"
        final_status = str(event.data.get("status") or "").strip()
        label = f"{status} status={final_status}" if final_status else status
        step = f" step={event.step}" if event.step is not None else ""
        name = f" {event.name}" if event.name else ""
        lines.append(f"- {event.kind}{step}{name} [{label}]: {event.summary}")
    return "\n".join(lines)


def _derive_stop_status(ok: bool, failure_class: str) -> str:
    if ok:
        return "done"
    normalized = str(failure_class or "").strip().lower()
    if normalized in {"approval_required", "review_required"}:
        return "needs_approval"
    if normalized in {"goal_conflict", "policy_blocked", "hook_blocked", "answer_guard_blocked", "blocked"}:
        return "blocked"
    return "failed"


def _preview(text: str, limit: int = 500) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"
