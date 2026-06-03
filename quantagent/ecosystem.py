from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .mcp_runtime import load_mcp_servers
from .plugin_runtime import build_plugin_registry
from .skills import list_skills
from .tool_manifest_v2 import build_tool_manifest_catalog


ECOSYSTEM_VERSION = 1
ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class EcosystemItem:
    kind: str
    name: str
    description: str
    source: str
    status: str = "available"
    risk: str = ""
    license: str = ""
    path: str = ""
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
        return payload


@dataclass(frozen=True)
class EcosystemDiagnostic:
    level: str
    source: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EcosystemCatalog:
    version: int
    project: str
    generated_at_ms: int
    catalog_hash: str
    counts: dict[str, int]
    items: tuple[EcosystemItem, ...]
    diagnostics: tuple[EcosystemDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "project": self.project,
            "generated_at_ms": self.generated_at_ms,
            "catalog_hash": self.catalog_hash,
            "counts": dict(self.counts),
            "items": [item.to_dict() for item in self.items],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


def ecosystem_catalog_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "ecosystem_catalog.json"


def build_ecosystem_catalog(project: str | Path) -> EcosystemCatalog:
    project_path = Path(project).expanduser().resolve(strict=False)
    items: list[EcosystemItem] = []
    diagnostics: list[EcosystemDiagnostic] = []

    skill_names: set[str] = set()
    for skill in list_skills(project_path):
        skill_names.add(skill.name)
        items.append(
            EcosystemItem(
                kind="skill",
                name=skill.name,
                description=skill.description,
                source=skill.source,
                status="installed" if skill.source == "project" else "available",
                license=skill.license,
                path=skill.path,
                tags=skill.triggers[:12],
                metadata={"trigger_count": len(skill.triggers)},
            )
        )

    plugin_registry = build_plugin_registry(project_path)
    for plugin in plugin_registry.plugins:
        items.append(
            EcosystemItem(
                kind="plugin",
                name=plugin.plugin_id,
                description=plugin.description or plugin.name,
                source=plugin.origin,
                status="enabled" if plugin.enabled else "disabled",
                path=str(plugin.path or ""),
                tags=tuple(sorted({"plugin", plugin.origin, *plugin.startup_hooks})),
                metadata={
                    "version": plugin.version,
                    "name": plugin.name,
                    "tools": [tool.name for tool in plugin.tools],
                    "skills": [skill.name for skill in plugin.skills],
                    "manifest_hash": plugin.manifest_hash,
                    "env_requirements": list(plugin.env_requirements),
                },
            )
        )
        for skill in plugin.skills:
            if skill.name not in skill_names:
                diagnostics.append(
                    EcosystemDiagnostic(
                        "warning",
                        f"plugin:{plugin.plugin_id}",
                        f"plugin skill {skill.name!r} is declared but not installed in the skill runtime",
                    )
                )
    diagnostics.extend(EcosystemDiagnostic(item.level, item.path, item.message) for item in plugin_registry.diagnostics)

    tool_catalog = build_tool_manifest_catalog(project_path)
    for tool in tool_catalog.tools:
        items.append(
            EcosystemItem(
                kind="tool",
                name=tool.name,
                description=tool.description,
                source=tool.source,
                status=tool.permission.mode,
                risk=tool.permission.risk,
                tags=tuple(sorted({*tool.permission.policy_tags, *tool.runtime.side_effects, tool.runtime.runtime})),
                metadata={
                    "requires_approval": tool.permission.requires_approval,
                    "runtime": tool.runtime.to_dict(),
                    "renderer": tool.renderer.to_dict(),
                    "provenance": tool.provenance,
                },
            )
        )
    diagnostics.extend(EcosystemDiagnostic(item.level, f"tool:{item.tool}", item.message) for item in tool_catalog.diagnostics)

    for server in load_mcp_servers(project_path):
        permission_values = tuple(sorted(set(server.permissions.values())))
        items.append(
            EcosystemItem(
                kind="mcp",
                name=server.name,
                description=server.url or " ".join(server.argv),
                source=server.transport,
                status="enabled" if server.enabled else "disabled",
                risk="medium" if "ask" in permission_values else "low",
                tags=tuple(sorted({"mcp", server.transport, *permission_values})),
                metadata={
                    "transport": server.transport,
                    "session_scoped": server.session_scoped,
                    "timeout": server.timeout,
                    "idle_ttl": server.idle_ttl,
                    "auth_profile": server.auth_profile,
                    "env_whitelist": list(server.env_whitelist),
                    "permissions": dict(server.permissions),
                },
            )
        )

    items.extend(_upstream_items())
    items = tuple(sorted(items, key=lambda item: (item.kind, item.name, item.source)))
    counts = dict(Counter(item.kind for item in items))
    payload = [item.to_dict() for item in items]
    catalog_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return EcosystemCatalog(
        version=ECOSYSTEM_VERSION,
        project=str(project_path),
        generated_at_ms=int(time.time() * 1000),
        catalog_hash=catalog_hash,
        counts=counts,
        items=items,
        diagnostics=tuple(diagnostics),
    )


def filter_ecosystem_catalog(catalog: EcosystemCatalog, *, query: str = "", kind: str = "") -> EcosystemCatalog:
    lowered = query.strip().lower()
    selected: list[EcosystemItem] = []
    for item in catalog.items:
        if kind and item.kind != kind:
            continue
        if lowered and lowered not in _item_search_text(item):
            continue
        selected.append(item)
    counts = dict(Counter(item.kind for item in selected))
    payload = [item.to_dict() for item in selected]
    catalog_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return EcosystemCatalog(
        version=catalog.version,
        project=catalog.project,
        generated_at_ms=catalog.generated_at_ms,
        catalog_hash=catalog_hash,
        counts=counts,
        items=tuple(selected),
        diagnostics=catalog.diagnostics,
    )


def write_ecosystem_catalog(project: str | Path, catalog: EcosystemCatalog | None = None) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    catalog = catalog or build_ecosystem_catalog(project_path)
    path = ecosystem_catalog_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def render_ecosystem_catalog(catalog: EcosystemCatalog, *, limit: int = 80) -> str:
    lines = [
        "# Mako Ecosystem",
        "",
        f"- project: {catalog.project}",
        f"- hash: {catalog.catalog_hash}",
        "- counts: " + ", ".join(f"{key}={value}" for key, value in sorted(catalog.counts.items())),
        "",
        "## Items",
        "",
    ]
    for item in catalog.items[: max(0, limit)]:
        license_text = f" license={item.license}" if item.license else ""
        risk = f" risk={item.risk}" if item.risk else ""
        tags = f" tags={','.join(item.tags[:6])}" if item.tags else ""
        lines.append(f"- [{item.kind}] {item.name} status={item.status} source={item.source}{risk}{license_text}{tags}: {item.description}")
    hidden = len(catalog.items) - max(0, limit)
    if hidden > 0:
        lines.append(f"- ... {hidden} more")
    if catalog.diagnostics:
        lines.extend(["", "## Diagnostics", ""])
        for diagnostic in catalog.diagnostics[:40]:
            lines.append(f"- [{diagnostic.level}] {diagnostic.source}: {diagnostic.message}")
    return "\n".join(lines) + "\n"


def _upstream_items() -> list[EcosystemItem]:
    specs = [
        {
            "name": "hermes-skills",
            "license": "MIT",
            "rel_path": "third_party/hermes/skills",
            "description": "Hermes skill workflows",
            "copy_policy": "direct_copy_ok",
            "license_evidence": "MIT frontmatter in vendored SKILL.md files",
            "manifest_path": "third_party/hermes/MANIFEST.sha256",
        },
        {
            "name": "openclaw-selected",
            "license": "MIT",
            "rel_path": "third_party/openclaw/selected",
            "description": "OpenClaw runtime utilities",
            "copy_policy": "direct_copy_ok",
            "license_path": "third_party/openclaw/LICENSE",
            "license_evidence": "MIT license file",
            "manifest_path": "third_party/openclaw/MANIFEST.sha256",
        },
        {
            "name": "mcp-python-sdk",
            "license": "MIT",
            "rel_path": "third_party/mcp_python_sdk",
            "description": "MCP protocol and tool manager sources",
            "copy_policy": "direct_copy_ok",
            "license_path": "third_party/mcp_python_sdk/LICENSE",
        },
        {
            "name": "aider-repomap",
            "license": "Apache-2.0",
            "rel_path": "third_party/aider/aider/repomap.py",
            "description": "Repo map ranking source",
            "copy_policy": "direct_copy_ok_with_apache_notice",
            "license_path": "third_party/aider/LICENSE.txt",
        },
        {
            "name": "swe-agent-env",
            "license": "MIT",
            "rel_path": "third_party/swe_agent/sweagent/environment/swe_env.py",
            "description": "Task environment source",
            "copy_policy": "direct_copy_ok",
            "license_path": "third_party/swe_agent/LICENSE",
        },
        {
            "name": "vnpy-trader",
            "license": "MIT",
            "rel_path": "third_party/vnpy/vnpy/trader",
            "description": "Broker/trader object model sources",
            "copy_policy": "direct_copy_ok",
            "license_path": "third_party/vnpy/LICENSE",
        },
        {
            "name": "hummingbot-order-lifecycle",
            "license": "Apache-2.0",
            "rel_path": "third_party/hummingbot/hummingbot/core/data_type",
            "description": "Order lifecycle sources",
            "copy_policy": "direct_copy_ok_with_apache_notice",
            "license_path": "third_party/hummingbot/LICENSE",
        },
        {
            "name": "pandera-schema",
            "license": "MIT",
            "rel_path": "third_party/pandera/pandera",
            "description": "Schema/check source",
            "copy_policy": "direct_copy_ok",
            "license_path": "third_party/pandera/LICENSE.txt",
        },
        {
            "name": "great-expectations-core",
            "license": "Apache-2.0",
            "rel_path": "third_party/great_expectations/great_expectations/expectations/core",
            "description": "Expectation source",
            "copy_policy": "direct_copy_ok_with_apache_notice",
            "license_path": "third_party/great_expectations/LICENSE",
        },
    ]
    out: list[EcosystemItem] = []
    for spec in specs:
        name = str(spec["name"])
        license_name = str(spec["license"])
        rel_path = str(spec["rel_path"])
        description = str(spec["description"])
        path = ROOT / rel_path
        status = "vendored" if path.exists() else "missing"
        license_path = ROOT / str(spec.get("license_path", ""))
        manifest_path = ROOT / str(spec.get("manifest_path", ""))
        license_verified = _upstream_license_verified(name, path, license_path, license_name)
        manifest_verified = _manifest_verified(manifest_path) if spec.get("manifest_path") else None
        tags = ["copyable", license_name.lower(), "third_party", str(spec["copy_policy"])]
        if license_verified:
            tags.append("license-verified")
        if manifest_verified is True:
            tags.append("manifest-verified")
        out.append(
            EcosystemItem(
                kind="upstream",
                name=name,
                description=description,
                source="third_party",
                status=status,
                license=license_name,
                path=str(path),
                tags=tuple(tags),
                metadata={
                    "file_count": _file_count(path),
                    "relative_path": rel_path,
                    "copy_policy": str(spec["copy_policy"]),
                    "license_evidence": str(spec.get("license_evidence") or spec.get("license_path") or ""),
                    "license_verified": license_verified,
                    "manifest_path": str(manifest_path) if spec.get("manifest_path") else "",
                    "manifest_verified": manifest_verified,
                },
            )
        )
    return out


def _file_count(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return 1
    return sum(1 for item in path.rglob("*") if item.is_file())


def _upstream_license_verified(name: str, path: Path, license_path: Path, license_name: str) -> bool:
    if license_path.exists() and license_path.is_file():
        return _license_text_matches(license_path.read_text(encoding="utf-8", errors="replace"), license_name)
    if name == "hermes-skills" and path.exists():
        skill_files = sorted(path.glob("**/SKILL.md"))
        return bool(skill_files) and all("license: MIT" in item.read_text(encoding="utf-8", errors="replace")[:600] for item in skill_files)
    return False


def _license_text_matches(text: str, license_name: str) -> bool:
    lowered = text.lower()
    normalized = license_name.lower()
    if normalized == "mit":
        return "mit license" in lowered or "permission is hereby granted" in lowered
    if normalized == "apache-2.0":
        return "apache license" in lowered and ("version 2.0" in lowered or "apache.org/licenses/license-2.0" in lowered)
    return normalized in lowered


def _manifest_verified(manifest_path: Path) -> bool:
    if not manifest_path.exists():
        return False
    for raw_line in manifest_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            return False
        expected, rel_path = parts
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            return False
        target = ROOT / rel_path
        if not target.exists() or not target.is_file():
            return False
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            return False
    return True


def _item_search_text(item: EcosystemItem) -> str:
    return " ".join(
        [
            item.kind,
            item.name,
            item.description,
            item.source,
            item.status,
            item.risk,
            item.license,
            item.path,
            " ".join(item.tags),
            json.dumps(item.metadata, ensure_ascii=False, sort_keys=True),
        ]
    ).lower()
