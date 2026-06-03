from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .sandbox_policy import ALLOW, ASK, DENY, matches_tool_pattern
from .tool_manifest_v2 import ToolManifestCatalog, ToolManifestV2, build_tool_manifest_catalog


MODE_CONFIG_PATH = ".quantagent/modes.json"
VALID_ACTIONS = {ALLOW, ASK, DENY}


@dataclass(frozen=True)
class ModeToolRule:
    action: str
    patterns: tuple[str, ...]
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["patterns"] = list(self.patterns)
        return payload


@dataclass(frozen=True)
class AgentMode:
    name: str
    description: str
    profile: str
    prompt_overlay: str = ""
    context_policy: str = "standard"
    source_checks: str = "optional"
    apply_gate: str = "optional"
    isolation: str = "host"
    default_action: str = ASK
    rules: tuple[ModeToolRule, ...] = ()
    source: str = "builtin"
    tags: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "profile": self.profile,
            "prompt_overlay": self.prompt_overlay,
            "context_policy": self.context_policy,
            "source_checks": self.source_checks,
            "apply_gate": self.apply_gate,
            "isolation": self.isolation,
            "default_action": self.default_action,
            "rules": [rule.to_dict() for rule in self.rules],
            "source": self.source,
            "tags": list(self.tags),
        }


@dataclass(frozen=True)
class AgentModeDecision:
    mode: str
    tool: str
    action: str
    allowed: bool
    matched_rule: str
    reason: str
    profile: str
    source_checks: str
    apply_gate: str
    isolation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"runtime": "agent_mode"}


@dataclass(frozen=True)
class AgentModeToolView:
    tool: str
    action: str
    risk: str
    requires_approval: bool
    reason: str
    renderer: str = ""
    side_effects: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["side_effects"] = list(self.side_effects)
        return payload


