from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .code_index import CodeDiagnostic, editor_diagnostics


@dataclass(frozen=True)
class DiagnosticSnapshot:
    snapshot_id: str
    generated_at_ms: int
    project: str
    diagnostics: tuple[CodeDiagnostic, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["diagnostics"] = [asdict(item) for item in self.diagnostics]
        return payload


def diagnostic_registry_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "diagnostics" / "registry.json"


def refresh_diagnostic_registry(project: str | Path, *, limit: int = 500) -> DiagnosticSnapshot:
    project_path = Path(project).expanduser().resolve(strict=False)
    generated = int(time.time() * 1000)
    snapshot = DiagnosticSnapshot(
        snapshot_id=f"diag-{generated}",
        generated_at_ms=generated,
        project=str(project_path),
        diagnostics=tuple(editor_diagnostics(project_path, limit=limit)),
    )
    path = diagnostic_registry_path(project_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return snapshot


def load_diagnostic_registry(project: str | Path) -> DiagnosticSnapshot:
    path = diagnostic_registry_path(project)
    payload = json.loads(path.read_text(encoding="utf-8"))
    diagnostics = tuple(
        CodeDiagnostic(
            path=str(item.get("path") or ""),
            level=str(item.get("level") or "info"),
            code=str(item.get("code") or ""),
            message=str(item.get("message") or ""),
            line=item.get("line"),
            column=item.get("column"),
            source=str(item.get("source") or "diagnostic_registry"),
        )
        for item in payload.get("diagnostics", [])
        if isinstance(item, dict)
    )
    return DiagnosticSnapshot(
        snapshot_id=str(payload.get("snapshot_id") or ""),
        generated_at_ms=int(payload.get("generated_at_ms") or 0),
        project=str(payload.get("project") or project),
        diagnostics=diagnostics,
    )


def diagnostics_for_paths(snapshot: DiagnosticSnapshot, paths: list[str] | tuple[str, ...]) -> list[CodeDiagnostic]:
    wanted = {path.strip() for path in paths if path.strip()}
    if not wanted:
        return list(snapshot.diagnostics)
    return [item for item in snapshot.diagnostics if item.path in wanted or any(item.path.startswith(prefix.rstrip("/") + "/") for prefix in wanted)]


def render_diagnostic_registry(snapshot: DiagnosticSnapshot, *, paths: list[str] | tuple[str, ...] = ()) -> str:
    diagnostics = diagnostics_for_paths(snapshot, paths)
    lines = [
        "# Diagnostic Registry",
        "",
        f"- snapshot_id: {snapshot.snapshot_id}",
        f"- project: {snapshot.project}",
        f"- diagnostics: {len(diagnostics)}",
        "",
    ]
    if not diagnostics:
        lines.append("No diagnostics.")
        return "\n".join(lines) + "\n"
    for item in diagnostics:
        location = item.path
        if item.line is not None:
            location += f":{item.line}"
            if item.column is not None:
                location += f":{item.column}"
        lines.append(f"- [{item.level}] {item.code} {location}: {item.message}")
    return "\n".join(lines) + "\n"
