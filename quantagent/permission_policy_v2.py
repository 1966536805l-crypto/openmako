from __future__ import annotations

import fnmatch
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .tool_manifest_v2 import ToolManifestCatalog, build_tool_manifest_catalog


VALID_ACTIONS = {"allow", "ask", "deny"}
SEVERITY_ORDER = {"deny": 0, "ask": 1, "allow": 2}


@dataclass(frozen=True)
class PermissionRuleV2:
    rule_id: str
    action: str
    tool: str = "*"
    arg_contains: tuple[str, ...] = ()
    risk: str = ""
    priority: int = 0
    reason: str = ""
    expires_at_ms: int | None = None
    allow_always: bool = False
    source: str = "project"

    def matches(self, *, tool: str, args: Mapping[str, Any], risk: str = "") -> bool:
        if self.risk and self.risk != risk:
            return False
        if not fnmatch.fnmatch(tool, self.tool):
            return False
        if self.arg_contains:
            haystack = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str).lower()
            return all(fragment.lower() in haystack for fragment in self.arg_contains)
        return True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["arg_contains"] = list(self.arg_contains)
        return payload


@dataclass(frozen=True)
class PermissionDecisionV2:
    action: str
    tool: str
    risk: str
    reason: str
    rule_id: str = ""
    approval_required: bool = False
    allow_always: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PermissionLint:
    rule_id: str
    level: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PermissionPolicyV2:
    rules: tuple[PermissionRuleV2, ...] = field(default_factory=tuple)
    source_path: str = ""

    def evaluate(
        self,
        *,
        tool: str,
        args: Mapping[str, Any] | None = None,
        catalog: ToolManifestCatalog | None = None,
    ) -> PermissionDecisionV2:
        args = args or {}
        risk = _risk_for_tool(catalog, tool)
        sorted_rules = sorted(self.rules, key=lambda item: (-item.priority, SEVERITY_ORDER.get(item.action, 9), item.rule_id))
        for rule in sorted_rules:
            if rule.matches(tool=tool, args=args, risk=risk):
                return PermissionDecisionV2(
                    action=rule.action,
                    tool=tool,
                    risk=risk,
                    reason=rule.reason or f"matched permission rule {rule.rule_id}",
                    rule_id=rule.rule_id,
                    approval_required=rule.action == "ask",
                    allow_always=rule.allow_always,
                )
        default_action = "ask" if risk in {"high", "critical"} else "allow"
        return PermissionDecisionV2(
            action=default_action,
            tool=tool,
            risk=risk,
            reason=f"default {default_action} for {risk or 'unknown'} risk tool",
            approval_required=default_action == "ask",
        )

    def to_dict(self) -> dict[str, Any]:
        return {"version": 2, "source_path": self.source_path, "rules": [rule.to_dict() for rule in self.rules]}


def permission_policy_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "permissions.v2.json"


def load_permission_policy_v2(project: str | Path) -> PermissionPolicyV2:
    path = permission_policy_path(project)
    if not path.exists():
        return PermissionPolicyV2(rules=default_permission_rules(), source_path=str(path))
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("permission policy must be a JSON object")
    rules = tuple(_rule_from_dict(item, index=index) for index, item in enumerate(_list(data.get("rules"))))
    return PermissionPolicyV2(rules=rules, source_path=str(path))


def save_permission_policy_v2(project: str | Path, policy: PermissionPolicyV2) -> Path:
    path = permission_policy_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def add_permission_rule_v2(
    project: str | Path,
    *,
    action: str,
    tool: str = "*",
    arg_contains: Iterable[str] = (),
    risk: str = "",
    priority: int = 50,
    reason: str = "",
    allow_always: bool = False,
    rule_id: str = "",
) -> tuple[PermissionPolicyV2, PermissionRuleV2]:
    if action not in VALID_ACTIONS:
        raise ValueError(f"invalid action: {action}")
    policy = load_permission_policy_v2(project)
    existing = {rule.rule_id for rule in policy.rules}
    new_rule = PermissionRuleV2(
        rule_id=rule_id or _new_rule_id(action, tool, existing),
        action=action,
        tool=tool or "*",
        arg_contains=tuple(str(item) for item in arg_contains if str(item).strip()),
        risk=risk,
        priority=priority,
        reason=reason,
        allow_always=allow_always,
    )
    updated = PermissionPolicyV2(rules=policy.rules + (new_rule,), source_path=policy.source_path)
    lints = lint_permission_policy_v2(updated)
    errors = [item for item in lints if item.level == "error"]
    if errors:
        detail = "; ".join(f"{item.rule_id}: {item.message}" for item in errors)
        raise ValueError("permission rule invalid: " + detail)
    save_permission_policy_v2(project, updated)
    return updated, new_rule


def default_permission_rules() -> tuple[PermissionRuleV2, ...]:
    return (
        PermissionRuleV2("deny-destructive-shell", "deny", tool="shell", arg_contains=("rm -rf /",), priority=100, reason="hard destructive shell command"),
        PermissionRuleV2("ask-shell", "ask", tool="shell", priority=20, reason="shell commands can mutate the host"),
        PermissionRuleV2("ask-plugins", "ask", tool="plugin.*", priority=15, reason="plugin tools require explicit trust"),
        PermissionRuleV2("allow-readonly", "allow", tool="status", priority=10, reason="readonly project status"),
        PermissionRuleV2("allow-audit", "allow", tool="audit", priority=10, reason="readonly audit command"),
    )


