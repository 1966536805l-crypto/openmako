from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Toolset:
    name: str
    description: str
    tools: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()


TOOLSETS: dict[str, Toolset] = {
    "core": Toolset(
        "core",
        "Default local Mako tools for safe project inspection.",
        ("status", "context", "audit", "validate", "registry", "safety_claim", "agent-v2"),
    ),
    "file": Toolset(
        "file",
        "Project-contained file read/search/write/edit tools.",
        ("file_read", "file_search", "files.read", "files.search", "files.diff-replace", "files.replace", "patch-engine", "edit-loop"),
    ),
    "memory": Toolset(
        "memory",
        "Persistent local memory and session recall.",
        ("memory.add", "memory.search", "memory.extract", "session.list", "session.compact"),
    ),
    "desktop": Toolset(
        "desktop",
        "Local desktop screen and input tools.",
        (
            "desktop.front",
            "desktop.window",
            "desktop.live",
            "desktop.open",
            "desktop.shot",
            "desktop.grid",
            "desktop.ax",
            "desktop.ocr",
            "desktop.som",
            "desktop.tokenize",
            "desktop.decide",
            "desktop.daemon",
            "desktop.eval",
            "desktop.find",
            "desktop.plan-click",
            "desktop.find-click",
            "desktop.web-search",
            "desktop.run",
            "desktop.som-click",
            "desktop.grid-click",
            "desktop.hotkey",
            "desktop.click",
            "desktop.type",
        ),
    ),
    "quant": Toolset(
        "quant",
        "Quant research validation, evidence, and anti-hallucination tools.",
        ("audit", "validate", "registry", "experiment", "consensus", "quant_auditor"),
    ),
    "coding": Toolset(
        "coding",
        "Coding-agent workflow tools.",
        includes=("core", "file", "memory"),
    ),
    "operator": Toolset(
        "operator",
        "Human-operated local assistant tools. Desktop actions remain explicit.",
        includes=("core", "file", "memory", "desktop"),
    ),
    "research": Toolset(
        "research",
        "Quant research loop with memory and evidence tracking.",
        includes=("core", "quant", "memory"),
    ),
}


def list_toolsets() -> list[Toolset]:
    return [TOOLSETS[name] for name in sorted(TOOLSETS)]


def resolve_toolset(name: str, seen: set[str] | None = None) -> tuple[str, ...]:
    seen = seen or set()
    if name not in TOOLSETS:
        raise KeyError(f"unknown toolset: {name}")
    if name in seen:
        raise ValueError(f"cyclic toolset include: {name}")
    seen.add(name)
    toolset = TOOLSETS[name]
    tools: list[str] = list(toolset.tools)
    for include in toolset.includes:
        tools.extend(resolve_toolset(include, seen=set(seen)))
    return tuple(dict.fromkeys(tools))


def render_toolsets(name: str | None = None) -> str:
    if name:
        tools = resolve_toolset(name)
        toolset = TOOLSETS[name]
        return "\n".join(
            [
                f"# Toolset {toolset.name}",
                "",
                toolset.description,
                "",
                "## Tools",
                "",
                *[f"- {tool}" for tool in tools],
            ]
        ) + "\n"
    lines = ["# Mako Toolsets", ""]
    for toolset in list_toolsets():
        includes = f" includes={','.join(toolset.includes)}" if toolset.includes else ""
        lines.append(f"- {toolset.name}: {toolset.description}{includes}")
    return "\n".join(lines) + "\n"
