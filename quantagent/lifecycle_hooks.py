from __future__ import annotations

from .exception_audit import audit_suppressed_exception
from pathlib import Path
from typing import Any

from .agent_profiles import load_agent_profile_config
from .hook_events import QueryEvent
from .hook_runner import HookContext, HookRegistry, HookRunResult, HookSpec, run_configured_hooks
from .runtime_store import record_query_event


GLOBAL_HOOKS = HookRegistry()


def run_lifecycle_hook(
    project: str | Path,
    event: str,
    payload: dict[str, Any] | None = None,
    *,
    session_id: str = "",
    run_id: str = "",
    plugin_id: str = "core",
    query_id: str = "",
    registry: HookRegistry | None = None,
) -> HookRunResult:
    selected = registry or GLOBAL_HOOKS
    result = selected.run(
        event,
        payload or {},
        HookContext(project=str(project), session_id=session_id, run_id=run_id, plugin_id=plugin_id),
    )
    result = _run_profile_hooks(
        project,
        event,
        result,
        session_id=session_id,
        run_id=run_id,
        plugin_id=plugin_id,
    )
    if query_id:
        record_query_event(
            project,
            QueryEvent(
                kind="hook",
                query_id=query_id,
                name=event,
                ok=not result.blocked,
                summary=f"hook {event}: {len(result.summaries)} summary, {len(result.errors)} error(s)",
                data={
                    "event": event,
                    "blocked": result.blocked,
                    "handled": result.handled,
                    "summaries": list(result.summaries),
                    "errors": list(result.errors),
                },
            ),
        )
    return result


def _run_profile_hooks(
    project: str | Path,
    event: str,
    result: HookRunResult,
    *,
    session_id: str,
    run_id: str,
    plugin_id: str,
) -> HookRunResult:
    if result.blocked:
        return result
    profile_name = str(result.payload.get("profile") or "")
    if not profile_name:
        return result
    try:
        profile = load_agent_profile_config(project).agents.get(profile_name)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:77", exc)
        return HookRunResult(
            event=result.event,
            payload=result.payload,
            handled=result.handled,
            blocked=result.blocked,
            errors=(*result.errors, f"profile hook load failed: {type(exc).__name__}: {exc}"),
            summaries=result.summaries,
        )
    if not profile or not profile.hooks:
        return result
    configured = run_configured_hooks(
        project,
        event,
        result.payload,
        _hook_specs_from_raw(profile.hooks),
        HookContext(project=str(project), session_id=session_id, run_id=run_id, plugin_id=plugin_id),
    )
    return HookRunResult(
        event=configured.event,
        payload=configured.payload,
        handled=result.handled or configured.handled,
        blocked=result.blocked or configured.blocked,
        errors=(*result.errors, *configured.errors),
        summaries=(*result.summaries, *configured.summaries),
    )


def _hook_specs_from_raw(raw: Any) -> list[HookSpec]:
    specs: list[HookSpec] = []
    if not raw:
        return specs
    if isinstance(raw, list):
        for item in raw:
            specs.extend(_hook_specs_from_item("", item))
    elif isinstance(raw, dict):
        for event, value in raw.items():
            specs.extend(_hook_specs_from_item(str(event), value))
    return specs


def _hook_specs_from_item(event: str, raw: Any) -> list[HookSpec]:
    if isinstance(raw, list):
        specs: list[HookSpec] = []
        for item in raw:
            specs.extend(_hook_specs_from_item(event, item))
        return specs
    if isinstance(raw, dict):
        payload = dict(raw)
        payload.setdefault("event", event)
        return [HookSpec.from_mapping(payload)]
    if isinstance(raw, str):
        return [HookSpec(event=event, command=raw)]
    return []
