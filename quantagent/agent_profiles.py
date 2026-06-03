from __future__ import annotations

import ast
import json
import os
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .sandbox_policy import ALLOW, ASK, DENY, matches_tool_pattern, resolve_permission_dsl


CONFIG_NAMES = ("config.json", "quantagent.json")
INSTRUCTION_FILES = (
    "QUANTAGENT.md",
    "AGENTS.md",
    "AI_协作交接/PROJECT_MEMORY.md",
)
CLAUDE_AGENT_IMPORT_ENV = "QUANTAGENT_LOAD_CLAUDE_AGENTS"


@dataclass(frozen=True)
class AgentProfile:
    name: str
    mode: str = "primary"
    description: str = ""
    model: str = ""
    prompt: str = ""
    permission: dict[str, Any] = field(default_factory=dict)
    steps: int = 0
    hidden: bool = False
    source: str = "builtin"
    tools: list[str] = field(default_factory=list)
    disallowed_tools: list[str] = field(default_factory=list)
    permission_mode: str = ""
    skills: list[str] = field(default_factory=list)
    mcp_servers: Any = field(default_factory=dict)
    hooks: Any = field(default_factory=dict)
    memory: Any = ""
    effort: str = ""
    background: bool = False
    isolation: str = ""
    color: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentProfileConfig:
    default_agent: str
    agents: dict[str, AgentProfile]
    sources: list[str] = field(default_factory=list)
    managed_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "default_agent": self.default_agent,
            "agents": {name: agent.to_dict() for name, agent in self.agents.items()},
            "sources": self.sources,
            "managed_sources": self.managed_sources,
        }


@dataclass(frozen=True)
class AgentPermissionDecision:
    profile: str
    mode: str
    tool: str
    action: str
    pattern: str
    source: str
    reason: str

    @property
    def matched(self) -> bool:
        return bool(self.profile)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"runtime": "agent_profile"}


@dataclass(frozen=True)
class InstructionSource:
    path: str
    priority: int
    text: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"chars": len(self.text)}


def builtin_agent_config() -> dict[str, Any]:
    return {
        "default_agent": "build",
        "agents": {
            "plan": {
                "mode": "primary",
                "source": "builtin",
                "description": "Read-mostly planning agent. It can inspect context and code but cannot edit files.",
                "permission": OrderedDict(
                    [
                        ("*", ASK),
                        ("status", ALLOW),
                        ("context", ALLOW),
                        ("audit", ALLOW),
                        ("validate", ALLOW),
                        ("registry", ALLOW),
                        ("file_read", ALLOW),
                        ("file_search", ALLOW),
                        ("memory.search", ALLOW),
                        ("index*", ALLOW),
                        ("checkpoint.list", ALLOW),
                        ("checkpoint.show", ALLOW),
                        ("transcript*", ALLOW),
                        ("edit", DENY),
                        ("file_write", DENY),
                        ("file_edit", DENY),
                        ("apply_patch", DENY),
                        ("experiment", DENY),
                        ("run_p4", DENY),
                    ]
                ),
            },
            "build": {
                "mode": "primary",
                "source": "builtin",
                "description": "Default coding agent. Reads are allowed; writes, shell, and MCP tools require approval.",
                "permission": OrderedDict(
                    [
                        ("*", ASK),
                        ("status", ALLOW),
                        ("context", ALLOW),
                        ("audit", ALLOW),
                        ("validate", ALLOW),
                        ("registry", ALLOW),
                        ("file_read", ALLOW),
                        ("file_search", ALLOW),
                        ("memory.search", ALLOW),
                        ("py_compile", ALLOW),
                        ("test", ALLOW),
                        ("edit", ASK),
                        ("file_write", ASK),
                        ("file_edit", ASK),
                        ("shell", ASK),
                        ("command", ASK),
                        ("mcp:*", ASK),
                    ]
                ),
            },
            "audit": {
                "mode": "subagent",
                "source": "builtin",
                "description": "Read-only code and evidence auditor. It can inspect and report but cannot mutate state.",
                "permission": OrderedDict(
                    [
                        ("*", DENY),
                        ("status", ALLOW),
                        ("context", ALLOW),
                        ("audit", ALLOW),
                        ("validate", ALLOW),
                        ("registry", ALLOW),
                        ("file_read", ALLOW),
                        ("file_search", ALLOW),
                        ("memory.search", ALLOW),
                        ("transcript*", ALLOW),
                        ("checkpoint.show", ALLOW),
                    ]
                ),
            },
            "quant-auditor": {
                "mode": "subagent",
                "source": "builtin",
                "description": "Quant evidence auditor. It can read evidence and run audits, but cannot edit, trade, or launch experiments.",
                "permission": OrderedDict(
                    [
                        ("*", DENY),
                        ("evidence_read", ALLOW),
                        ("status", ALLOW),
                        ("context", ALLOW),
                        ("audit", ALLOW),
                        ("validate", ALLOW),
                        ("registry", ALLOW),
                        ("file_read", ALLOW),
                        ("file_search", ALLOW),
                        ("experiment", DENY),
                        ("run_p4", DENY),
                        ("edit", DENY),
                        ("shell", DENY),
                    ]
                ),
            },
        },
    }


