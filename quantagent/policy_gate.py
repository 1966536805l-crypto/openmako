from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from .agent_modes import resolve_agent_mode_permission
from .agent_profiles import resolve_agent_permission
from .permission_policy_v2 import PermissionDecisionV2, evaluate_permission_v2, permission_policy_path
from .sandbox_policy import ALLOW, ASK, DENY, classify_tool
from .shell_semantics import ShellSemantics, classify_shell_command


T = TypeVar("T")


@dataclass(frozen=True)
class PolicyDecision:
    profile: str
    tool: str
    action: str
    allowed: bool
    owner_approved: bool
    reason: str
    policy_reason: str
    summary: str
    shell_risk: str = ""
    shell_subjects: tuple[str, ...] = ()
    policy_v2: dict[str, Any] | None = None
    approval_required: bool = False

    @property
    def ok(self) -> bool:
        return self.allowed

    def metadata(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.policy_v2 is None:
            payload.pop("policy_v2", None)
        return payload


def enforce_tool(
    profile: str,
    tool: str,
    reason: str = "",
    owner_approved: bool = False,
    project: str | Path | None = None,
    args: dict[str, Any] | None = None,
) -> PolicyDecision:
    policy_args = _args_with_project(args, project)
    mode_decision = resolve_agent_mode_permission(project, profile, tool, owner_approved=owner_approved)
    if mode_decision is not None:
        action, policy_reason = mode_decision.action, mode_decision.reason
    else:
        agent_decision = resolve_agent_permission(project, profile, tool, args=policy_args)
        if agent_decision is not None:
            action, policy_reason = agent_decision.action, agent_decision.reason
        else:
            action, policy_reason = classify_tool(tool, profile=profile)
    shell_semantics = _shell_semantics_for_tool(tool, policy_args, project)
    if shell_semantics is not None:
        if shell_semantics.deny_hardline:
            action = DENY
            policy_reason = _append_policy_reason(
                policy_reason,
                "shell semantics hard-deny: " + "; ".join(shell_semantics.reasons),
            )
        elif action == ALLOW and shell_semantics.risk_level.startswith("L4"):
            action = ASK
            policy_reason = _append_policy_reason(
                policy_reason,
                f"shell semantics escalated to ask ({shell_semantics.risk_level})",
            )
    v2_decision = _permission_v2_decision(project, policy_args, tool)
    if v2_decision is not None:
        action, policy_reason = _merge_v2_decision(
            action,
            policy_reason,
            v2_decision,
            hard_deny=bool(shell_semantics and shell_semantics.deny_hardline),
        )
    allowed = action == ALLOW or (action == ASK and owner_approved)
    approval_required = action == ASK and not allowed
    summary = _decision_summary(
        profile=profile,
        tool=tool,
        action=action,
        allowed=allowed,
        owner_approved=owner_approved,
        reason=reason,
        policy_reason=policy_reason,
    )
    return PolicyDecision(
        profile=profile,
        tool=tool.strip(),
        action=action,
        allowed=allowed,
        owner_approved=owner_approved,
        reason=reason,
        policy_reason=policy_reason,
        summary=summary,
        shell_risk=shell_semantics.risk_level if shell_semantics is not None else "",
        shell_subjects=shell_semantics.subjects if shell_semantics is not None else (),
        policy_v2=v2_decision.to_dict() if v2_decision is not None else None,
        approval_required=approval_required,
    )


def require_tool(
    profile: str,
    tool: str,
    reason: str = "",
    owner_approved: bool = False,
    project: str | Path | None = None,
    args: dict[str, Any] | None = None,
) -> PolicyDecision:
    decision = enforce_tool(profile, tool, reason=reason, owner_approved=owner_approved, project=project, args=args)
    if not decision.allowed:
        raise PermissionError(decision.summary)
    return decision


def run_with_policy(
    profile: str,
    tool: str,
    func: Callable[..., T],
    *args: Any,
    reason: str = "",
    owner_approved: bool = False,
    project: str | Path | None = None,
    args_payload: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[PolicyDecision, T]:
    decision = require_tool(profile, tool, reason=reason, owner_approved=owner_approved, project=project, args=args_payload)
    return decision, func(*args, **kwargs)


def decision_metadata(decision: PolicyDecision) -> dict[str, Any]:
    return decision.metadata()


def tool_policy_metadata(
    profile: str,
    tool: str,
    reason: str = "",
    owner_approved: bool = False,
    project: str | Path | None = None,
    args: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return enforce_tool(
        profile,
        tool,
        reason=reason,
        owner_approved=owner_approved,
        project=project,
        args=args,
    ).metadata()


def _decision_summary(
    *,
    profile: str,
    tool: str,
    action: str,
    allowed: bool,
    owner_approved: bool,
    reason: str,
    policy_reason: str,
) -> str:
    status = "allowed" if allowed else "blocked"
    approval = " owner-approved" if owner_approved else ""
    parts = [f"{tool.strip() or '<empty>'} {status} by {profile} policy ({action}{approval})"]
    if reason:
        parts.append(f"reason: {reason}")
    parts.append(policy_reason)
    return "; ".join(parts)


def _shell_semantics_for_tool(tool: str, args: dict[str, Any] | None, project: str | Path | None) -> ShellSemantics | None:
    normalized = tool.strip().lower().replace("-", "_")
    if normalized not in {"bash", "shell", "command"}:
        return None
    if not isinstance(args, dict):
        return None
    command = _first_arg_text(args, ("command", "cmd", "script", "input"))
    if not command:
        return None
    cwd = _first_arg_text(args, ("cwd", "working_dir", "workdir")) or project
    project_arg = project or _first_arg_text(args, ("project", "project_path", "root")) or cwd
    return classify_shell_command(command, cwd=cwd, project=project_arg)


def _args_with_project(args: dict[str, Any] | None, project: str | Path | None) -> dict[str, Any] | None:
    if not isinstance(args, dict):
        if project is None:
            return args
        return {"project": str(project)}
    if project is None or any(key in args for key in ("project", "project_path", "root")):
        return args
    merged = dict(args)
    merged["project"] = str(project)
    return merged


def _first_arg_text(args: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _append_policy_reason(base: str, extra: str) -> str:
    if not base:
        return extra
    if not extra:
        return base
    return f"{base}; {extra}"


def _permission_v2_decision(project: str | Path | None, args: dict[str, Any] | None, tool: str) -> PermissionDecisionV2 | None:
    if project is None:
        return None
    project_path = Path(project).expanduser().resolve(strict=False)
    if not permission_policy_path(project_path).exists():
        return None
    try:
        return evaluate_permission_v2(project_path, tool=tool, args=args or {})
    except (OSError, ValueError):
        return None


def _merge_v2_decision(
    action: str,
    policy_reason: str,
    v2_decision: PermissionDecisionV2,
    *,
    hard_deny: bool,
) -> tuple[str, str]:
    v2_action = v2_decision.action
    if action == DENY or hard_deny:
        final = DENY
    elif v2_action in {ALLOW, ASK, DENY}:
        final = v2_action
    else:
        final = action
    reason = _append_policy_reason(
        policy_reason,
        f"permission v2 {v2_decision.action}"
        + (f" rule={v2_decision.rule_id}" if v2_decision.rule_id else "")
        + f": {v2_decision.reason}",
    )
    return final, reason
