from __future__ import annotations

from .exception_audit import audit_suppressed_exception
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
import re
import subprocess
import threading
from typing import Any, Callable, Iterable, Literal, Mapping, Optional, Sequence, Union


HookMode = Literal["void", "modifying", "claiming"]
FailurePolicy = Literal["fail_open", "fail_closed"]


HOOK_EVENT_MODES: dict[str, HookMode] = {
    "user_prompt_submit": "modifying",
    "before_context_build": "modifying",
    "after_context_build": "modifying",
    "before_model_call": "modifying",
    "after_model_call": "void",
    "before_prompt_build": "modifying",
    "before_tool_call": "modifying",
    "permission_request": "void",
    "after_tool_call": "void",
    "before_patch_apply": "modifying",
    "after_test_run": "void",
    "before_agent_finalize": "modifying",
    "after_agent_finalize": "void",
    "post_tool_use_failure": "void",
    "stop": "void",
    "subagent_start": "void",
    "subagent_stop": "void",
    "pre_compact": "modifying",
    "session_start": "void",
    "session_end": "void",
    "notification": "void",
    "setup": "void",
    "task_completed": "void",
    "config_change": "void",
    "worktree_create": "void",
    "worktree_remove": "void",
    "file_changed": "void",
    "inbound_claim": "claiming",
}

# Claude-ish public hook names are accepted as aliases so config files can use
# familiar names while QuantAgent internals keep their existing snake_case
# lifecycle points.
CLAUDE_HOOK_EVENT_ALIASES: dict[str, str] = {
    "UserPromptSubmit": "user_prompt_submit",
    "PreToolUse": "before_tool_call",
    "PostToolUse": "after_tool_call",
    "PostToolUseFailure": "post_tool_use_failure",
    "Stop": "stop",
    "SubagentStart": "subagent_start",
    "SubagentStop": "subagent_stop",
    "PreCompact": "pre_compact",
    "PermissionRequest": "permission_request",
    "SessionStart": "session_start",
    "SessionEnd": "session_end",
    "Notification": "notification",
    "Setup": "setup",
    "TaskCompleted": "task_completed",
    "ConfigChange": "config_change",
    "WorktreeCreate": "worktree_create",
    "WorktreeRemove": "worktree_remove",
}

HOOK_EVENT_ALIASES: dict[str, str] = {
    **CLAUDE_HOOK_EVENT_ALIASES,
    "user_prompt_submit": "user_prompt_submit",
    "pre_tool_use": "before_tool_call",
    "post_tool_use": "after_tool_call",
    "post_tool_use_failure": "post_tool_use_failure",
    "stop": "stop",
    "subagent_start": "subagent_start",
    "subagent_stop": "subagent_stop",
    "pre_compact": "pre_compact",
    "permission_request": "permission_request",
    "session_start": "session_start",
    "session_end": "session_end",
    "notification": "notification",
    "setup": "setup",
    "task_completed": "task_completed",
    "config_change": "config_change",
    "worktree_create": "worktree_create",
    "worktree_remove": "worktree_remove",
}


@dataclass(frozen=True)
class HookContext:
    project: str = ""
    session_id: str = ""
    run_id: str = ""
    plugin_id: str = ""


@dataclass(frozen=True)
class HookResult:
    payload: dict[str, Any] | None = None
    handled: bool = False
    blocked: bool = False
    summary: str = ""


HookCallable = Callable[[dict[str, Any], HookContext], Optional[Union[HookResult, dict[str, Any]]]]


@dataclass(frozen=True)
class HookHandler:
    event: str
    handler: HookCallable
    plugin_id: str = "core"
    priority: int = 0
    timeout_ms: int | None = None
    failure_policy: FailurePolicy = "fail_open"


@dataclass(frozen=True)
class HookRunResult:
    event: str
    payload: dict[str, Any]
    handled: bool = False
    blocked: bool = False
    errors: tuple[str, ...] = ()
    summaries: tuple[str, ...] = ()


HookCommand = Union[str, Sequence[str]]