def load_agent_profile_config(
    project: str | Path | None = None,
    *,
    cli_override: dict[str, Any] | None = None,
) -> AgentProfileConfig:
    project_path = Path(project).expanduser().resolve(strict=False) if project is not None else Path.cwd()
    merged: dict[str, Any] = builtin_agent_config()
    sources = ["builtin"]
    managed_sources: list[str] = []
    for path in _global_agent_markdown_paths():
        agent_config = _read_agent_markdown_config(path)
        if agent_config:
            merged = _deep_merge(merged, agent_config)
            sources.append(str(path))
    for path in _global_config_paths():
        if path.exists():
            merged = _deep_merge(merged, _read_config(path))
            sources.append(str(path))
    for path in _project_agent_markdown_paths(project_path):
        agent_config = _read_agent_markdown_config(path)
        if agent_config:
            merged = _deep_merge(merged, agent_config)
            sources.append(str(path))
    for path in _project_config_paths(project_path):
        if path.exists():
            merged = _deep_merge(merged, _read_config(path))
            sources.append(str(path))
    env_json = os.environ.get("QUANTAGENT_CONFIG_JSON")
    if env_json:
        merged = _deep_merge(merged, _loads_config(env_json, "QUANTAGENT_CONFIG_JSON"))
        sources.append("env:QUANTAGENT_CONFIG_JSON")
    if os.environ.get("QUANTAGENT_AGENT"):
        merged = _deep_merge(merged, {"default_agent": os.environ["QUANTAGENT_AGENT"]})
        sources.append("env:QUANTAGENT_AGENT")
    if cli_override:
        merged = _deep_merge(merged, cli_override)
        sources.append("cli")
    for path in _managed_config_paths(project_path):
        if path.exists():
            merged = _deep_merge(merged, _read_config(path))
            managed_sources.append(str(path))
    agents = _load_agents(merged.get("agents") or merged.get("agent") or {})
    default_agent = str(merged.get("default_agent") or merged.get("defaultAgent") or "build")
    if (default_agent not in agents or agents[default_agent].mode != "primary") and agents:
        default_agent = "build" if "build" in agents else sorted(agents)[0]
    return AgentProfileConfig(default_agent=default_agent, agents=agents, sources=sources, managed_sources=managed_sources)


def resolve_agent_permission(
    project: str | Path | None,
    profile_name: str,
    tool: str,
    *,
    args: dict[str, Any] | None = None,
) -> AgentPermissionDecision | None:
    config = load_agent_profile_config(project)
    profile = config.agents.get(profile_name)
    if profile is None:
        return None
    decision = resolve_permission_dsl(
        profile.permission,
        tool,
        {
            **(args or {}),
            **({"project": str(Path(project).expanduser().resolve(strict=False))} if project is not None else {}),
        },
    )
    return AgentPermissionDecision(
        profile=profile.name,
        mode=profile.mode,
        tool=tool.strip(),
        action=decision.action,
        pattern=decision.pattern,
        source=profile.source,
        reason=f"{tool.strip()} {decision.action} by agent profile {profile.name} pattern {decision.pattern}; {decision.reason}",
    )


