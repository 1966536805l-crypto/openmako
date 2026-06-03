from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import hashlib
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FileSnapshot:
    path: str
    existed: bool
    sha256: str = ""
    text: str = ""


@dataclass(frozen=True)
class CheckpointRecord:
    checkpoint_id: str
    task_id: str = ""
    plan_id: str = ""
    reason: str = ""
    created_at_ms: int = 0
    files: list[FileSnapshot] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"restore_command": f"mako checkpoint restore {self.checkpoint_id}"}


def checkpoint_dir(project: str | Path) -> Path:
    return Path(project).expanduser().resolve(strict=False) / ".quantagent" / "checkpoints"


def checkpoint_path(project: str | Path, checkpoint_id: str) -> Path:
    return checkpoint_dir(project) / f"{checkpoint_id}.json"


def create_checkpoint(
    project: str | Path,
    paths: list[str | Path],
    *,
    task_id: str = "",
    plan_id: str = "",
    reason: str = "",
) -> CheckpointRecord:
    project_path = Path(project).expanduser().resolve(strict=False)
    snapshots = [_snapshot_file(project_path, path) for path in paths]
    record = CheckpointRecord(
        checkpoint_id="chk-" + uuid.uuid4().hex[:12],
        task_id=task_id,
        plan_id=plan_id,
        reason=reason,
        created_at_ms=int(time.time() * 1000),
        files=snapshots,
    )
    path = checkpoint_path(project_path, record.checkpoint_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def load_checkpoint(project: str | Path, checkpoint_id: str) -> CheckpointRecord:
    payload = json.loads(checkpoint_path(project, checkpoint_id).read_text(encoding="utf-8"))
    files = [FileSnapshot(path=str(item.get("path") or ""), existed=bool(item.get("existed")), sha256=str(item.get("sha256") or ""), text=str(item.get("text") or "")) for item in payload.get("files", []) if isinstance(item, dict)]
    return CheckpointRecord(
        checkpoint_id=str(payload.get("checkpoint_id") or checkpoint_id),
        task_id=str(payload.get("task_id") or ""),
        plan_id=str(payload.get("plan_id") or ""),
        reason=str(payload.get("reason") or ""),
        created_at_ms=int(payload.get("created_at_ms") or 0),
        files=files,
    )


def list_checkpoints(project: str | Path, *, limit: int = 20) -> list[CheckpointRecord]:
    root = checkpoint_dir(project)
    if not root.exists():
        return []
    records: list[CheckpointRecord] = []
    for path in sorted(root.glob("chk-*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
        try:
            records.append(load_checkpoint(project, path.stem))
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:86", exc)
            continue
    return records


def restore_checkpoint(project: str | Path, checkpoint_id: str) -> CheckpointRecord:
    project_path = Path(project).expanduser().resolve(strict=False)
    record = load_checkpoint(project_path, checkpoint_id)
    for snapshot in record.files:
        target = _resolve(project_path, snapshot.path)
        if snapshot.existed:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(snapshot.text, encoding="utf-8")
        elif target.exists():
            target.unlink()
    return record


def render_checkpoints(records: list[CheckpointRecord]) -> str:
    if not records:
        return "No checkpoints.\n"
    lines = ["# Mako Checkpoints", ""]
    for record in records:
        lines.append(f"- {record.checkpoint_id}: files={len(record.files)} task={record.task_id or '-'} plan={record.plan_id or '-'} reason={record.reason}")
    return "\n".join(lines) + "\n"


def render_checkpoint_detail(record: CheckpointRecord, *, include_text: bool = False, max_chars: int = 1000) -> str:
    lines = [
        "# Mako Checkpoint",
        "",
        f"- checkpoint_id: {record.checkpoint_id}",
        f"- task_id: {record.task_id or '-'}",
        f"- plan_id: {record.plan_id or '-'}",
        f"- reason: {record.reason or '-'}",
        f"- created_at_ms: {record.created_at_ms}",
        f"- files: {len(record.files)}",
        "",
        "## Files",
    ]
    for snapshot in record.files:
        state = "present" if snapshot.existed else "absent"
        lines.append(f"- {snapshot.path} [{state}] sha256={snapshot.sha256 or '-'}")
        if include_text and snapshot.existed:
            preview = snapshot.text if len(snapshot.text) <= max_chars else snapshot.text[:max_chars] + "\n[trimmed]"
            lines.extend(["```", preview, "```"])
    lines.append("")
    lines.append(f"restore: mako checkpoint restore {record.checkpoint_id}")
    return "\n".join(lines) + "\n"


def _snapshot_file(project: Path, path: str | Path) -> FileSnapshot:
    target = _resolve(project, str(path))
    rel = str(target.relative_to(project)) if _inside(target, project) else str(path)
    if not target.exists():
        return FileSnapshot(rel, False)
    text = target.read_text(encoding="utf-8", errors="replace")
    return FileSnapshot(rel, True, hashlib.sha256(text.encode("utf-8")).hexdigest(), text)


def _resolve(project: Path, path: str | Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = project / candidate
    resolved = candidate.expanduser().resolve(strict=False)
    if not _inside(resolved, project):
        raise ValueError(f"checkpoint path escapes project: {path}")
    return resolved


def _inside(path: Path, project: Path) -> bool:
    project = project.expanduser().resolve(strict=False)
    path = path.expanduser().resolve(strict=False)
    return path == project or project in path.parents
