from __future__ import annotations

import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .worktree_isolation import detect_sandbox_backend


@dataclass(frozen=True)
class SubagentBackend:
    name: str
    available: bool
    isolation: str
    transport: str
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_subagent_backends(project: str | Path) -> list[SubagentBackend]:
    project_path = Path(project).expanduser().resolve(strict=False)
    sandbox = detect_sandbox_backend("auto")
    return [
        SubagentBackend("in_process", True, "shared_process", "python", "local background task runtime"),
        SubagentBackend("worktree", True, sandbox.backend, "python", f"isolated copy rooted near {project_path}"),
        SubagentBackend("tmux", bool(shutil.which("tmux")), "terminal_session", "tmux", "tmux executable detected" if shutil.which("tmux") else "tmux not found"),
        SubagentBackend("iterm", _has_iterm(), "terminal_session", "iterm", "iTerm app detected" if _has_iterm() else "iTerm app not detected"),
        SubagentBackend("remote", False, "remote_workspace", "websocket", "remote runner specs exist, but live remote agent execution is not enabled"),
    ]


def choose_subagent_backend(project: str | Path, preferred: str = "auto") -> SubagentBackend:
    backends = detect_subagent_backends(project)
    if preferred != "auto":
        for backend in backends:
            if backend.name == preferred:
                return backend
        raise KeyError(f"unknown subagent backend: {preferred}")
    for name in ("worktree", "tmux", "in_process"):
        backend = next(item for item in backends if item.name == name)
        if backend.available:
            return backend
    return backends[0]


def render_subagent_backends(backends: list[SubagentBackend]) -> str:
    lines = ["# Subagent Backends", ""]
    for backend in backends:
        mark = "ok" if backend.available else "gap"
        lines.append(f"- [{mark}] {backend.name}: isolation={backend.isolation} transport={backend.transport}; {backend.reason}")
    return "\n".join(lines) + "\n"


def _has_iterm() -> bool:
    return Path("/Applications/iTerm.app").exists() or Path("/Applications/iTerm2.app").exists()