def load_instructions(project: str | Path, *, max_chars: int = 80_000) -> list[InstructionSource]:
    project_path = Path(project).expanduser().resolve(strict=False)
    results: list[InstructionSource] = []
    for priority, path in enumerate(_instruction_paths(project_path), start=1):
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if len(text) > max_chars:
            text = text[:max_chars] + "\n[instruction trimmed]"
        results.append(InstructionSource(path=str(path), priority=priority, text=text, source=_source_label(path, project_path)))
    return results


def render_agent_profiles(config: AgentProfileConfig) -> str:
    lines = ["# Mako Agent Profiles", "", f"- default_agent: {config.default_agent}"]
    if config.sources:
        lines.append(f"- sources: {', '.join(config.sources)}")
    if config.managed_sources:
        lines.append(f"- managed_sources: {', '.join(config.managed_sources)}")
    lines.append("")
    for profile in sorted(config.agents.values(), key=lambda item: (item.mode, item.name)):
        hidden = " hidden" if profile.hidden else ""
        lines.append(f"- {profile.name} [{profile.mode}{hidden}]: {profile.description}")
    return "\n".join(lines) + "\n"


def render_agent_profile(profile: AgentProfile) -> str:
    lines = [
        f"# Agent Profile {profile.name}",
        "",
        f"- mode: {profile.mode}",
        f"- source: {profile.source}",
        f"- model: {profile.model or '-'}",
        f"- steps: {profile.steps or '-'}",
        f"- hidden: {profile.hidden}",
        f"- description: {profile.description or '-'}",
    ]
    lines.extend(_render_agent_profile_extras(profile))
    lines.extend(["", "## Permissions"])
    for pattern, action in profile.permission.items():
        lines.append(f"- {pattern}: {_normalize_action(action)}")
    if profile.prompt:
        lines.extend(["", "## Prompt", profile.prompt])
    return "\n".join(lines) + "\n"


def render_instructions(instructions: list[InstructionSource]) -> str:
    if not instructions:
        return "No Mako instructions found.\n"
    lines = ["# Mako Instructions", ""]
    for item in instructions:
        lines.append(f"- priority={item.priority} source={item.source} path={item.path} chars={len(item.text)}")
    return "\n".join(lines) + "\n"


def _load_agents(raw: Any) -> dict[str, AgentProfile]:
    if not isinstance(raw, dict):
        return {}
    agents: dict[str, AgentProfile] = {}
    for name, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        profile_name = str(name)
        agents[str(name)] = AgentProfile(
            name=profile_name,
            mode=str(payload.get("mode") or "primary"),
            description=str(payload.get("description") or ""),
            model=str(payload.get("model") or ""),
            prompt=str(payload.get("prompt") or ""),
            permission=_profile_permission(payload),
            steps=_to_int(_first_present(payload, ("steps", "max_steps", "maxSteps", "maxTurns"), 0)),
            hidden=_to_bool(payload.get("hidden", False)),
            source=str(payload.get("source") or "config"),
            tools=_string_list(payload.get("tools")),
            disallowed_tools=_string_list(_first_present(payload, ("disallowedTools", "disallowed_tools"), [])),
            permission_mode=str(_first_present(payload, ("permissionMode", "permission_mode"), "") or ""),
            skills=_string_list(payload.get("skills")),
            mcp_servers=_first_present(payload, ("mcpServers", "mcp_servers"), {}),
            hooks=payload.get("hooks", {}),
            memory=payload.get("memory", ""),
            effort=str(payload.get("effort") or ""),
            background=_to_bool(payload.get("background", False)),
            isolation=str(payload.get("isolation") or ""),
            color=str(payload.get("color") or ""),
            extra=_extra_profile_fields(payload),
        )
    return agents


