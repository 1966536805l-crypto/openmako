from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

from .branding import PRODUCT_NAME


TRUST_STORE_ENV = "QUANTAGENT_TRUST_STORE"
ASSUME_TRUST_ENV = "QUANTAGENT_TRUST_WORKSPACE"
SKIP_PROMPT_ENV = "QUANTAGENT_NO_TRUST_PROMPT"


def workspace_key(project: str | Path) -> str:
    return str(Path(project).expanduser().resolve(strict=False))


def trust_store_path() -> Path:
    override = os.environ.get(TRUST_STORE_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".quantagent" / "trusted_workspaces.json"


def load_trusted_workspaces() -> dict[str, dict[str, str]]:
    path = trust_store_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    workspaces = data.get("workspaces") if isinstance(data, dict) else None
    return workspaces if isinstance(workspaces, dict) else {}


def save_trusted_workspaces(workspaces: dict[str, dict[str, str]]) -> Path:
    path = trust_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"workspaces": workspaces}, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def is_workspace_trusted(project: str | Path) -> bool:
    return workspace_key(project) in load_trusted_workspaces()


def trust_workspace(project: str | Path) -> Path:
    key = workspace_key(project)
    workspaces = load_trusted_workspaces()
    workspaces[key] = {"trusted_at": datetime.now().isoformat(timespec="seconds")}
    return save_trusted_workspaces(workspaces)


def render_workspace_trust_prompt(project: str | Path) -> str:
    key = workspace_key(project)
    return f""" ╭████╮   {PRODUCT_NAME}
 │⬤██⬤│
 ╰████╯

Accessing workspace:

 {key}

Quick safety check: Is this a project you created or one you trust? (Like your own code, a well-known open source
project, or work from your team). If not, take a moment to review what's in this folder first.

{PRODUCT_NAME} will be able to read, edit, and execute files here.

Security guide

❯ 1. Yes, I trust this folder
  2. No, exit

Enter to confirm · type 2 to exit
"""


def ensure_workspace_trusted(
    project: str | Path,
    *,
    assume_yes: bool = False,
    disabled: bool = False,
    interactive: bool | None = None,
    input_func: Callable[[str], str] = input,
    output: TextIO | None = None,
) -> bool:
    if disabled or _truthy_env(SKIP_PROMPT_ENV):
        return True
    if assume_yes or _truthy_env(ASSUME_TRUST_ENV):
        trust_workspace(project)
        return True
    if is_workspace_trusted(project):
        return True
    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stderr.isatty()
    if not interactive:
        return False

    stream = output or sys.stderr
    print(render_workspace_trust_prompt(project), file=stream, end="")
    try:
        answer = input_func("> ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("", file=stream)
        return False
    if answer in {"", "1", "y", "yes"}:
        trust_workspace(project)
        return True
    return False


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}
