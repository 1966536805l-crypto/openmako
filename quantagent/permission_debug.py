from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .agent_profiles import load_agent_profile_config
from .policy_gate import enforce_tool
from .runtime_store import ToolInvocationRecord, list_tool_invocations
from .shell_semantics import classify_shell_command


@dataclass(frozen=True)
class PermissionShadow:
    pattern: str
    previous_pattern: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PermissionExplanation:
    profile: str
    tool: str
    decision: dict[str, Any]
    args: dict[str, Any] = field(default_factory=dict)
    shell_semantics: dict[str, Any] | None = None
    shadowed_rules: tuple[PermissionShadow, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "tool": self.tool,
            "decision": self.decision,
            "args": self.args,
            "shell_semantics": self.shell_semantics,
            "shadowed_rules": [item.to_dict() for item in self.shadowed_rules],
        }


def explain_permission(
    project: str | Path,
    *,
    profile: str,
    tool: str,
    args: dict[str, Any] | None = None,
    owner_approved: bool = False,
) -> PermissionExplanation:
    project_path = Path(project).expanduser().resolve(strict=False)
    payload = args or {}
    decision = enforce_tool(profile, tool, project=project_path, args=payload, owner_approved=owner_approved)
    shell = None
    command = _command_from_args(payload)
    if tool.strip().lower().replace("-", "_") in {"bash", "shell", "command"} and command:
        shell = classify_shell_command(command, cwd=payload.get("cwd") or project_path, project=project_path).to_dict()
    return PermissionExplanation(
        profile=profile,
        tool=tool,
        decision=decision.metadata(),
        args=payload,
        shell_semantics=shell,
        shadowed_rules=tuple(find_shadowed_permission_rules(project_path, profile)),
    )


def find_shadowed_permission_rules(project: str | Path, profile: str) -> list[PermissionShadow]:
    config = load_agent_profile_config(project)
    agent = config.agents.get(profile)
    if agent is None:
        return []
    shadows: list[PermissionShadow] = []
    seen: dict[str, str] = {}
    for pattern in _flatten_patterns(agent.permission):
        normalized = _normalize_pattern(pattern)
        if normalized in seen:
            shadows.append(PermissionShadow(pattern, seen[normalized], "later rule has the same normalized pattern and wins ties"))
        for previous in seen:
            if previous == "*" and normalized != "*":
                continue
            if normalized.startswith(previous.rstrip("*")) and previous.endswith("*"):
                shadows.append(PermissionShadow(pattern, seen[previous], "earlier wildcard may make this rule harder to reason about"))
        seen[normalized] = pattern
    return shadows


def recent_permission_denials(project: str | Path, *, limit: int = 20) -> list[ToolInvocationRecord]:
    records = list_tool_invocations(project, limit=max(limit * 4, limit))
    denials: list[ToolInvocationRecord] = []
    for record in records:
        if record.error_kind == "policy_blocked":
            denials.append(record)
            continue
        try:
            policy = json.loads(record.policy_json or "{}")
        except json.JSONDecodeError:
            policy = {}
        if policy.get("action") == "deny" or (policy.get("action") == "ask" and record.status == "failed"):
            denials.append(record)
        if len(denials) >= limit:
            break
    return denials


def render_permission_explanation(explanation: PermissionExplanation) -> str:
    decision = explanation.decision
    lines = [
        "# Permission Explanation",
        "",
        f"- profile: {explanation.profile}",
        f"- tool: {explanation.tool}",
        f"- action: {decision.get('action', '')}",
        f"- allowed: {str(bool(decision.get('allowed'))).lower()}",
        f"- approval_required: {str(bool(decision.get('approval_required'))).lower()}",
        f"- policy_reason: {decision.get('policy_reason', '')}",
    ]
    policy_v2 = decision.get("policy_v2") if isinstance(decision.get("policy_v2"), dict) else None
    if policy_v2:
        rule = f" rule={policy_v2.get('rule_id')}" if policy_v2.get("rule_id") else ""
        lines.append(f"- policy_v2: {policy_v2.get('action')} risk={policy_v2.get('risk') or 'unknown'}{rule}")
    if decision.get("shell_risk"):
        lines.append(f"- shell_risk: {decision.get('shell_risk')}")
    if decision.get("shell_subjects"):
        lines.append("- shell_subjects: " + ", ".join(decision.get("shell_subjects") or []))
    if explanation.shadowed_rules:
        lines.extend(["", "## Shadowed Or Ambiguous Rules"])
        lines.extend(f"- {item.pattern} after {item.previous_pattern}: {item.reason}" for item in explanation.shadowed_rules)
    return "\n".join(lines) + "\n"


def render_recent_denials(records: list[ToolInvocationRecord]) -> str:
    if not records:
        return "No recent permission denials.\n"
    lines = ["# Recent Permission Denials", ""]
    for record in records:
        lines.append(f"- {record.invocation_id} {record.tool} {record.status} {record.error_kind}: {record.summary}")
    return "\n".join(lines) + "\n"


def _command_from_args(args: dict[str, Any]) -> str:
    for key in ("command", "cmd", "script", "input"):
        value = args.get(key)
        if isinstance(value, str):
            return value
    return ""


def _flatten_patterns(permission: Any, prefix: str = "") -> list[str]:
    if not isinstance(permission, dict):
        return []
    patterns: list[str] = []
    for key, value in permission.items():
        pattern = f"{prefix}.{key}" if prefix else str(key)
        patterns.append(pattern)
        patterns.extend(_flatten_patterns(value, pattern))
    return patterns


def _normalize_pattern(pattern: str) -> str:
    return pattern.strip().lower().replace("-", "_").replace(":", ".")