def _profile_permission(payload: dict[str, Any]) -> dict[str, Any]:
    permission = payload.get("permission", payload.get("permissions"))
    permission_mode = str(_first_present(payload, ("permissionMode", "permission_mode"), "") or "")
    tools = _string_list(payload.get("tools"))
    disallowed = _string_list(_first_present(payload, ("disallowedTools", "disallowed_tools"), []))
    if isinstance(permission, dict):
        normalized = _normalize_permission(permission)
    else:
        default_action = _permission_mode_default(permission_mode) or ASK
        normalized = OrderedDict()
        if tools and not _tools_include_all(tools):
            normalized["*"] = DENY
        else:
            normalized["*"] = default_action
    for tool in tools:
        if _is_all_tool(tool):
            continue
        for pattern in _tool_permission_patterns(tool):
            normalized[pattern] = ALLOW
    for tool in disallowed:
        for pattern in _tool_permission_patterns(tool):
            normalized[pattern] = DENY
    return normalized or {"*": ASK}


def _normalize_permission(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"*": ASK}
    normalized: dict[str, Any] = OrderedDict()
    for pattern, action in raw.items():
        if isinstance(action, bool):
            normalized[str(pattern)] = ALLOW if action else DENY
        elif isinstance(action, str):
            normalized[str(pattern)] = _normalize_action(action)
        elif isinstance(action, dict):
            normalized[str(pattern)] = _normalize_permission(action)
        else:
            normalized[str(pattern)] = ASK
    return normalized or {"*": ASK}


def _normalize_action(raw: Any) -> str:
    text = str(raw).strip().lower()
    return text if text in {ALLOW, ASK, DENY} else ASK


def _permission_mode_default(raw: str) -> str:
    text = raw.strip().lower().replace("-", "_")
    if text in {"allow", "allow_all", "allowed", "bypass", "bypass_permissions", "trusted"}:
        return ALLOW
    if text in {"deny", "deny_all", "read_only", "readonly", "locked"}:
        return DENY
    if text in {"ask", "ask_all", "default", "prompt"}:
        return ASK
    return ""


def _tools_include_all(tools: list[str]) -> bool:
    return any(_is_all_tool(tool) for tool in tools)


def _is_all_tool(tool: str) -> bool:
    return tool.strip().lower() in {"*", "all", "all_tools"}


def _tool_permission_patterns(tool: str) -> list[str]:
    selected = tool.strip()
    if not selected:
        return []
    aliases = {
        "bash": "shell",
        "shell": "shell",
        "read": "file_read",
        "grep": "file_search",
        "glob": "file_search",
        "ls": "file_search",
        "edit": "edit",
        "multiedit": "edit",
        "write": "file_write",
        "notebookedit": "edit",
    }
    patterns = [selected]
    lowered = selected.lower()
    if lowered.startswith("mcp__"):
        patterns.append("mcp:" + selected[5:].replace("__", ":"))
    if lowered in aliases:
        patterns.append(aliases[lowered])
    unique: list[str] = []
    for pattern in patterns:
        if pattern and pattern not in unique:
            unique.append(pattern)
    return unique


def _pattern_score(tool: str, pattern: Any) -> int:
    selected = str(pattern)
    if not selected:
        return -1
    tool_names = {tool.strip(), tool.strip().replace(":", "_"), _tool_group(tool)}
    if selected == "evidence_read":
        return 100 if _tool_group(tool) == "evidence_read" else -1
    if any(name == selected for name in tool_names if name):
        return 100
    if selected == "*":
        return 1
    if any(char in selected for char in "*?[]"):
        return 50 if any(matches_tool_pattern(name, selected) for name in tool_names if name) else -1
    return 80 if any(matches_tool_pattern(name, selected) for name in tool_names if name) else -1


def _tool_group(tool: str) -> str:
    normalized = tool.strip()
    if normalized in {"file_write", "file_edit", "apply_patch"} or normalized.startswith("edit"):
        return "edit"
    if normalized in {"shell", "command", "bash"}:
        return "shell"
    if normalized in {"file_read", "file_search", "context", "status", "registry", "audit"}:
        return "evidence_read"
    if normalized.startswith("mcp:"):
        return "mcp"
    return normalized


