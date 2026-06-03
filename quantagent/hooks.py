from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .context_pack import build_context_pack
from .journal import append_journal
from .state import write_project_state


@dataclass
class HookEvent:
    changed: bool
    latest_file: Path | None
    action: str


def hook_state_file(project: Path) -> Path:
    out_dir = project / "AI_协作交接"
    if not out_dir.exists():
        out_dir = project
    return out_dir / ".quantagent_hook_state.json"


def latest_comm_file(project: Path) -> Path | None:
    comm = project / "AI_协作交接"
    if not comm.exists():
        return None
    ignored_prefixes = ("QUANTAGENT_", "PROJECT_STATE_COMPACT")
    files = [
        p
        for p in comm.glob("*.md")
        if p.is_file() and not p.name.startswith(ignored_prefixes)
    ]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)


def run_hooks_once(project: Path, force: bool = False) -> HookEvent:
    latest = latest_comm_file(project)
    state_path = hook_state_file(project)
    previous = {}
    if state_path.exists():
        previous = json.loads(state_path.read_text(encoding="utf-8"))

    marker = None
    if latest:
        marker = {"path": str(latest), "mtime": latest.stat().st_mtime}
    changed = force or marker != previous.get("latest")

    if changed:
        md_path, _ = write_project_state(project)
        pack = build_context_pack(project)
        context_path = (project / "AI_协作交接" / "QUANTAGENT_CONTEXT_PACK.md")
        if context_path.parent.exists():
            context_path.write_text(pack.text, encoding="utf-8")
        latest_name = latest.name if latest else "none"
        append_journal(project, "hook", f"Detected communication update: {latest_name}\nUpdated: {md_path}")
        state_path.write_text(json.dumps({"latest": marker}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return HookEvent(True, latest, "updated_state_context_journal")

    return HookEvent(False, latest, "no_change")
