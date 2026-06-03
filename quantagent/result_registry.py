from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class RegistryEntry:
    id: str
    created_at: str
    kind: str
    name: str
    json_path: str
    markdown_path: str
    summary: str
    tags: list[str]


def registry_dir(project: Path) -> Path:
    out_dir = project / "AI_协作交接" / "quantagent_results"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def registry_path(project: Path) -> Path:
    return registry_dir(project) / "registry.json"


def load_registry(project: Path) -> list[RegistryEntry]:
    path = registry_path(project)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [RegistryEntry(**item) for item in data.get("entries", [])]


def save_registry(project: Path, entries: list[RegistryEntry]) -> Path:
    path = registry_path(project)
    payload = {"entries": [asdict(entry) for entry in entries]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def register_result(
    project: Path,
    *,
    kind: str,
    name: str,
    payload: dict[str, Any],
    markdown: str,
    summary: str,
    tags: list[str] | None = None,
) -> RegistryEntry:
    created_at = datetime.now().isoformat(timespec="seconds")
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name)[:80]
    result_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_name}"
    out_dir = registry_dir(project)
    json_path = out_dir / f"{result_id}.json"
    markdown_path = out_dir / f"{result_id}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(markdown, encoding="utf-8")

    entry = RegistryEntry(
        id=result_id,
        created_at=created_at,
        kind=kind,
        name=name,
        json_path=str(json_path),
        markdown_path=str(markdown_path),
        summary=summary,
        tags=tags or [],
    )
    entries = load_registry(project)
    entries.append(entry)
    save_registry(project, entries)
    return entry


def render_registry_markdown(entries: list[RegistryEntry], limit: int = 20) -> str:
    lines = ["# Mako Result Registry", ""]
    for entry in entries[-limit:][::-1]:
        tags = ",".join(entry.tags)
        lines.append(f"- {entry.created_at} `{entry.kind}` `{entry.id}` {entry.summary} [{tags}]")
    return "\n".join(lines) + "\n"