def _project_config_paths(project: Path) -> list[Path]:
    return [project / ".quantagent" / name for name in CONFIG_NAMES]


def _global_config_paths() -> list[Path]:
    root = Path(os.environ.get("QUANTAGENT_HOME", "~/.quantagent")).expanduser()
    return [root / name for name in CONFIG_NAMES]


def _managed_config_paths(project: Path) -> list[Path]:
    paths: list[Path] = []
    if os.environ.get("QUANTAGENT_MANAGED_CONFIG"):
        paths.append(Path(os.environ["QUANTAGENT_MANAGED_CONFIG"]).expanduser())
    paths.append(project / ".quantagent" / "managed_config.json")
    return paths


def _global_agent_markdown_paths() -> list[Path]:
    quantagent_root = Path(os.environ.get("QUANTAGENT_HOME", "~/.quantagent")).expanduser()
    paths: list[Path] = []
    if _truthy_env(CLAUDE_AGENT_IMPORT_ENV):
        claude_root = Path(os.environ.get("CLAUDE_HOME", "~/.claude")).expanduser()
        paths.extend(_agent_markdown_files(claude_root / "agents"))
    paths.extend(_agent_markdown_files(quantagent_root / "agents"))
    return paths


def _project_agent_markdown_paths(project: Path) -> list[Path]:
    paths: list[Path] = []
    if _truthy_env(CLAUDE_AGENT_IMPORT_ENV):
        paths.extend(_agent_markdown_files(project / ".claude" / "agents"))
    paths.extend(_agent_markdown_files(project / ".quantagent" / "agents"))
    return paths


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _agent_markdown_files(directory: Path) -> list[Path]:
    if not directory.exists() or not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.md") if path.is_file())


def _instruction_paths(project: Path) -> list[Path]:
    paths: list[Path] = []
    global_root = Path(os.environ.get("QUANTAGENT_HOME", "~/.quantagent")).expanduser()
    paths.extend([global_root / "AGENTS.md", *sorted((global_root / "instructions").glob("*.md"))] if (global_root / "instructions").exists() else [global_root / "AGENTS.md"])
    paths.extend(project / item for item in INSTRUCTION_FILES)
    instruction_dir = project / ".quantagent" / "instructions"
    if instruction_dir.exists():
        paths.extend(sorted(instruction_dir.glob("*.md")))
    return paths


def _source_label(path: Path, project: Path) -> str:
    try:
        path.relative_to(project)
        return "project"
    except ValueError:
        return "global"


def _read_config(path: Path) -> dict[str, Any]:
    return _loads_config(path.read_text(encoding="utf-8"), str(path))


def _read_agent_markdown_config(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)
    payload = _parse_frontmatter(frontmatter) if frontmatter is not None else {}
    if not isinstance(payload, dict):
        payload = {}
    name = str(payload.get("name") or path.stem).strip()
    if not name:
        return {}
    if body.strip():
        payload["prompt"] = body.strip("\r\n")
    payload.setdefault("mode", "subagent")
    payload["source"] = str(path)
    return {"agents": {name: payload}}


