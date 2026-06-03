from __future__ import annotations

from .exception_audit import audit_suppressed_exception
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .agent_modes import AgentMode, get_agent_mode, resolve_agent_mode_permission
from .diagnostic_registry import DiagnosticSnapshot, load_diagnostic_registry, refresh_diagnostic_registry
from .mode_router import ModeRoute, route_agent_mode
from .repo_map import RepoMapHit, ensure_repo_map, search_repo_map
from .runtime_store import list_approval_requests
from .source_checks import SourceCheckResult, load_source_checks, run_source_checks, source_check_summary
from .tool_transcript import ToolCallTranscript, list_tool_transcripts


@dataclass(frozen=True)
class RuntimeContextSection:
    name: str
    status: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"ok", "empty", "advisory", "warn"}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentRuntimeContext:
    task: str
    mode: str
    profile: str
    route: ModeRoute
    mode_policy: dict[str, Any]
    sections: tuple[RuntimeContextSection, ...] = ()
    changed_paths: tuple[str, ...] = ()
    tool_name: str = ""
    estimated_tokens: int = 0

    @property
    def ok(self) -> bool:
        return all(section.ok for section in self.sections)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "mode": self.mode,
            "profile": self.profile,
            "route": self.route.to_dict(),
            "mode_policy": self.mode_policy,
            "sections": [section.to_dict() for section in self.sections],
            "changed_paths": list(self.changed_paths),
            "tool_name": self.tool_name,
            "estimated_tokens": self.estimated_tokens,
            "ok": self.ok,
        }


def build_agent_runtime_context(
    project: str | Path,
    task: str,
    *,
    mode_name: str = "",
    previous_mode: str = "",
    failure_class: str = "",
    changed_paths: Iterable[str | Path] = (),
    input_provenance: str = "",
    tool_name: str = "",
    include_repo_map: bool = True,
    include_diagnostics: bool = True,
    include_source_checks: bool = True,
    include_runtime: bool = True,
    repo_limit: int = 6,
    transcript_limit: int = 6,
) -> AgentRuntimeContext:
    project_path = Path(project).expanduser().resolve(strict=False)
    paths = tuple(_normalize_path(path) for path in changed_paths if str(path).strip())
    route = route_agent_mode(
        project_path,
        task,
        explicit_mode=mode_name,
        previous_mode=previous_mode,
        failure_class=failure_class,
        changed_paths=paths,
        input_provenance=input_provenance,
        tool_name=tool_name,
    )
    mode = get_agent_mode(project_path, route.mode)
    sections: list[RuntimeContextSection] = [_mode_section(project_path, mode, tool_name)]

    if include_repo_map:
        sections.append(_repo_map_section(project_path, task, limit=repo_limit))
    if include_diagnostics:
        sections.append(_diagnostics_section(project_path, paths))
    if include_source_checks:
        sections.append(_source_checks_section(project_path, paths))
    if include_runtime:
        sections.append(_runtime_section(project_path, transcript_limit=transcript_limit))

    estimated = sum(_estimate_section_tokens(section) for section in sections)
    return AgentRuntimeContext(
        task=task,
        mode=route.mode,
        profile=route.profile,
        route=route,
        mode_policy=_mode_policy(mode),
        sections=tuple(sections),
        changed_paths=paths,
        tool_name=tool_name,
        estimated_tokens=estimated,
    )


def render_agent_runtime_context(context: AgentRuntimeContext) -> str:
    lines = [
        "# Agent Runtime Context",
        "",
        f"- task: {context.task}",
        f"- mode: {context.mode}",
        f"- profile: {context.profile}",
        f"- route_confidence: {context.route.confidence:.2f}",
        f"- transition: {context.route.transition}",
        f"- changed_paths: {len(context.changed_paths)}",
        f"- tool_name: {context.tool_name or '-'}",
        f"- estimated_tokens: {context.estimated_tokens}",
        "",
        "## Route",
        "",
    ]
    lines.extend(f"- {reason}" for reason in context.route.reasons)
    lines.extend(["", "## Sections", ""])
    for section in context.sections:
        lines.append(f"- [{section.status}] {section.name}: {section.summary}")
        for key, value in _section_preview(section.data).items():
            lines.append(f"  {key}: {value}")
    return "\n".join(lines) + "\n"