@dataclass(frozen=True)
class AgentModeDiagnostic:
    mode: str
    level: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def builtin_agent_modes() -> tuple[AgentMode, ...]:
    return (
        AgentMode(
            name="plan",
            profile="plan",
            description="Read-only planning mode. It can inspect context and produce plans, but cannot mutate the workspace.",
            prompt_overlay="Plan first. Do not edit files or run mutating commands.",
            context_policy="repo_map+diagnostics",
            source_checks="advisory",
            apply_gate="required_for_apply",
            isolation="host-readonly",
            default_action=DENY,
            rules=(
                ModeToolRule(ALLOW, ("status", "context", "audit", "validate", "registry", "tools", "skills"), "readonly project context"),
                ModeToolRule(ALLOW, ("file_read", "file_search", "glob", "grep", "index*", "repo-map", "repo_map", "diagnostics", "lsp*"), "readonly code inspection"),
                ModeToolRule(ALLOW, ("tool-manifest", "policy-v2", "checks", "source_checks", "task-graph", "event-log"), "planning metadata"),
                ModeToolRule(DENY, ("edit", "file_write", "file_edit", "apply_patch", "apply-gate.apply", "shell", "command", "experiment", "run_p4"), "plan mode is non-mutating"),
            ),
            tags=("readonly", "planning"),
        ),
        AgentMode(
            name="build",
            profile="build",
            description="Default coding mode. Writes and shell commands require approval and source checks are enforced by apply gate.",
            prompt_overlay="Make small reviewed changes, run focused tests, and respect source checks.",
            context_policy="repo_map+retrieval+lsp",
            source_checks="enforced",
            apply_gate="required",
            isolation="host-or-worktree",
            default_action=ASK,
            rules=(
                ModeToolRule(ALLOW, ("status", "context", "audit", "validate", "registry", "file_read", "file_search", "index*", "repo-map", "checks"), "safe project context"),
                ModeToolRule(ALLOW, ("py_compile", "test", "diff-preview", "apply-gate.evaluate"), "safe local validation"),
                ModeToolRule(ASK, ("edit", "file_write", "file_edit", "apply_patch", "apply-gate*", "shell", "command", "mcp:*"), "build mode requires approval for side effects"),
                ModeToolRule(DENY, ("raw_data_mutation", "account_funds", "secret_exfiltration"), "hard safety boundary"),
            ),
            tags=("coding", "default"),
        ),
        AgentMode(
            name="review",
            profile="audit",
            description="Review-only mode. It can inspect diffs, diagnostics, checks, and reports without mutating the workspace.",
            prompt_overlay="Review evidence first. Report risks and missing tests; do not write files.",
            context_policy="diff+diagnostics+repo_map",
            source_checks="enforced_readonly",
            apply_gate="evaluate_only",
            isolation="host-readonly",
            default_action=DENY,
            rules=(
                ModeToolRule(ALLOW, ("status", "context", "audit", "validate", "registry", "file_read", "file_search", "repo-map", "checks", "diagnostics", "diff-preview", "apply-gate.evaluate"), "review evidence"),
                ModeToolRule(ALLOW, ("event-log", "task-graph", "transcript*", "checkpoint.show", "checkpoint.list"), "runtime evidence"),
                ModeToolRule(DENY, ("edit", "file_write", "file_edit", "apply_patch", "shell", "command", "apply-gate.apply", "experiment", "run_p4"), "review mode cannot mutate"),
            ),
            tags=("readonly", "review"),
        ),
        AgentMode(
            name="repair",
            profile="build",
            description="Repair mode. It can run isolated repair loops and prepare review bundles; main workspace apply still goes through apply gate.",
            prompt_overlay="Prefer isolated worktrees, classify failures, and produce a parent-reviewable patch.",
            context_policy="repo_map+retrieval+lsp+failure_feedback",
            source_checks="enforced",
            apply_gate="required",
            isolation="worktree",
            default_action=ASK,
            rules=(
                ModeToolRule(ALLOW, ("status", "context", "audit", "validate", "file_read", "file_search", "repo-map", "diagnostics", "retrieval", "index*"), "repair context"),
                ModeToolRule(ALLOW, ("py_compile", "test", "checks", "diff-preview", "apply-gate.evaluate"), "safe repair validation"),
                ModeToolRule(ASK, ("edit", "file_write", "file_edit", "apply_patch", "shell", "command", "isolation*", "subagent*", "apply-gate*"), "repair side effects require approval/review"),
                ModeToolRule(DENY, ("raw_data_mutation", "account_funds", "secret_exfiltration"), "hard safety boundary"),
            ),
            tags=("repair", "isolated"),
        ),
        AgentMode(
            name="research",
            profile="plan",
            description="Research mode. It can read, search, summarize, and query context without risky local mutation.",
            prompt_overlay="Gather evidence, cite artifacts, and avoid workspace mutation.",
            context_policy="repo_map+retrieval",
            source_checks="advisory",
            apply_gate="not_applicable",
            isolation="host-readonly",
            default_action=ASK,
            rules=(
                ModeToolRule(ALLOW, ("status", "context", "audit", "validate", "registry", "file_read", "file_search", "repo-map", "retrieval", "index*", "ask"), "research context"),
                ModeToolRule(ASK, ("webfetch", "websearch", "mcp:*", "shell", "command"), "external or executable research needs approval"),
                ModeToolRule(DENY, ("edit", "file_write", "file_edit", "apply_patch", "experiment", "run_p4"), "research mode is non-mutating"),
            ),
            tags=("research", "readonly"),
        ),
        AgentMode(
            name="admin",
            profile="build",
            description="Administrative mode for daemon, plugin, MCP, session-bus, and runtime control. Most side effects require approval.",
            prompt_overlay="Operate control-plane tools conservatively and preserve audit trails.",
            context_policy="runtime+events+doctor",
            source_checks="optional",
            apply_gate="required_for_code",
            isolation="host",
            default_action=ASK,
            rules=(
                ModeToolRule(ALLOW, ("status", "doctor", "event-log", "task-graph", "session-bus.status", "session-bus.summary", "mcp-daemon.status", "plugins", "tool-manifest"), "admin inspection"),
                ModeToolRule(ASK, ("session-bus*", "mcp*", "mcp-daemon*", "plugins*", "hooks", "checkpoint*", "resume*", "shell", "command"), "control-plane side effect"),
                ModeToolRule(DENY, ("raw_data_mutation", "account_funds", "secret_exfiltration"), "hard safety boundary"),
            ),
            tags=("admin", "control-plane"),
        ),
    )


def agent_mode_config_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / MODE_CONFIG_PATH