def _split_frontmatter(text: str) -> tuple[str | None, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None, text
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() in {"---", "..."}:
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    return None, text


def _parse_frontmatter(text: str) -> dict[str, Any]:
    lines = text.splitlines()
    parsed, _index = _parse_yamlish_node(lines, 0, 0)
    return parsed if isinstance(parsed, dict) else {}


def _parse_yamlish_node(lines: list[str], index: int, indent: int) -> tuple[Any, int]:
    index = _skip_yamlish_blank(lines, index)
    if index >= len(lines):
        return OrderedDict(), index
    current = lines[index]
    current_indent = _line_indent(current)
    if current_indent < indent:
        return OrderedDict(), index
    if current[current_indent:].startswith("- "):
        return _parse_yamlish_list(lines, index, current_indent)
    return _parse_yamlish_map(lines, index, current_indent)


def _parse_yamlish_map(lines: list[str], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = OrderedDict()
    while index < len(lines):
        index = _skip_yamlish_blank(lines, index)
        if index >= len(lines):
            break
        line = lines[index]
        current_indent = _line_indent(line)
        if current_indent < indent:
            break
        if current_indent > indent:
            index += 1
            continue
        content = line[current_indent:]
        if content.startswith("- "):
            break
        key, separator, raw_value = content.partition(":")
        if not separator:
            index += 1
            continue
        key = key.strip()
        value_text = raw_value.strip()
        index += 1
        if value_text in {"|", ">"}:
            result[key], index = _parse_block_scalar(lines, index, current_indent, folded=value_text == ">")
        elif value_text:
            result[key] = _parse_scalar(value_text)
        else:
            child_indent = _next_yamlish_indent(lines, index, current_indent)
            if child_indent is None:
                result[key] = OrderedDict()
            else:
                result[key], index = _parse_yamlish_node(lines, index, child_indent)
    return result, index


def _parse_yamlish_list(lines: list[str], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        index = _skip_yamlish_blank(lines, index)
        if index >= len(lines):
            break
        line = lines[index]
        current_indent = _line_indent(line)
        if current_indent < indent:
            break
        content = line[current_indent:]
        if current_indent != indent or not content.startswith("- "):
            break
        item_text = content[2:].strip()
        index += 1
        if not item_text:
            child_indent = _next_yamlish_indent(lines, index, current_indent)
            if child_indent is None:
                result.append("")
            else:
                child, index = _parse_yamlish_node(lines, index, child_indent)
                result.append(child)
            continue
        key, separator, raw_value = item_text.partition(":")
        if separator and key.strip() and not item_text.startswith(("'", '"')) and (not raw_value or raw_value[:1].isspace()):
            item: dict[str, Any] = OrderedDict()
            value_text = raw_value.strip()
            if value_text:
                item[key.strip()] = _parse_scalar(value_text)
            else:
                child_indent = _next_yamlish_indent(lines, index, current_indent)
                if child_indent is not None:
                    item[key.strip()], index = _parse_yamlish_node(lines, index, child_indent)
                else:
                    item[key.strip()] = OrderedDict()
            child_indent = _next_yamlish_indent(lines, index, current_indent)
            if child_indent is not None:
                child, index = _parse_yamlish_node(lines, index, child_indent)
                if isinstance(child, dict):
                    item.update(child)
            result.append(item)
        else:
            result.append(_parse_scalar(item_text))
    return result, index


def _parse_block_scalar(lines: list[str], index: int, parent_indent: int, *, folded: bool) -> tuple[str, int]:
    block: list[str] = []
    child_indent = _next_yamlish_indent(lines, index, parent_indent)
    if child_indent is None:
        return "", index
    while index < len(lines):
        line = lines[index]
        if line.strip() and _line_indent(line) <= parent_indent:
            break
        block.append(line[child_indent:] if len(line) >= child_indent else "")
        index += 1
    if folded:
        return " ".join(part.strip() for part in block if part.strip()), index
    return "\n".join(block).rstrip("\n"), index


def _skip_yamlish_blank(lines: list[str], index: int) -> int:
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped and not stripped.startswith("#"):
            break
        index += 1
    return index


def _next_yamlish_indent(lines: list[str], index: int, parent_indent: int) -> int | None:
    probe = _skip_yamlish_blank(lines, index)
    if probe >= len(lines):
        return None
    indent = _line_indent(lines[probe])
    return indent if indent > parent_indent else None


def _line_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_scalar(raw: str) -> Any:
    text = raw.strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None
    if text.startswith(("[", "{")) and text.endswith(("]", "}")):
        parsed = _parse_structured_scalar(text)
        if parsed is not None:
            return parsed
    if text[0] in {"'", '"'}:
        try:
            return ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return text.strip("'\"")
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _parse_structured_scalar(text: str) -> Any:
    for loader in (json.loads, ast.literal_eval):
        try:
            return loader(text)
        except (json.JSONDecodeError, SyntaxError, ValueError):
            pass
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        return [_parse_scalar(part) for part in _split_inline_items(inner)] if inner else []
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        result: dict[str, Any] = OrderedDict()
        for item in _split_inline_items(inner):
            key, separator, value = item.partition(":")
            if separator:
                result[key.strip().strip("'\"")] = _parse_scalar(value)
        return result
    return None


def _split_inline_items(text: str) -> list[str]:
    items: list[str] = []
    start = 0
    depth = 0
    quote = ""
    for index, char in enumerate(text):
        if quote:
            if char == quote and (index == 0 or text[index - 1] != "\\"):
                quote = ""
            continue
        if char in {"'", '"'}:
            quote = char
        elif char in "[{(":
            depth += 1
        elif char in "]})":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            items.append(text[start:index].strip())
            start = index + 1
    items.append(text[start:].strip())
    return [item for item in items if item]


def _first_present(payload: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def _string_list(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        return [part.strip() for part in raw.split(",") if part.strip()]
    if isinstance(raw, (list, tuple, set)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return [str(raw).strip()]


def _to_int(raw: Any) -> int:
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _to_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


def _extra_profile_fields(payload: dict[str, Any]) -> dict[str, Any]:
    known = {
        "name",
        "mode",
        "description",
        "model",
        "prompt",
        "permission",
        "permissions",
        "steps",
        "max_steps",
        "maxSteps",
        "maxTurns",
        "hidden",
        "source",
        "tools",
        "disallowedTools",
        "disallowed_tools",
        "permissionMode",
        "permission_mode",
        "skills",
        "mcpServers",
        "mcp_servers",
        "hooks",
        "memory",
        "effort",
        "background",
        "isolation",
        "color",
        "extra",
    }
    extra = dict(payload.get("extra") or {}) if isinstance(payload.get("extra"), dict) else {}
    for key, value in payload.items():
        if key not in known:
            extra[str(key)] = value
    return extra


def _render_agent_profile_extras(profile: AgentProfile) -> list[str]:
    lines: list[str] = []
    if profile.tools:
        lines.append(f"- tools: {', '.join(profile.tools)}")
    if profile.disallowed_tools:
        lines.append(f"- disallowed_tools: {', '.join(profile.disallowed_tools)}")
    if profile.permission_mode:
        lines.append(f"- permission_mode: {profile.permission_mode}")
    if profile.skills:
        lines.append(f"- skills: {', '.join(profile.skills)}")
    if profile.mcp_servers:
        lines.append(f"- mcp_servers: {_render_extra_value(profile.mcp_servers)}")
    if profile.hooks:
        lines.append(f"- hooks: {_render_extra_value(profile.hooks)}")
    if profile.memory:
        lines.append(f"- memory: {_render_extra_value(profile.memory)}")
    if profile.effort:
        lines.append(f"- effort: {profile.effort}")
    if profile.background:
        lines.append(f"- background: {profile.background}")
    if profile.isolation:
        lines.append(f"- isolation: {profile.isolation}")
    if profile.color:
        lines.append(f"- color: {profile.color}")
    if profile.extra:
        lines.append(f"- extra: {', '.join(sorted(profile.extra))}")
    return lines


def _render_extra_value(raw: Any) -> str:
    if isinstance(raw, dict):
        return ", ".join(str(key) for key in raw) or "-"
    if isinstance(raw, list):
        return ", ".join(str(item) for item in raw) or "-"
    text = str(raw).replace("\n", " ").strip()
    return text[:117] + "..." if len(text) > 120 else text


def _loads_config(text: str, source: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Mako config JSON in {source}: {exc}") from exc
    return payload if isinstance(payload, dict) else {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        target_key = "agents" if key == "agent" else key
        if isinstance(value, dict) and isinstance(result.get(target_key), dict):
            result[target_key] = _deep_merge(result[target_key], value)
        else:
            result[target_key] = value
    return result
