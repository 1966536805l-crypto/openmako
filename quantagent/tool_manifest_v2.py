from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .mcp_tool_manager import validate_tool_name
from .plugin_runtime import build_plugin_registry
from .tool_registry import list_tools


MANIFEST_VERSION = 2
VALID_RISKS = {"low", "medium", "high", "critical"}
VALID_PERMISSION_MODES = {"allow", "ask", "deny"}
VALID_RENDERERS = {"text", "diff", "table", "json", "artifact", "approval", "diagnostic"}


@dataclass(frozen=True)
class ToolPromptSpec:
    purpose: str
    preconditions: tuple[str, ...] = ()
    success_criteria: tuple[str, ...] = ()
    failure_modes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolPermissionSpec:
    mode: str
    risk: str
    requires_approval: bool = False
    allow_always_supported: bool = True
    audit_level: str = "standard"
    policy_tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolRendererSpec:
    kind: str = "text"
    title: str = ""
    collapse_threshold_chars: int = 4000
    artifact_output: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolRuntimeSpec:
    runtime: str = "python"
    entrypoint: str = ""
    timeout_seconds: int = 120
    concurrency_key: str = ""
    side_effects: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolManifestV2:
    name: str
    description: str
    source: str
    prompt: ToolPromptSpec
    permission: ToolPermissionSpec
    renderer: ToolRendererSpec = field(default_factory=ToolRendererSpec)
    runtime: ToolRuntimeSpec = field(default_factory=ToolRuntimeSpec)
    aliases: tuple[str, ...] = ()
    version: int = MANIFEST_VERSION
    provenance: str = "clean-room"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "aliases": list(self.aliases),
            "prompt": self.prompt.to_dict(),
            "permission": self.permission.to_dict(),
            "renderer": self.renderer.to_dict(),
            "runtime": self.runtime.to_dict(),
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class ToolManifestDiagnostic:
    tool: str
    level: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolManifestCatalog:
    version: int
    catalog_hash: str
    tools: tuple[ToolManifestV2, ...]
    diagnostics: tuple[ToolManifestDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "catalog_hash": self.catalog_hash,
            "tools": [tool.to_dict() for tool in self.tools],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


def build_tool_manifest_catalog(project: str | Path | None = None) -> ToolManifestCatalog:
    manifests: list[ToolManifestV2] = [_from_builtin_tool(tool) for tool in list_tools()]
    diagnostics: list[ToolManifestDiagnostic] = []
    if project is not None:
        registry = build_plugin_registry(Path(project).expanduser().resolve(strict=False))
        for plugin in registry.plugins:
            for tool in plugin.tools:
                manifests.append(
                    ToolManifestV2(
                        name=tool.name,
                        description=tool.description or f"Plugin tool from {plugin.plugin_id}",
                        source=f"plugin:{plugin.plugin_id}",
                        prompt=ToolPromptSpec(
                            purpose=tool.description or f"Run plugin tool {tool.name}.",
                            preconditions=("Plugin manifest is enabled and trusted for this project.",),
                            success_criteria=("Tool returns a structured result or clear failure reason.",),
                        ),
                        permission=ToolPermissionSpec(
                            mode=(plugin.tool_permissions or {}).get(tool.name, _permission_mode_for_risk(tool.risk)),
                            risk=_normalize_risk(tool.risk),
                            requires_approval=_normalize_risk(tool.risk) in {"high", "critical"},
                            policy_tags=("plugin", plugin.plugin_id),
                        ),
                        renderer=ToolRendererSpec(kind="json", title=tool.name, artifact_output=True),
                        runtime=ToolRuntimeSpec(runtime="plugin", entrypoint=tool.name, side_effects=("plugin",)),
                        provenance="plugin-manifest",
                    )
                )
        diagnostics.extend(
            ToolManifestDiagnostic("plugin-registry", item.level, item.message) for item in registry.diagnostics
        )
    diagnostics.extend(validate_tool_manifests(manifests))
    catalog_hash = _catalog_hash(manifests)
    return ToolManifestCatalog(
        version=MANIFEST_VERSION,
        catalog_hash=catalog_hash,
        tools=tuple(sorted(manifests, key=lambda item: item.name)),
        diagnostics=tuple(diagnostics),
    )


def validate_tool_manifests(tools: Iterable[ToolManifestV2]) -> list[ToolManifestDiagnostic]:
    diagnostics: list[ToolManifestDiagnostic] = []
    seen: dict[str, str] = {}
    for tool in tools:
        if not tool.name.strip():
            diagnostics.append(ToolManifestDiagnostic(tool.name, "error", "tool name is required"))
        name_validation = validate_tool_name(tool.name)
        for warning in name_validation.warnings:
            diagnostics.append(ToolManifestDiagnostic(tool.name, "warning" if name_validation.is_valid else "error", warning))
        old_source = seen.get(tool.name)
        if old_source:
            diagnostics.append(
                ToolManifestDiagnostic(tool.name, "error", f"duplicate tool name from {old_source} and {tool.source}")
            )
        seen[tool.name] = tool.source
        if tool.permission.mode not in VALID_PERMISSION_MODES:
            diagnostics.append(ToolManifestDiagnostic(tool.name, "error", f"invalid permission mode {tool.permission.mode!r}"))
        if tool.permission.risk not in VALID_RISKS:
            diagnostics.append(ToolManifestDiagnostic(tool.name, "error", f"invalid risk {tool.permission.risk!r}"))
        if tool.renderer.kind not in VALID_RENDERERS:
            diagnostics.append(ToolManifestDiagnostic(tool.name, "warning", f"unknown renderer {tool.renderer.kind!r}"))
        if tool.permission.risk in {"high", "critical"} and not tool.permission.requires_approval:
            diagnostics.append(ToolManifestDiagnostic(tool.name, "warning", "high risk tool should require approval"))
        if tool.runtime.timeout_seconds <= 0:
            diagnostics.append(ToolManifestDiagnostic(tool.name, "error", "timeout_seconds must be positive"))
    return diagnostics


def render_tool_manifest_catalog(catalog: ToolManifestCatalog, *, show_diagnostics: bool = True) -> str:
    lines = [
        "# Mako Tool Manifest v2",
        "",
        f"- tools: {len(catalog.tools)}",
        f"- hash: {catalog.catalog_hash}",
        "",
    ]
    for tool in catalog.tools:
        approval = " approval" if tool.permission.requires_approval else ""
        lines.append(f"- {tool.name} [{tool.permission.risk}/{tool.permission.mode}{approval}] {tool.source}: {tool.description}")
    if show_diagnostics and catalog.diagnostics:
        lines.extend(["", "## Diagnostics", ""])
        for diagnostic in catalog.diagnostics:
            lines.append(f"- [{diagnostic.level}] {diagnostic.tool}: {diagnostic.message}")
    return "\n".join(lines) + "\n"


def render_tool_manifest(tool: ToolManifestV2) -> str:
    return json.dumps(tool.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def find_tool_manifest(catalog: ToolManifestCatalog, name: str) -> ToolManifestV2:
    for tool in catalog.tools:
        if tool.name == name or name in tool.aliases:
            return tool
    raise KeyError(f"tool manifest not found: {name}")


def _from_builtin_tool(tool: Any) -> ToolManifestV2:
    risk = _normalize_risk(getattr(tool, "risk", "medium"))
    name = str(getattr(tool, "name", ""))
    description = str(getattr(tool, "description", ""))
    return ToolManifestV2(
        name=name,
        description=description,
        source="builtin",
        prompt=ToolPromptSpec(
            purpose=description or f"Run {name}.",
            preconditions=_preconditions_for_builtin(name, risk),
            success_criteria=("Return a concise status, artifact path, or structured error.",),
            failure_modes=("policy_blocked", "timeout", "tool_error"),
        ),
        permission=ToolPermissionSpec(
            mode="ask" if name in {"shell", "consensus", "model-test"} or name.startswith("desktop.") else _permission_mode_for_risk(risk),
            risk=risk,
            requires_approval=risk in {"high", "critical"} or name in {"shell", "consensus", "model-test"} or name.startswith("desktop."),
            policy_tags=_policy_tags(name, risk),
        ),
        renderer=ToolRendererSpec(
            kind="diff" if "edit" in name or "apply" in name else ("table" if name in {"status", "todo", "registry"} else "text"),
            title=name,
            artifact_output=name in {"shell", "experiment", "run-next", "agent-v2"},
        ),
        runtime=ToolRuntimeSpec(
            runtime="python",
            entrypoint=f"quantagent.tool_registry:{name}",
            timeout_seconds=600 if name in {"experiment", "run-next", "agent-v2"} else 120,
            concurrency_key="workspace-write" if name in {"shell", "state", "todo", "run-next"} else "",
            side_effects=_side_effects(name),
        ),
    )


def _normalize_risk(value: str) -> str:
    value = str(value or "medium").lower()
    if value in VALID_RISKS:
        return value
    if value in {"critical", "danger", "dangerous"}:
        return "critical"
    return "medium"


def _permission_mode_for_risk(risk: str) -> str:
    risk = _normalize_risk(risk)
    if risk in {"high", "critical"}:
        return "ask"
    return "allow"


def _preconditions_for_builtin(name: str, risk: str) -> tuple[str, ...]:
    items = ["Project path has been resolved and workspace trust is known."]
    if risk in {"high", "critical"} or name == "shell":
        items.append("Permission policy has been evaluated and approval recorded when required.")
    if name in {"edit", "apply-gate", "diff-preview"}:
        items.append("Diff preview exists before filesystem mutation.")
    return tuple(items)


def _policy_tags(name: str, risk: str) -> tuple[str, ...]:
    tags = [risk]
    if name == "shell":
        tags.append("shell")
    if name.startswith("desktop."):
        tags.append("desktop")
    if name in {"state", "todo", "files", "edit"}:
        tags.append("filesystem")
    return tuple(tags)


def _side_effects(name: str) -> tuple[str, ...]:
    effects: list[str] = []
    if name in {"state", "todo", "hooks", "run-next", "loop", "experiment", "shell"}:
        effects.append("filesystem")
    if name in {"ask", "consensus", "model-test"}:
        effects.append("network")
    if name == "shell":
        effects.append("process")
    if name in {"desktop.shot", "desktop.grid", "desktop.ax", "desktop.ocr", "desktop.som", "desktop.tokenize", "desktop.find"}:
        effects.append("screen-read")
    if name.startswith("desktop.") and name not in {"desktop.shot", "desktop.grid", "desktop.ax", "desktop.ocr", "desktop.som", "desktop.tokenize", "desktop.decide", "desktop.find"}:
        effects.append("desktop-input")
    return tuple(effects)


def _catalog_hash(tools: Iterable[ToolManifestV2]) -> str:
    payload = [tool.to_dict() for tool in sorted(tools, key=lambda item: item.name)]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