def context_prompt_fragment(context: AgentRuntimeContext, *, max_chars: int = 9000) -> str:
    """Compact prompt-ready fragment for agent loops before tool calls."""
    lines = [
        "# Mode-Aware Runtime Context",
        f"mode: {context.mode}",
        f"profile: {context.profile}",
        f"intent: {context.route.intent}",
        f"confidence: {context.route.confidence:.2f}",
        f"mode_policy: checks={context.mode_policy.get('source_checks')} apply_gate={context.mode_policy.get('apply_gate')} isolation={context.mode_policy.get('isolation')}",
        "",
        "route_reasons:",
    ]
    lines.extend(f"- {reason}" for reason in context.route.reasons[:6])
    for section in context.sections:
        lines.extend(["", f"## {section.name} [{section.status}]", section.summary])
        preview = _section_preview(section.data, max_items=8)
        for key, value in preview.items():
            lines.append(f"- {key}: {value}")
    text = "\n".join(lines).strip() + "\n"
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 80)].rstrip() + "\n\n[trimmed by agent runtime context]\n"


def _mode_section(project: Path, mode: AgentMode, tool_name: str) -> RuntimeContextSection:
    decision_data: dict[str, Any] = {}
    if tool_name:
        decision = resolve_agent_mode_permission(project, mode.name, tool_name)
        decision_data = decision.to_dict() if decision is not None else {"tool": tool_name, "action": "unknown"}
    return RuntimeContextSection(
        "mode_policy",
        "ok",
        f"{mode.name}: checks={mode.source_checks}, apply_gate={mode.apply_gate}, isolation={mode.isolation}",
        {
            "mode": mode.to_dict(),
            "tool_decision": decision_data,
        },
    )


