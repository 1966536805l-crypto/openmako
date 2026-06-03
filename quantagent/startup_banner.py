from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .branding import PRODUCT_NAME, PRODUCT_SIGIL, TAGLINE
from .model_client import DEFAULT_REASONING_EFFORT


DEFAULT_MODEL = "gpt-5.5"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class StartupWarning:
    title: str
    detail: str
    suggestions: tuple[str, ...] = ()


def render_startup_banner(project: str | Path, model: str, *, base_url: str | None = None) -> str:
    project_path = Path(project).expanduser().resolve(strict=False)
    lines = [
        f"{PRODUCT_SIGIL}  {PRODUCT_NAME} v{__version__}",
        f"    {model} with {os.environ.get('QUANTAGENT_REASONING_EFFORT', DEFAULT_REASONING_EFFORT)} effort - {TAGLINE}",
        f"    {project_path}",
        "",
        f"Using {model} ({_model_source(model)}) - /model to change",
        f"Provider {_provider_url(base_url)} ({_provider_source(base_url)})",
    ]
    warnings = collect_startup_warnings()
    if warnings:
        lines.append("")
        for warning in warnings:
            lines.append(f"WARNING {warning.title}: {warning.detail}")
            for suggestion in warning.suggestions:
                lines.append(f"  - {suggestion}")
    return "\n".join(lines) + "\n"


def collect_startup_warnings(*, home: str | Path | None = None, env: dict[str, str] | None = None) -> list[StartupWarning]:
    active_env = dict(os.environ if env is None else env)
    warnings: list[StartupWarning] = []

    if active_env.get("QUANTAGENT_OPENAI_API_KEY") and active_env.get("OPENAI_API_KEY"):
        warnings.append(
            StartupWarning(
                "Auth conflict",
                "Both QUANTAGENT_OPENAI_API_KEY and OPENAI_API_KEY are set.",
                (
                    "Trying to use QUANTAGENT_OPENAI_API_KEY? unset OPENAI_API_KEY.",
                    "Trying to use OPENAI_API_KEY? unset QUANTAGENT_OPENAI_API_KEY.",
                ),
            )
        )

    if active_env.get("ANTHROPIC_AUTH_TOKEN") and active_env.get("ANTHROPIC_API_KEY"):
        warnings.append(
            StartupWarning(
                "Anthropic auth conflict",
                "Both ANTHROPIC_AUTH_TOKEN and ANTHROPIC_API_KEY are set.",
                (
                    "Trying to use ANTHROPIC_AUTH_TOKEN? unset ANTHROPIC_API_KEY.",
                    "Trying to use ANTHROPIC_API_KEY? unset ANTHROPIC_AUTH_TOKEN.",
                ),
            )
        )

    warnings.extend(_shell_startup_warnings(home=home, env=active_env))
    return warnings


def _model_source(model: str) -> str:
    if os.environ.get("QUANTAGENT_MODEL") == model:
        return "from QUANTAGENT_MODEL"
    if model != DEFAULT_MODEL:
        return "from CLI/config"
    return "default"


def _provider_url(base_url: str | None) -> str:
    return (
        base_url
        or os.environ.get("QUANTAGENT_OPENAI_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or DEFAULT_BASE_URL
    ).rstrip("/")


def _provider_source(base_url: str | None) -> str:
    if base_url:
        return "from --base-url"
    if os.environ.get("QUANTAGENT_OPENAI_BASE_URL"):
        return "from QUANTAGENT_OPENAI_BASE_URL"
    if os.environ.get("OPENAI_BASE_URL"):
        return "from OPENAI_BASE_URL"
    return "default"


def _shell_startup_warnings(*, home: str | Path | None, env: dict[str, str]) -> list[StartupWarning]:
    home_path = Path(home).expanduser() if home is not None else Path.home()
    zshrc = home_path / ".zshrc"
    if not zshrc.exists():
        return []
    try:
        text = zshrc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    warnings: list[StartupWarning] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        target = _parse_source_target(raw_line)
        if not target:
            continue
        path = _expand_shell_path(target, home_path=home_path, env=env)
        if path and not path.exists():
            warnings.append(
                StartupWarning(
                    "Shell startup file missing",
                    f"{zshrc}:source:{line_number}: no such file or directory: {path}",
                    (
                        "Remove or guard that source line in .zshrc.",
                        f"Recreate the missing file if you still use it: {path}",
                    ),
                )
            )
    return warnings


def _parse_source_target(line: str) -> str:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return ""
    match = re.match(r"^(?:source|\.)\s+([^\s;&|]+)", stripped)
    if not match:
        return ""
    return match.group(1).strip("\"'")


def _expand_shell_path(raw_path: str, *, home_path: Path, env: dict[str, str]) -> Path | None:
    expanded = raw_path.replace("$HOME", str(home_path)).replace("${HOME}", str(home_path))
    if expanded.startswith("~"):
        expanded = str(home_path) + expanded[1:]
    for name, value in env.items():
        expanded = expanded.replace("${" + name + "}", value).replace("$" + name, value)
    if "$" in expanded or "`" in expanded or "$(" in expanded:
        return None
    path = Path(expanded).expanduser()
    return path if path.is_absolute() else home_path / path