def lint_permission_policy_v2(policy: PermissionPolicyV2) -> list[PermissionLint]:
    diagnostics: list[PermissionLint] = []
    seen_ids: set[str] = set()
    rules = list(policy.rules)
    for rule in rules:
        if rule.rule_id in seen_ids:
            diagnostics.append(PermissionLint(rule.rule_id, "error", "duplicate rule id"))
        seen_ids.add(rule.rule_id)
        if rule.action not in VALID_ACTIONS:
            diagnostics.append(PermissionLint(rule.rule_id, "error", f"invalid action {rule.action!r}"))
        if not rule.tool:
            diagnostics.append(PermissionLint(rule.rule_id, "error", "tool matcher is required"))
        if rule.expires_at_ms is not None and rule.expires_at_ms <= 0:
            diagnostics.append(PermissionLint(rule.rule_id, "warning", "expires_at_ms should be a positive unix timestamp in ms"))
    diagnostics.extend(_shadow_diagnostics(rules))
    diagnostics.extend(_conflict_diagnostics(rules))
    return diagnostics


def evaluate_permission_v2(
    project: str | Path,
    *,
    tool: str,
    args: Mapping[str, Any] | None = None,
) -> PermissionDecisionV2:
    project_path = Path(project).expanduser().resolve(strict=False)
    policy = load_permission_policy_v2(project_path)
    catalog = build_tool_manifest_catalog(project_path)
    return policy.evaluate(tool=tool, args=args or {}, catalog=catalog)


def render_permission_lints(lints: Iterable[PermissionLint]) -> str:
    items = list(lints)
    if not items:
        return "No permission policy v2 issues.\n"
    lines = ["# Permission Policy v2 Lint", ""]
    for item in items:
        lines.append(f"- [{item.level}] {item.rule_id}: {item.message}")
    return "\n".join(lines) + "\n"


def render_permission_decision(decision: PermissionDecisionV2) -> str:
    approval = " approval_required=true" if decision.approval_required else ""
    rule = f" rule={decision.rule_id}" if decision.rule_id else ""
    return f"{decision.action} tool={decision.tool} risk={decision.risk or 'unknown'}{approval}{rule}\nreason: {decision.reason}\n"


def _rule_from_dict(data: Any, *, index: int) -> PermissionRuleV2:
    if not isinstance(data, Mapping):
        raise ValueError("permission rule entries must be objects")
    return PermissionRuleV2(
        rule_id=str(data.get("rule_id") or data.get("id") or f"rule-{index + 1}"),
        action=str(data.get("action") or "ask"),
        tool=str(data.get("tool") or "*"),
        arg_contains=tuple(str(item) for item in _list(data.get("arg_contains") or data.get("argContains"))),
        risk=str(data.get("risk") or ""),
        priority=int(data.get("priority") or 0),
        reason=str(data.get("reason") or ""),
        expires_at_ms=_int_or_none(data.get("expires_at_ms") or data.get("expiresAtMs")),
        allow_always=bool(data.get("allow_always") or data.get("allowAlways")),
        source=str(data.get("source") or "project"),
    )


def _shadow_diagnostics(rules: list[PermissionRuleV2]) -> list[PermissionLint]:
    diagnostics: list[PermissionLint] = []
    ordered = sorted(rules, key=lambda item: (-item.priority, SEVERITY_ORDER.get(item.action, 9), item.rule_id))
    for index, rule in enumerate(ordered):
        for earlier in ordered[:index]:
            if earlier.priority < rule.priority:
                continue
            if earlier.tool == rule.tool and earlier.arg_contains == rule.arg_contains and earlier.risk == rule.risk:
                diagnostics.append(PermissionLint(rule.rule_id, "warning", f"shadowed by earlier rule {earlier.rule_id}"))
                break
    return diagnostics


def _conflict_diagnostics(rules: list[PermissionRuleV2]) -> list[PermissionLint]:
    diagnostics: list[PermissionLint] = []
    by_matcher: dict[tuple[str, tuple[str, ...], str, int], PermissionRuleV2] = {}
    for rule in rules:
        key = (rule.tool, rule.arg_contains, rule.risk, rule.priority)
        previous = by_matcher.get(key)
        if previous and previous.action != rule.action:
            diagnostics.append(
                PermissionLint(rule.rule_id, "error", f"conflicts with {previous.rule_id} on same matcher and priority")
            )
        by_matcher[key] = rule
    return diagnostics


def _risk_for_tool(catalog: ToolManifestCatalog | None, tool: str) -> str:
    if not catalog:
        return ""
    for manifest in catalog.tools:
        if manifest.name == tool:
            return manifest.permission.risk
    return ""


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _new_rule_id(action: str, tool: str, existing: set[str]) -> str:
    normalized = "".join(ch if ch.isalnum() else "-" for ch in f"{action}-{tool}".lower()).strip("-") or "rule"
    base = "rule-" + normalized[:48]
    candidate = base
    suffix = 1
    stamp = str(int(time.time() * 1000))[-5:]
    while candidate in existing:
        suffix += 1
        candidate = f"{base}-{stamp}-{suffix}"
    return candidate
