from __future__ import annotations

import json
import hashlib
import os
import re
from dataclasses import asdict, dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

from . import __version__ as QUANTAGENT_VERSION


VALID_PERMISSION_ACTIONS = {"allow", "ask", "deny"}
VALID_STARTUP_HOOKS = {
    "before_context_build",
    "after_context_build",
    "before_model_call",
    "after_model_call",
    "before_tool_call",
    "permission_request",
    "after_tool_call",
    "before_patch_apply",
    "after_test_run",
    "before_agent_finalize",
    "after_agent_finalize",
}


@dataclass(frozen=True)
class PluginTool:
    name: str
    description: str = ""
    risk: str = "medium"


@dataclass(frozen=True)
class PluginSkill:
    name: str
    description: str = ""
    triggers: tuple[str, ...] = ()


@dataclass(frozen=True)
class PluginManifest:
    plugin_id: str
    name: str
    version: str
    description: str = ""
    tools: tuple[PluginTool, ...] = ()
    skills: tuple[PluginSkill, ...] = ()
    path: Path | None = None
    enabled: bool = True
    origin: str = "project"
    manifest_hash: str = ""
    startup_hooks: tuple[str, ...] = ()
    tool_permissions: dict[str, str] | None = None
    env_requirements: tuple[str, ...] = ()
    compatibility: dict[str, str] | None = None

    def to_record(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["path"] = str(self.path) if self.path else ""
        payload["tool_permissions"] = dict(self.tool_permissions or {})
        payload["compatibility"] = dict(self.compatibility or {})
        return payload


@dataclass(frozen=True)
class PluginDiagnostic:
    path: str
    level: str
    message: str


@dataclass(frozen=True)
class PluginExecutionDecision:
    plugin_id: str
    action: str
    reason: str
    isolation: str = ""

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PluginToolPermissionDecision:
    plugin_id: str
    tool: str
    action: str
    pattern: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PluginCompatDecision:
    plugin_id: str
    action: str
    requirement: str
    host_version: str
    reason: str

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PluginTrustReport:
    plugin_id: str
    level: str
    reasons: tuple[str, ...]
    requires_isolation: bool = True
    requires_approval: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PluginInstallState:
    plugin_id: str
    version: str
    enabled: bool
    origin: str
    manifest_hash: str
    path: str
    tools: tuple[str, ...] = ()
    compatibility: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tools"] = list(self.tools)
        payload["compatibility"] = dict(self.compatibility or {})
        return payload


@dataclass(frozen=True)
class PluginInstallSnapshot:
    schema: str
    snapshot_hash: str
    generated_at_ms: int
    policy_hash: str
    plugins: tuple[PluginInstallState, ...]
    diagnostics: tuple[PluginDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "snapshot_hash": self.snapshot_hash,
            "generated_at_ms": self.generated_at_ms,
            "policy_hash": self.policy_hash,
            "plugins": [plugin.to_dict() for plugin in self.plugins],
            "diagnostics": [asdict(item) for item in self.diagnostics],
        }


@dataclass(frozen=True)
class PluginRegistry:
    version: int
    generated_at_ms: int
    policy_hash: str
    plugins: tuple[PluginManifest, ...]
    diagnostics: tuple[PluginDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "generatedAtMs": self.generated_at_ms,
            "policyHash": self.policy_hash,
            "plugins": [plugin.to_record() for plugin in self.plugins],
            "diagnostics": [asdict(item) for item in self.diagnostics],
        }


class PluginManifestError(ValueError):
    pass


def plugin_dirs(project: Path) -> tuple[Path, ...]:
    return (
        project / ".quantagent" / "plugins",
        Path(__file__).resolve().parent.parent / "plugins",
    )


def _real(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _inside(path: Path, parent: Path) -> bool:
    path_real = _real(path)
    parent_real = _real(parent)
    return path_real == parent_real or parent_real in path_real.parents


def discover_plugin_manifests(project: Path) -> list[PluginManifest]:
    return [plugin for plugin in build_plugin_registry(project).plugins if plugin.enabled]


def build_plugin_registry(project: Path) -> PluginRegistry:
    manifests: list[PluginManifest] = []
    diagnostics: list[PluginDiagnostic] = []
    seen: dict[str, Path] = {}
    project_real = _real(project)
    for root in plugin_dirs(project):
        if not root.exists():
            continue
        for path in sorted(root.glob("*/quantagent.plugin.json")):
            try:
                manifest = load_manifest(path, allowed_root=root, origin="project" if project_real in _real(path).parents else "bundled")
            except PluginManifestError as exc:
                diagnostics.append(PluginDiagnostic(str(path), "error", str(exc)))
                continue
            manifest_diagnostics = _validate_manifest(manifest)
            diagnostics.extend(manifest_diagnostics)
            if any(item.level == "error" for item in manifest_diagnostics):
                continue
            if manifest.plugin_id in seen:
                diagnostics.append(
                    PluginDiagnostic(
                        str(path),
                        "error",
                        f"duplicate plugin id {manifest.plugin_id!r}; first seen at {seen[manifest.plugin_id]}",
                    )
                )
                continue
            seen[manifest.plugin_id] = manifest.path or path
            manifests.append(manifest)
    policy_payload = [
        {
            "id": manifest.plugin_id,
            "enabled": manifest.enabled,
            "hash": manifest.manifest_hash,
            "origin": manifest.origin,
            "startup_hooks": list(manifest.startup_hooks),
            "tool_permissions": dict(manifest.tool_permissions or {}),
            "env_requirements": list(manifest.env_requirements),
            "compatibility": dict(manifest.compatibility or {}),
        }
        for manifest in manifests
    ]
    policy_hash = hashlib.sha256(json.dumps(policy_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return PluginRegistry(
        version=1,
        generated_at_ms=_now_ms(),
        policy_hash=policy_hash,
        plugins=tuple(manifests),
        diagnostics=tuple(diagnostics),
    )


def load_manifest(path: Path, allowed_root: Path | None = None, *, origin: str = "project") -> PluginManifest:
    path = _real(path)
    if allowed_root is not None and not _inside(path, allowed_root):
        raise PluginManifestError(f"manifest escapes plugin root: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        raise PluginManifestError(f"invalid plugin manifest: {exc}") from exc
    if not isinstance(data, dict):
        raise PluginManifestError("plugin manifest must be an object")
    plugin_id = _required_str(data, "id")
    name = _required_str(data, "name")
    version = _required_str(data, "version")
    tools = tuple(_tool(item) for item in _list(data.get("tools")))
    skills = tuple(_skill(item) for item in _list(data.get("skills")))
    return PluginManifest(
        plugin_id=plugin_id,
        name=name,
        version=version,
        description=str(data.get("description") or ""),
        tools=tools,
        skills=skills,
        path=path,
        enabled=bool(data.get("enabled", True)),
        origin=origin,
        manifest_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        startup_hooks=tuple(str(item) for item in _list(data.get("startup_hooks") or data.get("startupHooks"))),
        tool_permissions=_str_dict(data.get("tool_permissions") or data.get("toolPermissions")),
        env_requirements=tuple(str(item) for item in _list(data.get("env_requirements") or data.get("envRequirements"))),
        compatibility=_str_dict(data.get("compatibility")),
    )


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginManifestError(f"missing required string field: {key}")
    return value.strip()


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _str_dict(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _tool(value: Any) -> PluginTool:
    if not isinstance(value, dict):
        raise PluginManifestError("tool entries must be objects")
    name = _required_str(value, "name")
    return PluginTool(
        name=name,
        description=str(value.get("description") or ""),
        risk=str(value.get("risk") or "medium"),
    )


def _skill(value: Any) -> PluginSkill:
    if not isinstance(value, dict):
        raise PluginManifestError("skill entries must be objects")
    name = _required_str(value, "name")
    triggers_raw = value.get("triggers")
    triggers = tuple(str(item) for item in triggers_raw) if isinstance(triggers_raw, list) else ()
    return PluginSkill(
        name=name,
        description=str(value.get("description") or ""),
        triggers=triggers,
    )


def _validate_manifest(manifest: PluginManifest) -> list[PluginDiagnostic]:
    diagnostics: list[PluginDiagnostic] = []
    location = str(manifest.path or manifest.plugin_id)
    for hook in manifest.startup_hooks:
        if hook not in VALID_STARTUP_HOOKS:
            diagnostics.append(
                PluginDiagnostic(
                    location,
                    "error",
                    f"unknown startup hook {hook!r}; expected one of: {', '.join(sorted(VALID_STARTUP_HOOKS))}",
                )
            )
    for pattern, action in sorted((manifest.tool_permissions or {}).items()):
        if not pattern.strip():
            diagnostics.append(PluginDiagnostic(location, "error", "tool permission pattern must not be empty"))
        if action not in VALID_PERMISSION_ACTIONS:
            diagnostics.append(
                PluginDiagnostic(
                    location,
                    "error",
                    f"tool permission for {pattern!r} must be allow, ask, or deny; got {action!r}",
                )
            )
    for env_name in manifest.env_requirements:
        if not env_name.strip() or any(char.isspace() for char in env_name):
            diagnostics.append(PluginDiagnostic(location, "error", f"invalid env requirement name {env_name!r}"))
        elif env_name not in os.environ:
            diagnostics.append(PluginDiagnostic(location, "warn", f"required environment variable {env_name} is not set"))
    compat = check_plugin_compat(manifest)
    if not compat.allowed:
        diagnostics.append(PluginDiagnostic(location, "error", compat.reason))
    return diagnostics


def resolve_plugin_tool_permission(manifest: PluginManifest, tool: str) -> PluginToolPermissionDecision:
    tool_name = str(tool or "").strip()
    declared = {item.name for item in manifest.tools}
    if not manifest.enabled:
        return PluginToolPermissionDecision(manifest.plugin_id, tool_name, "deny", "<disabled>", "plugin is disabled")
    if not tool_name:
        return PluginToolPermissionDecision(manifest.plugin_id, tool_name, "deny", "<empty>", "plugin tool name is required")
    if tool_name not in declared:
        return PluginToolPermissionDecision(manifest.plugin_id, tool_name, "deny", "<undeclared>", "plugin tool is not declared by manifest")
    action = "ask"
    matched = "<default-fail-closed>"
    for pattern, raw_action in (manifest.tool_permissions or {}).items():
        if fnmatchcase(tool_name, str(pattern)):
            action = str(raw_action).strip().lower()
            matched = str(pattern)
    if action not in VALID_PERMISSION_ACTIONS:
        action = "ask"
    return PluginToolPermissionDecision(
        manifest.plugin_id,
        tool_name,
        action,
        matched,
        f"{manifest.plugin_id}/{tool_name} {action} by plugin permission pattern {matched}",
    )


def plugin_execution_decision(
    manifest: PluginManifest,
    *,
    isolation: str = "",
    owner_approved: bool = False,
    tool: str = "",
) -> PluginExecutionDecision:
    """Gate future plugin execution behind explicit isolation.

    Mako plugins are metadata-only today. This function exists so callers
    do not accidentally execute plugin code without a declared isolation mode.
    """
    errors = [item.message for item in _validate_manifest(manifest) if item.level == "error"]
    if errors:
        return PluginExecutionDecision(manifest.plugin_id, "deny", errors[0], isolation)
    if not manifest.enabled:
        return PluginExecutionDecision(manifest.plugin_id, "deny", "plugin is disabled", isolation)
    if isolation != "worktree":
        return PluginExecutionDecision(manifest.plugin_id, "deny", "plugin execution requires worktree isolation", isolation)
    if not owner_approved:
        return PluginExecutionDecision(manifest.plugin_id, "ask", "plugin execution requires explicit owner approval", isolation)
    if tool:
        tool_decision = resolve_plugin_tool_permission(manifest, tool)
        if tool_decision.action == "deny":
            return PluginExecutionDecision(manifest.plugin_id, "deny", tool_decision.reason, isolation)
    return PluginExecutionDecision(manifest.plugin_id, "allow", "plugin execution allowed inside isolated worktree", isolation)


def check_plugin_compat(manifest: PluginManifest, *, host_version: str = QUANTAGENT_VERSION) -> PluginCompatDecision:
    requirement = str((manifest.compatibility or {}).get("quantagent") or "").strip()
    if not requirement:
        return PluginCompatDecision(manifest.plugin_id, "allow", "", host_version, "plugin has no quantagent compatibility requirement")
    if _version_satisfies(host_version, requirement):
        return PluginCompatDecision(manifest.plugin_id, "allow", requirement, host_version, f"quantagent {host_version} satisfies {requirement}")
    return PluginCompatDecision(manifest.plugin_id, "deny", requirement, host_version, f"quantagent {host_version} does not satisfy plugin compatibility {requirement}")


def build_plugin_install_snapshot(registry: PluginRegistry) -> PluginInstallSnapshot:
    states = tuple(
        sorted(
            (
                PluginInstallState(
                    plugin_id=plugin.plugin_id,
                    version=plugin.version,
                    enabled=plugin.enabled,
                    origin=plugin.origin,
                    manifest_hash=plugin.manifest_hash,
                    path=str(plugin.path or ""),
                    tools=tuple(sorted(tool.name for tool in plugin.tools)),
                    compatibility=dict(plugin.compatibility or {}),
                )
                for plugin in registry.plugins
            ),
            key=lambda item: item.plugin_id,
        )
    )
    snapshot_hash = hashlib.sha256(
        json.dumps([state.to_dict() for state in states], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return PluginInstallSnapshot(
        schema="quantagent.plugin_install_snapshot.v1",
        snapshot_hash=snapshot_hash,
        generated_at_ms=_now_ms(),
        policy_hash=registry.policy_hash,
        plugins=states,
        diagnostics=registry.diagnostics,
    )


def compare_plugin_install_snapshots(previous: PluginInstallSnapshot, current: PluginInstallSnapshot) -> dict[str, tuple[str, ...]]:
    previous_plugins = {plugin.plugin_id: plugin for plugin in previous.plugins}
    current_plugins = {plugin.plugin_id: plugin for plugin in current.plugins}
    previous_ids = set(previous_plugins)
    current_ids = set(current_plugins)
    changed = tuple(
        sorted(
            plugin_id
            for plugin_id in previous_ids & current_ids
            if previous_plugins[plugin_id].to_dict() != current_plugins[plugin_id].to_dict()
        )
    )
    return {
        "added": tuple(sorted(current_ids - previous_ids)),
        "removed": tuple(sorted(previous_ids - current_ids)),
        "changed": changed,
    }


def plugin_trust_report(manifest: PluginManifest) -> PluginTrustReport:
    reasons: list[str] = []
    risk_score = 0
    if manifest.origin != "bundled":
        risk_score += 1
        reasons.append(f"origin is {manifest.origin}")
    if manifest.startup_hooks:
        risk_score += 2
        reasons.append("declares startup hooks")
    if manifest.env_requirements:
        risk_score += 1
        reasons.append("requires environment variables")
    high_tools = [tool.name for tool in manifest.tools if tool.risk.lower() in {"high", "critical"}]
    if high_tools:
        risk_score += 2
        reasons.append("declares high-risk tools: " + ", ".join(high_tools))
    if manifest.tool_permissions:
        risk_score += 1
        reasons.append("declares tool permission overrides")
    level = "low" if risk_score <= 1 else "medium" if risk_score <= 3 else "high"
    if not reasons:
        reasons.append("metadata-only plugin with no elevated hooks or permissions")
    return PluginTrustReport(
        manifest.plugin_id,
        level,
        tuple(reasons),
        requires_isolation=level in {"medium", "high"},
        requires_approval=level != "low",
    )


def render_plugin_trust_reports(registry: PluginRegistry) -> str:
    if not registry.plugins:
        return "No plugin trust reports.\n"
    lines = ["# Plugin Trust Reports", ""]
    for manifest in registry.plugins:
        report = plugin_trust_report(manifest)
        lines.append(f"- [{report.level}] {manifest.plugin_id}: isolation={str(report.requires_isolation).lower()} approval={str(report.requires_approval).lower()}")
        lines.append("  reasons: " + "; ".join(report.reasons))
    return "\n".join(lines) + "\n"


def render_plugins(manifests: list[PluginManifest]) -> str:
    if not manifests:
        return "No Mako plugins discovered.\n"
    lines = ["# Mako Plugins", ""]
    for manifest in manifests:
        lines.append(f"- {manifest.plugin_id} {manifest.version}: {manifest.name}")
        if manifest.description:
            lines.append(f"  {manifest.description}")
        if manifest.tools:
            lines.append("  tools: " + ", ".join(tool.name for tool in manifest.tools))
        if manifest.skills:
            lines.append("  skills: " + ", ".join(skill.name for skill in manifest.skills))
    return "\n".join(lines) + "\n"


def plugin_registry_path(project: Path) -> Path:
    return project / ".quantagent" / "plugins" / "registry.json"


def write_plugin_registry(project: Path, registry: PluginRegistry) -> Path:
    path = plugin_registry_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registry.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_plugin_registry(registry: PluginRegistry) -> str:
    lines = [
        "# Mako Plugin Registry",
        "",
        f"- version: {registry.version}",
        f"- plugins: {len(registry.plugins)}",
        f"- diagnostics: {len(registry.diagnostics)}",
        f"- policy_hash: {registry.policy_hash}",
        "",
    ]
    if registry.plugins:
        lines.append("## Plugins")
        lines.append("")
        for plugin in registry.plugins:
            state = "enabled" if plugin.enabled else "disabled"
            lines.append(f"- [{state}] {plugin.plugin_id} {plugin.version}: {plugin.name} ({plugin.origin})")
            lines.append(f"  hash: {plugin.manifest_hash[:16]}")
            if plugin.startup_hooks:
                lines.append(f"  startup_hooks: {', '.join(plugin.startup_hooks)}")
            if plugin.tool_permissions:
                lines.append("  tool_permissions: " + ", ".join(f"{key}={value}" for key, value in sorted(plugin.tool_permissions.items())))
            if plugin.env_requirements:
                lines.append(f"  env: {', '.join(plugin.env_requirements)}")
    if registry.diagnostics:
        lines.extend(["", "## Diagnostics", ""])
        for item in registry.diagnostics:
            lines.append(f"- [{item.level}] {item.path}: {item.message}")
    return "\n".join(lines) + "\n"


def open_plugin_state_store(
    project: Path,
    plugin: PluginManifest | str,
    *,
    namespace: str,
    max_entries: int = 100,
    default_ttl_ms: int | None = None,
) -> Any:
    from .plugin_state_store import create_plugin_state_keyed_store

    plugin_id = plugin.plugin_id if isinstance(plugin, PluginManifest) else str(plugin)
    return create_plugin_state_keyed_store(
        project,
        plugin_id,
        namespace=namespace,
        max_entries=max_entries,
        default_ttl_ms=default_ttl_ms,
    )


def _version_satisfies(host_version: str, requirement: str) -> bool:
    host = _version_tuple(host_version)
    spec = requirement.strip()
    match = re.fullmatch(r"(>=|<=|==|>|<|=)?\s*v?(\d+(?:\.\d+){0,2})", spec)
    if not match:
        return False
    operator = match.group(1) or "=="
    target = _version_tuple(match.group(2))
    if operator == ">=":
        return host >= target
    if operator == "<=":
        return host <= target
    if operator in {"==", "="}:
        return host == target
    if operator == ">":
        return host > target
    if operator == "<":
        return host < target
    return False


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = [int(item) for item in re.findall(r"\d+", str(value or ""))[:3]]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _now_ms() -> int:
    import time

    return int(time.time() * 1000)