@dataclass(frozen=True)
class HookSpec:
    event: str
    command: HookCommand
    matcher: str | None = None
    timeout_ms: int | None = None
    priority: int = 0
    async_: bool = False
    failure_policy: FailurePolicy = "fail_open"

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "HookSpec":
        command = data.get("command")
        if command is None:
            command = data.get("cmd")
        return cls(
            event=str(data.get("event") or ""),
            command=_normalize_command(command),
            matcher=_optional_str(data.get("matcher")),
            timeout_ms=_optional_int(data.get("timeout_ms") if "timeout_ms" in data else data.get("timeoutMs")),
            priority=int(data.get("priority") or 0),
            async_=bool(data.get("async") or data.get("async_") or data.get("async_hook")),
            failure_policy=_normalize_failure_policy(data.get("failure_policy") or data.get("failurePolicy")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "matcher": self.matcher,
            "command": _command_to_json(self.command),
            "timeout_ms": self.timeout_ms,
            "priority": self.priority,
            "async": self.async_,
            "failure_policy": self.failure_policy,
        }


@dataclass(frozen=True)
class LoadedHook:
    event: str
    command: HookCommand
    matcher: str | None = None
    timeout_ms: int | None = None
    priority: int = 0
    async_: bool = False
    failure_policy: FailurePolicy = "fail_open"

    @classmethod
    def from_spec(cls, spec: HookSpec | Mapping[str, Any]) -> "LoadedHook":
        if not isinstance(spec, HookSpec):
            spec = HookSpec.from_mapping(spec)
        event = normalize_hook_event(spec.event)
        if spec.matcher:
            re.compile(spec.matcher)
        return cls(
            event=event,
            command=_normalize_command(spec.command),
            matcher=spec.matcher,
            timeout_ms=spec.timeout_ms,
            priority=spec.priority,
            async_=spec.async_,
            failure_policy=spec.failure_policy,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "matcher": self.matcher,
            "command": _command_to_json(self.command),
            "timeout_ms": self.timeout_ms,
            "priority": self.priority,
            "async": self.async_,
            "failure_policy": self.failure_policy,
        }


@dataclass
class HookRegistry:
    handlers: list[HookHandler] = field(default_factory=list)

    def register(self, handler: HookHandler) -> None:
        event = normalize_hook_event(handler.event)
        self.handlers.append(replace(handler, event=event))

    def list_handlers(self, event: str | None = None) -> list[HookHandler]:
        if event is not None:
            event = normalize_hook_event(event)
        selected = [handler for handler in self.handlers if event is None or handler.event == event]
        return sorted(selected, key=lambda item: item.priority, reverse=True)

    def run(self, event: str, payload: dict[str, Any] | None = None, context: HookContext | None = None) -> HookRunResult:
        event = normalize_hook_event(event)
        mode = HOOK_EVENT_MODES[event]
        current = dict(payload or {})
        ctx = context or HookContext()
        errors: list[str] = []
        summaries: list[str] = []
        handled = False
        blocked = False

        for handler in self.list_handlers(event):
            result, error = _call_handler(handler, current, ctx)
            if error:
                errors.append(error)
                if handler.failure_policy == "fail_closed":
                    blocked = True
                    break
                continue
            if result.summary:
                summaries.append(result.summary)
            if result.blocked:
                blocked = True
                break
            if mode == "modifying" and result.payload is not None:
                current = dict(result.payload)
            elif mode == "claiming" and result.handled:
                handled = True
                if result.payload is not None:
                    current = dict(result.payload)
                break

        return HookRunResult(
            event=event,
            payload=current,
            handled=handled,
            blocked=blocked,
            errors=tuple(errors),
            summaries=tuple(summaries),
        )


def normalize_hook_event(event: str) -> str:
    normalized = HOOK_EVENT_ALIASES.get(event, event)
    if normalized not in HOOK_EVENT_MODES:
        allowed = ", ".join(sorted(set(HOOK_EVENT_MODES) | set(CLAUDE_HOOK_EVENT_ALIASES)))
        raise ValueError(f"unknown hook event: {event}; expected one of: {allowed}")
    return normalized


def run_configured_hooks(
    project: str | Path,
    event: str,
    payload: dict[str, Any] | None,
    specs: Iterable[HookSpec | LoadedHook | Mapping[str, Any]],
    context: HookContext | None = None,
) -> HookRunResult:
    requested_event = event
    canonical_event = normalize_hook_event(event)
    mode = HOOK_EVENT_MODES[canonical_event]
    current = dict(payload or {})
    ctx = context or HookContext(project=str(project))
    errors: list[str] = []
    summaries: list[str] = []
    handled = False
    blocked = False

    hooks, load_errors = _load_hooks(specs)
    errors.extend(load_errors)

    selected = sorted(
        (hook for hook in hooks if hook.event == canonical_event),
        key=lambda item: item.priority,
        reverse=True,
    )
    for hook in selected:
        if not _hook_matches(hook, (canonical_event, requested_event), current):
            continue
        result, error = _call_loaded_hook(Path(project), hook, current, ctx)
        if error:
            errors.append(error)
            if hook.failure_policy == "fail_closed":
                blocked = True
                break
            continue
        if result.summary:
            summaries.append(result.summary)
        if result.blocked:
            blocked = True
            break
        if mode == "modifying" and result.payload is not None:
            current = dict(result.payload)
        elif mode == "claiming" and result.handled:
            handled = True
            if result.payload is not None:
                current = dict(result.payload)
            break

    return HookRunResult(
        event=canonical_event,
        payload=current,
        handled=handled,
        blocked=blocked,
        errors=tuple(errors),
        summaries=tuple(summaries),
    )


def _call_handler(handler: HookHandler, payload: dict[str, Any], context: HookContext) -> tuple[HookResult, str]:
    try:
        if handler.timeout_ms and handler.timeout_ms > 0:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(handler.handler, dict(payload), context)
                raw = future.result(timeout=handler.timeout_ms / 1000)
        else:
            raw = handler.handler(dict(payload), context)
    except FutureTimeout:
        return HookResult(), f"{handler.plugin_id}:{handler.event} timed out"
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:342", exc)
        return HookResult(), f"{handler.plugin_id}:{handler.event} failed: {type(exc).__name__}: {exc}"
    return _normalize_result(raw), ""


def _normalize_result(raw: HookResult | dict[str, Any] | None) -> HookResult:
    if raw is None:
        return HookResult()
    if isinstance(raw, HookResult):
        return raw
    if isinstance(raw, dict):
        return HookResult(payload=raw)
    return HookResult(summary=str(raw))


def _load_hooks(specs: Iterable[HookSpec | LoadedHook | Mapping[str, Any]]) -> tuple[list[LoadedHook], list[str]]:
    hooks: list[LoadedHook] = []
    errors: list[str] = []
    for index, spec in enumerate(specs):
        try:
            if isinstance(spec, LoadedHook):
                event = normalize_hook_event(spec.event)
                if spec.matcher:
                    re.compile(spec.matcher)
                hook = replace(
                    spec,
                    event=event,
                    command=_normalize_command(spec.command),
                    failure_policy=_normalize_failure_policy(spec.failure_policy),
                )
            else:
                hook = LoadedHook.from_spec(spec)
            hooks.append(hook)
        except Exception as exc:
            errors.append(f"hook spec {index} failed to load: {type(exc).__name__}: {exc}")
    return hooks, errors


def _call_loaded_hook(project: Path, hook: LoadedHook, payload: dict[str, Any], context: HookContext) -> tuple[HookResult, str]:
    if hook.async_:
        thread = threading.Thread(
            target=_run_shell_hook,
            args=(project, hook, dict(payload), context),
            daemon=True,
        )
        thread.start()
        return HookResult(summary=f"launched async hook for {hook.event}"), ""
    return _run_shell_hook(project, hook, payload, context)


def _run_shell_hook(project: Path, hook: LoadedHook, payload: dict[str, Any], context: HookContext) -> tuple[HookResult, str]:
    del context
    command = _normalize_command(hook.command)
    timeout = hook.timeout_ms / 1000 if hook.timeout_ms and hook.timeout_ms > 0 else None
    stdin_payload = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True)
    try:
        completed = subprocess.run(
            command,
            input=stdin_payload,
            text=True,
            capture_output=True,
            cwd=project,
            timeout=timeout,
            shell=isinstance(command, str),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return HookResult(), f"{hook.event} shell hook timed out"
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:410", exc)
        return HookResult(), f"{hook.event} shell hook failed: {type(exc).__name__}: {exc}"

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode != 0:
        detail = stderr or stdout or f"exit status {completed.returncode}"
        return HookResult(), f"{hook.event} shell hook exited {completed.returncode}: {_preview(detail)}"
    if not stdout:
        return HookResult(), ""
    try:
        raw = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return HookResult(), f"{hook.event} shell hook returned invalid JSON: {exc.msg}"
    if not isinstance(raw, Mapping):
        return HookResult(), f"{hook.event} shell hook returned JSON {type(raw).__name__}, expected object"
    return _normalize_shell_result(raw)


def _normalize_shell_result(raw: Mapping[str, Any]) -> tuple[HookResult, str]:
    payload = raw.get("payload")
    if payload is not None and not isinstance(payload, Mapping):
        return HookResult(), "shell hook field 'payload' must be an object"
    return (
        HookResult(
            payload=dict(payload) if payload is not None else None,
            handled=bool(raw.get("handled")),
            blocked=bool(raw.get("blocked")),
            summary=str(raw.get("summary") or ""),
        ),
        "",
    )


def _hook_matches(hook: LoadedHook, events: Iterable[str], payload: Mapping[str, Any]) -> bool:
    if not hook.matcher:
        return True
    pattern = re.compile(hook.matcher)
    haystacks = [
        *(str(event) for event in events),
        str(payload.get("event") or ""),
        str(payload.get("tool") or ""),
        str(payload.get("name") or ""),
        str(payload.get("message") or ""),
    ]
    return any(pattern.search(value) for value in haystacks if value)


def _normalize_command(command: Any) -> HookCommand:
    if isinstance(command, str):
        return command
    if isinstance(command, Sequence) and not isinstance(command, (bytes, bytearray, str)):
        return tuple(str(part) for part in command)
    raise ValueError("hook command must be a string or argv list")


def _command_to_json(command: HookCommand) -> str | list[str]:
    if isinstance(command, str):
        return command
    return [str(part) for part in command]


def _optional_str(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _normalize_failure_policy(value: Any) -> FailurePolicy:
    if value in (None, ""):
        return "fail_open"
    if value not in ("fail_open", "fail_closed"):
        raise ValueError("failure_policy must be fail_open or fail_closed")
    return value


def _preview(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."