def _repo_map_section(project: Path, task: str, *, limit: int) -> RuntimeContextSection:
    try:
        repo_map = ensure_repo_map(project)
        hits = search_repo_map(project, task or "agent runtime", limit=limit)
        return RuntimeContextSection(
            "repo_map",
            "ok" if hits else "empty",
            f"{len(repo_map.files)} indexed file(s), {len(hits)} relevant hit(s)",
            {
                "files": len(repo_map.files),
                "symbols": sum(len(item.symbols) for item in repo_map.files),
                "hits": [_hit_dict(hit) for hit in hits],
            },
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:196", exc)
        return RuntimeContextSection("repo_map", "warn", f"repo map unavailable: {type(exc).__name__}: {exc}")


def _diagnostics_section(project: Path, paths: tuple[str, ...]) -> RuntimeContextSection:
    try:
        snapshot = _load_or_refresh_diagnostics(project)
        diagnostics = _diagnostics_for_paths(snapshot, paths)
        counts: dict[str, int] = {}
        for item in diagnostics:
            level = str(item.level or "info")
            counts[level] = counts.get(level, 0) + 1
        blocking = counts.get("error", 0)
        status = "ok" if blocking == 0 else "warn"
        return RuntimeContextSection(
            "diagnostics",
            status if diagnostics else "empty",
            f"{len(diagnostics)} diagnostic(s), errors={blocking}",
            {
                "snapshot_id": snapshot.snapshot_id,
                "counts": counts,
                "items": [asdict(item) for item in diagnostics[:12]],
            },
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:220", exc)
        return RuntimeContextSection("diagnostics", "warn", f"diagnostics unavailable: {type(exc).__name__}: {exc}")


def _source_checks_section(project: Path, paths: tuple[str, ...]) -> RuntimeContextSection:
    try:
        specs = load_source_checks(project)
        results = run_source_checks(project, paths=paths, run_commands=False)
        summary = source_check_summary(results)
        failures = int(summary.get("counts", {}).get("fail", 0))
        warnings = int(summary.get("counts", {}).get("warn", 0))
        status = "ok"
        if failures:
            status = "warn"
        elif warnings:
            status = "advisory"
        elif not specs:
            status = "empty"
        return RuntimeContextSection(
            "source_checks",
            status,
            f"{len(specs)} check spec(s), {len(results)} result(s), failures={failures}",
            {
                "specs": [spec.to_dict() for spec in specs[:12]],
                "summary": summary,
                "results": [result.to_dict() for result in results[:12]],
            },
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:248", exc)
        return RuntimeContextSection("source_checks", "warn", f"source checks unavailable: {type(exc).__name__}: {exc}")


def _runtime_section(project: Path, *, transcript_limit: int) -> RuntimeContextSection:
    try:
        approvals = list_approval_requests(project, status="pending", limit=20)
        transcripts = list_tool_transcripts(project, limit=transcript_limit)
        failed = sum(1 for item in transcripts if item.status != "ok")
        return RuntimeContextSection(
            "runtime_state",
            "ok" if not failed else "advisory",
            f"{len(approvals)} pending approval(s), {len(transcripts)} recent tool call(s), failed={failed}",
            {
                "pending_approvals": [approval.approval_id for approval in approvals[:12]],
                "recent_tools": [_transcript_dict(item) for item in transcripts],
            },
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:266", exc)
        return RuntimeContextSection("runtime_state", "warn", f"runtime state unavailable: {type(exc).__name__}: {exc}")


def _mode_policy(mode: AgentMode) -> dict[str, Any]:
    return {
        "name": mode.name,
        "profile": mode.profile,
        "context_policy": mode.context_policy,
        "source_checks": mode.source_checks,
        "apply_gate": mode.apply_gate,
        "isolation": mode.isolation,
        "default_action": mode.default_action,
    }


def _load_or_refresh_diagnostics(project: Path) -> DiagnosticSnapshot:
    try:
        return load_diagnostic_registry(project)
    except (OSError, ValueError, KeyError):
        return refresh_diagnostic_registry(project, limit=300)


def _diagnostics_for_paths(snapshot: DiagnosticSnapshot, paths: tuple[str, ...]) -> list[Any]:
    if not paths:
        return list(snapshot.diagnostics)
    wanted = set(paths)
    return [
        item
        for item in snapshot.diagnostics
        if item.path in wanted or any(item.path.startswith(prefix.rstrip("/") + "/") for prefix in wanted)
    ]


def _hit_dict(hit: RepoMapHit) -> dict[str, Any]:
    return hit.to_dict()


def _transcript_dict(transcript: ToolCallTranscript) -> dict[str, Any]:
    return {
        "invocation_id": transcript.invocation_id,
        "tool": transcript.tool,
        "status": transcript.status,
        "summary": transcript.summary,
        "error_kind": transcript.error_kind,
        "approval_id": transcript.approval_id,
        "checkpoint_id": transcript.checkpoint_id,
        "duration_ms": transcript.duration_ms,
    }


def _section_preview(data: dict[str, Any], *, max_items: int = 5) -> dict[str, str]:
    preview: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool)):
            preview[key] = str(value)
        elif isinstance(value, dict):
            preview[key] = _compact_dict(value, max_items=max_items)
        elif isinstance(value, list):
            preview[key] = _compact_list(value, max_items=max_items)
        elif isinstance(value, tuple):
            preview[key] = _compact_list(list(value), max_items=max_items)
        if len(preview) >= max_items:
            break
    return preview


def _compact_dict(value: dict[str, Any], *, max_items: int) -> str:
    parts = []
    for key, item in list(value.items())[:max_items]:
        parts.append(f"{key}={_scalar_preview(item)}")
    extra = len(value) - len(parts)
    suffix = f", +{extra} more" if extra > 0 else ""
    return ", ".join(parts) + suffix


def _compact_list(value: list[Any], *, max_items: int) -> str:
    parts = [_scalar_preview(item) for item in value[:max_items]]
    extra = len(value) - len(parts)
    suffix = f", +{extra} more" if extra > 0 else ""
    return "; ".join(parts) + suffix


def _scalar_preview(value: Any) -> str:
    if isinstance(value, dict):
        label = value.get("path") or value.get("tool") or value.get("check_id") or value.get("invocation_id") or value.get("message")
        if label:
            return str(label)[:120]
        return "{" + ",".join(str(key) for key in list(value)[:4]) + "}"
    text = str(value)
    return text.replace("\n", " ")[:140]


def _estimate_section_tokens(section: RuntimeContextSection) -> int:
    return max(16, len(section.summary) // 4 + len(str(section.data)) // 8)


def _normalize_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip().lstrip("./")