def load_agent_modes(project: str | Path | None = None) -> dict[str, AgentMode]:
    modes = {mode.name: mode for mode in builtin_agent_modes()}
    if project is None:
        return modes
    path = agent_mode_config_path(project)
    if not path.exists():
        return modes
    data = json.loads(path.read_text(encoding="utf-8"))
    raw_modes = data.get("modes") if isinstance(data, dict) else None
    if not isinstance(raw_modes, dict):
        raise ValueError("agent modes config must contain a modes object")
    for name, raw in raw_modes.items():
        if not isinstance(raw, dict):
            raise ValueError(f"agent mode {name} must be an object")
        modes[str(name)] = _mode_from_mapping(str(name), raw, source=str(path))
    return modes


def list_agent_modes(project: str | Path | None = None) -> list[AgentMode]:
    return sorted(load_agent_modes(project).values(), key=lambda mode: mode.name)


def get_agent_mode(project: str | Path | None, name: str) -> AgentMode:
    modes = load_agent_modes(project)
    try:
        return modes[name]
    except KeyError as exc:
        raise KeyError(f"unknown agent mode: {name}") from exc


def resolve_agent_mode_permission(
    project: str | Path | None,
    mode_name: str,
    tool: str,
    *,
    owner_approved: bool = False,
) -> AgentModeDecision | None:
    try:
        mode = get_agent_mode(project, mode_name)
    except (KeyError, ValueError, json.JSONDecodeError):
        return None
    action, matched, reason = _mode_action(mode, tool)
    allowed = action == ALLOW or (action == ASK and owner_approved)
    return AgentModeDecision(
        mode=mode.name,
        tool=tool.strip(),
        action=action,
        allowed=allowed,
        matched_rule=matched,
        reason=reason,
        profile=mode.profile,
        source_checks=mode.source_checks,
        apply_gate=mode.apply_gate,
        isolation=mode.isolation,
    )


def mode_tool_views(
    project: str | Path | None,
    mode_name: str,
    *,
    catalog: ToolManifestCatalog | None = None,
) -> list[AgentModeToolView]:
    catalog = catalog or build_tool_manifest_catalog(project)
    return [_tool_view(project, mode_name, tool) for tool in catalog.tools]


def validate_agent_modes(project: str | Path | None = None) -> list[AgentModeDiagnostic]:
    diagnostics: list[AgentModeDiagnostic] = []
    try:
        modes = list_agent_modes(project)
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:288", exc)
        return [AgentModeDiagnostic("config", "error", f"agent mode config failed to load: {type(exc).__name__}: {exc}")]
    for mode in modes:
        if mode.default_action not in VALID_ACTIONS:
            diagnostics.append(AgentModeDiagnostic(mode.name, "error", f"invalid default_action {mode.default_action!r}"))
        if not mode.profile:
            diagnostics.append(AgentModeDiagnostic(mode.name, "error", "profile is required"))
        if mode.apply_gate == "required" and mode.source_checks not in {"enforced", "enforced_readonly"}:
            diagnostics.append(AgentModeDiagnostic(mode.name, "warning", "apply_gate required but source_checks are not enforced"))
        for rule in mode.rules:
            if rule.action not in VALID_ACTIONS:
                diagnostics.append(AgentModeDiagnostic(mode.name, "error", f"invalid rule action {rule.action!r}"))
            if not rule.patterns:
                diagnostics.append(AgentModeDiagnostic(mode.name, "warning", "rule has no patterns"))
    return diagnostics


def render_agent_modes(modes: Iterable[AgentMode]) -> str:
    items = list(modes)
    if not items:
        return "No agent modes.\n"
    lines = ["# Mako Agent Modes", ""]
    for mode in items:
        tags = f" tags={','.join(mode.tags)}" if mode.tags else ""
        lines.append(f"- {mode.name} profile={mode.profile} checks={mode.source_checks} gate={mode.apply_gate} isolation={mode.isolation}{tags}: {mode.description}")
    return "\n".join(lines) + "\n"


def render_agent_mode(mode: AgentMode) -> str:
    lines = [
        f"# Agent Mode {mode.name}",
        "",
        f"- source: {mode.source}",
        f"- profile: {mode.profile}",
        f"- context_policy: {mode.context_policy}",
        f"- source_checks: {mode.source_checks}",
        f"- apply_gate: {mode.apply_gate}",
        f"- isolation: {mode.isolation}",
        f"- default_action: {mode.default_action}",
        f"- tags: {', '.join(mode.tags) if mode.tags else '-'}",
        "",
        "## Description",
        "",
        mode.description,
    ]
    if mode.prompt_overlay:
        lines.extend(["", "## Prompt Overlay", "", mode.prompt_overlay])
    lines.extend(["", "## Tool Rules", ""])
    for rule in mode.rules:
        lines.append(f"- {rule.action}: {', '.join(rule.patterns)}")
        if rule.reason:
            lines.append(f"  reason: {rule.reason}")
    return "\n".join(lines) + "\n"


