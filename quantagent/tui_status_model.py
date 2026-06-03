from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .agent_context_runtime import AgentRuntimeContext, build_agent_runtime_context
from .mode_router import ModeRoute, route_agent_mode
from .session_bus import session_bus_summary, status_session_bus
from .ux_status import UXStatus, build_ux_status


@dataclass(frozen=True)
class TuiPanel:
    name: str
    status: str
    title: str
    lines: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["lines"] = list(self.lines)
        return payload


@dataclass(frozen=True)
class TuiStatusModel:
    project: str
    task: str
    route: ModeRoute
    context: AgentRuntimeContext
    ux: UXStatus
    panels: tuple[TuiPanel, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "task": self.task,
            "route": self.route.to_dict(),
            "context": self.context.to_dict(),
            "ux": self.ux.to_dict(),
            "panels": [panel.to_dict() for panel in self.panels],
        }


def build_tui_status_model(
    project: str | Path,
    *,
    task: str = "",
    mode_name: str = "",
    include_context_pack: bool = False,
    limit: int = 5,
) -> TuiStatusModel:
    project_path = Path(project).expanduser().resolve(strict=False)
    route = route_agent_mode(project_path, task or "status", explicit_mode=mode_name)
    context = build_agent_runtime_context(project_path, task or "status", mode_name=route.mode)
    ux = build_ux_status(project_path, task=task or "status", limit=limit, include_context_pack=include_context_pack)
    panels = (
        _mode_panel(route, context),
        _context_panel(context),
        _active_task_panel(ux),
        _approval_panel(ux),
        _tool_panel(ux),
        _session_bus_panel(project_path),
        _event_panel(ux),
    )
    return TuiStatusModel(str(project_path), task or "status", route, context, panels=panels, ux=ux)


def render_tui_status_model(model: TuiStatusModel) -> str:
    lines = [
        "# TUI Status Model",
        "",
        f"- project: {model.project}",
        f"- task: {model.task}",
        f"- active_mode: {model.route.mode}",
        f"- confidence: {model.route.confidence:.2f}",
        f"- context_sections: {len(model.context.sections)}",
        "",
        "## Panels",
        "",
    ]
    for panel in model.panels:
        lines.append(f"### {panel.title}")
        lines.append(f"- name: {panel.name}")
        lines.append(f"- status: {panel.status}")
        for line in panel.lines:
            lines.append(f"- {line}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_tui_status_json(model: TuiStatusModel) -> str:
    return json.dumps(model.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _mode_panel(route: ModeRoute, context: AgentRuntimeContext) -> TuiPanel:
    return TuiPanel(
        "mode",
        "ok",
        "Active Mode",
        (
            f"mode={route.mode}",
            f"profile={route.profile}",
            f"transition={route.transition}",
            f"intent={route.intent}",
            f"checks={context.mode_policy.get('source_checks')}",
            f"apply_gate={context.mode_policy.get('apply_gate')}",
            f"isolation={context.mode_policy.get('isolation')}",
        ),
        {"route": route.to_dict(), "mode_policy": context.mode_policy},
    )


def _context_panel(context: AgentRuntimeContext) -> TuiPanel:
    warnings = [section for section in context.sections if section.status == "warn"]
    return TuiPanel(
        "context",
        "warn" if warnings else "ok",
        "Runtime Context",
        tuple(f"{section.name}: {section.status}, {section.summary}" for section in context.sections),
        {"estimated_tokens": context.estimated_tokens, "sections": [section.to_dict() for section in context.sections]},
    )


def _approval_panel(ux: UXStatus) -> TuiPanel:
    return TuiPanel(
        "approvals",
        "blocked" if ux.approvals else "ok",
        "Approvals",
        tuple(f"{item.approval_id}: {item.tool} {item.action} {item.status}" for item in ux.approvals) or ("none",),
        {"approvals": [asdict(item) for item in ux.approvals]},
    )


def _active_task_panel(ux: UXStatus) -> TuiPanel:
    blocked = [item for item in ux.active_tasks if item.blocker or item.next_approval]
    running = [item for item in ux.active_tasks if item.status == "running"]
    return TuiPanel(
        "active_tasks",
        "blocked" if blocked else "running" if running else "ok",
        "Active Tasks",
        tuple(
            f"{item.task_id} [{item.status}]"
            + (f" tool={item.active_tool}/{item.active_tool_status or '-'}" if item.active_tool else "")
            + (f" blocker={item.blocker}" if item.blocker else "")
            for item in ux.active_tasks
        )
        or ("none",),
        {"active_tasks": [asdict(item) for item in ux.active_tasks]},
    )


def _tool_panel(ux: UXStatus) -> TuiPanel:
    failed = [item for item in ux.tools if item.status != "ok"]
    return TuiPanel(
        "tools",
        "warn" if failed else "ok",
        "Tool Calls",
        tuple(f"{item.tool} [{item.status}] {item.summary}" for item in ux.tools) or ("none",),
        {"tools": [asdict(item) for item in ux.tools]},
    )


def _session_bus_panel(project: Path) -> TuiPanel:
    try:
        state = status_session_bus(project)
        summary = session_bus_summary(project)
        return TuiPanel(
            "session_bus",
            "ok" if state.status in {"running", "stopped"} else "warn",
            "Session Bus",
            (
                f"status={state.status}",
                f"messages={summary.get('messages', 0)}",
                f"sessions={summary.get('sessions', 0)}",
                f"channels={','.join(summary.get('channels') or ()) if summary.get('channels') else 'none'}",
            ),
            {"state": state.to_dict(), "summary": summary},
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:164", exc)
        return TuiPanel("session_bus", "warn", "Session Bus", (f"{type(exc).__name__}: {exc}",))


def _event_panel(ux: UXStatus) -> TuiPanel:
    return TuiPanel(
        "events",
        "ok",
        "Recent Events",
        tuple(f"{item.kind}: {item.summary}" for item in ux.events) or ("none",),
        {"events": [asdict(item) for item in ux.events]},
    )