def render_mode_decision(decision: AgentModeDecision) -> str:
    return (
        f"{decision.action} mode={decision.mode} profile={decision.profile} tool={decision.tool} "
        f"allowed={str(decision.allowed).lower()} rule={decision.matched_rule or '<default>'}\n"
        f"reason: {decision.reason}\n"
        f"source_checks={decision.source_checks} apply_gate={decision.apply_gate} isolation={decision.isolation}\n"
    )


def render_mode_tool_views(views: Iterable[AgentModeToolView], *, mode_name: str) -> str:
    items = list(views)
    if not items:
        return f"No tools for mode {mode_name}.\n"
    lines = [f"# Agent Mode Tool Matrix: {mode_name}", ""]
    for view in items:
        approval = " approval" if view.requires_approval else ""
        effects = f" effects={','.join(view.side_effects)}" if view.side_effects else ""
        lines.append(f"- [{view.action}] {view.tool} risk={view.risk}{approval}{effects}: {view.reason}")
    return "\n".join(lines) + "\n"


def _tool_view(project: str | Path | None, mode_name: str, tool: ToolManifestV2) -> AgentModeToolView:
    decision = resolve_agent_mode_permission(project, mode_name, tool.name)
    if decision is None:
        raise KeyError(f"unknown agent mode: {mode_name}")
    return AgentModeToolView(
        tool=tool.name,
        action=decision.action,
        risk=tool.permission.risk,
        requires_approval=decision.action == ASK or tool.permission.requires_approval,
        reason=decision.reason,
        renderer=tool.renderer.kind,
        side_effects=tool.runtime.side_effects,
    )


def _mode_action(mode: AgentMode, tool: str) -> tuple[str, str, str]:
    normalized = tool.strip()
    for rule in mode.rules:
        for pattern in rule.patterns:
            if matches_tool_pattern(normalized, pattern):
                reason = rule.reason or f"{normalized} {rule.action} by mode {mode.name} pattern {pattern}"
                return rule.action, pattern, reason
    return mode.default_action, "<default>", f"{normalized} {mode.default_action} by mode {mode.name} default"


def _mode_from_mapping(name: str, raw: dict[str, Any], *, source: str) -> AgentMode:
    base = {mode.name: mode for mode in builtin_agent_modes()}.get(name)
    rules = raw.get("rules")
    parsed_rules = tuple(_rule_from_mapping(item) for item in rules) if isinstance(rules, list) else (base.rules if base else ())
    return AgentMode(
        name=name,
        description=str(raw.get("description") or (base.description if base else "")),
        profile=str(raw.get("profile") or (base.profile if base else "build")),
        prompt_overlay=str(raw.get("prompt_overlay") or raw.get("promptOverlay") or (base.prompt_overlay if base else "")),
        context_policy=str(raw.get("context_policy") or raw.get("contextPolicy") or (base.context_policy if base else "standard")),
        source_checks=str(raw.get("source_checks") or raw.get("sourceChecks") or (base.source_checks if base else "optional")),
        apply_gate=str(raw.get("apply_gate") or raw.get("applyGate") or (base.apply_gate if base else "optional")),
        isolation=str(raw.get("isolation") or (base.isolation if base else "host")),
        default_action=str(raw.get("default_action") or raw.get("defaultAction") or (base.default_action if base else ASK)),
        rules=parsed_rules,
        source=source,
        tags=tuple(str(item) for item in raw.get("tags") or (base.tags if base else ())),
    )


def _rule_from_mapping(raw: Any) -> ModeToolRule:
    if not isinstance(raw, dict):
        raise ValueError("mode rule must be an object")
    patterns = raw.get("patterns") or raw.get("tools") or raw.get("tool")
    if isinstance(patterns, str):
        parsed_patterns = (patterns,)
    elif isinstance(patterns, list):
        parsed_patterns = tuple(str(item) for item in patterns)
    else:
        parsed_patterns = ()
    return ModeToolRule(
        action=str(raw.get("action") or ASK),
        patterns=parsed_patterns,
        reason=str(raw.get("reason") or ""),
    )
