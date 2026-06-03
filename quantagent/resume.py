from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .query_runtime import QueryRuntime
from .runtime_store import record_compact_event
from .sessions import latest_session, load_session, render_session
from .subagents import get_subagent, load_subagents, render_subagents
from .task_state import FAILED, load_tasks, render_tasks
from .trajectory_compact import CompactMetrics, compact_messages, estimate_tokens


@dataclass(frozen=True)
class ResumeBundle:
    kind: str
    summary: str
    command: str
    body: str


@dataclass(frozen=True)
class ResumeSnapshot:
    snapshot_id: str
    kind: str
    source_id: str
    project: str
    created_at: str
    summary: str
    command: str
    body: str
    compacted_messages: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)
    auto: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def resume_last_failure(project: str | Path) -> ResumeBundle:
    project_path = Path(project).expanduser().resolve(strict=False)
    failed = [task for task in load_tasks(project_path) if task.status == FAILED]
    failed.sort(key=lambda task: task.updated_at, reverse=True)
    if not failed:
        return ResumeBundle("last_failure", "no failed task found", "mako task --refresh", "No failed task found.\n")
    task = failed[0]
    command = f"mako task --project {project_path} --output {task.id}"
    return ResumeBundle("last_failure", f"resume failed task {task.id}", command, render_tasks([task]))


def resume_task(project: str | Path, task_id: str) -> ResumeBundle:
    project_path = Path(project).expanduser().resolve(strict=False)
    for task in load_tasks(project_path):
        if task.id == task_id:
            return ResumeBundle("task", f"resume task {task.id}", f"mako task --project {project_path} --output {task.id}", render_tasks([task]))
    raise KeyError(f"task not found: {task_id}")


def resume_agent(project: str | Path, subagent_id: str = "") -> ResumeBundle:
    project_path = Path(project).expanduser().resolve(strict=False)
    records = load_subagents(project_path)
    if subagent_id:
        records = [record for record in records if record.subagent_id == subagent_id]
    if not records:
        return ResumeBundle("agent", "no subagent found", "mako subagent list --refresh", "No subagent found.\n")
    records.sort(key=lambda record: record.updated_at, reverse=True)
    record = records[0]
    return ResumeBundle("agent", f"resume subagent {record.subagent_id}", f"mako subagent show {record.subagent_id}", render_subagents([record]))


def resume_session(project: str | Path) -> ResumeBundle:
    project_path = Path(project).expanduser().resolve(strict=False)
    record = latest_session(project_path)
    if not record:
        return ResumeBundle("session", "no session found", "mako session --new", "No session found.\n")
    return ResumeBundle("session", f"resume session {record.session_id}", f"mako session --show {record.session_id}", render_session(record))


def resume_snapshot_dir(project: str | Path) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    base = project_path / "AI_协作交接"
    if not base.exists():
        base = project_path / ".quantagent"
    return base / "quantagent_resume_snapshots"


def resume_snapshot_path(project: str | Path, snapshot_id: str) -> Path:
    return resume_snapshot_dir(project) / f"{snapshot_id}.json"


def create_resume_snapshot(
    project: str | Path,
    kind: str = "session",
    *,
    source_id: str = "",
    target_summary_chars: int = 2200,
    auto: bool = False,
) -> ResumeSnapshot:
    """Persist a compact, deterministic resume artifact for long-running work."""
    project_path = Path(project).expanduser().resolve(strict=False)
    bundle, messages, artifacts = _snapshot_source(project_path, kind, source_id)
    compacted = compact_messages(messages, first_n=1, last_n=8, target_summary_chars=target_summary_chars)
    summary_entry = compacted.summary_entry or {}
    summary_text = str(summary_entry.get("content") or bundle.summary)
    source = _source_id_from_bundle(kind, source_id, bundle)
    snapshot = ResumeSnapshot(
        snapshot_id="resume-" + uuid.uuid4().hex[:12],
        kind=kind,
        source_id=source,
        project=str(project_path),
        created_at=datetime.now().isoformat(timespec="seconds"),
        summary=summary_text,
        command=bundle.command,
        body=bundle.body,
        compacted_messages=compacted.messages,
        metrics=compacted.metrics.to_dict(),
        artifacts=artifacts,
        auto=auto,
    )
    path = resume_snapshot_path(project_path, snapshot.snapshot_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        record_compact_event(
            project_path,
            model="resume",
            reason="resume_snapshot",
            mode="resume_snapshot",
            applied=True,
            session_id=source if kind == "session" else None,
            target_tokens=0,
            original_estimated_tokens=int(snapshot.metrics.get("original_estimated_tokens") or 0),
            compacted_estimated_tokens=int(snapshot.metrics.get("compacted_estimated_tokens") or 0),
            saved_estimated_tokens=int(snapshot.metrics.get("saved_estimated_tokens") or 0),
            protected_user_request=False,
            tokenizer_source="heuristic:trajectory_compact",
            token_count_exact=False,
            details={
                "snapshot_id": snapshot.snapshot_id,
                "kind": snapshot.kind,
                "source_id": snapshot.source_id,
                "artifact_path": str(path),
                "auto": auto,
                "metrics": snapshot.metrics,
            },
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:136", exc)
    QueryRuntime(project_path).emit(
        "resume_snapshot",
        f"resume snapshot created: {snapshot.snapshot_id}",
        ok=True,
        data={"kind": snapshot.kind, "source_id": snapshot.source_id, "path": str(path), "auto": auto, "metrics": snapshot.metrics},
    )
    return snapshot


def maybe_create_resume_snapshot(
    project: str | Path,
    kind: str = "session",
    *,
    source_id: str = "",
    token_threshold: int = 12_000,
    target_summary_chars: int = 2200,
) -> tuple[ResumeSnapshot | None, bool]:
    """Create a snapshot only when the source body is above a token threshold."""
    project_path = Path(project).expanduser().resolve(strict=False)
    bundle, messages, _artifacts = _snapshot_source(project_path, kind, source_id)
    estimate = estimate_tokens(bundle.body) + estimate_tokens(messages)
    if estimate < token_threshold:
        return None, False
    return create_resume_snapshot(
        project_path,
        kind,
        source_id=source_id,
        target_summary_chars=target_summary_chars,
        auto=True,
    ), True


def load_resume_snapshot(project: str | Path, snapshot_id: str) -> ResumeSnapshot:
    path = resume_snapshot_path(project, snapshot_id)
    if not path.exists():
        raise KeyError(f"resume snapshot not found: {snapshot_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("resume snapshot must be a JSON object")
    return ResumeSnapshot(
        snapshot_id=str(payload.get("snapshot_id") or snapshot_id),
        kind=str(payload.get("kind") or ""),
        source_id=str(payload.get("source_id") or ""),
        project=str(payload.get("project") or project),
        created_at=str(payload.get("created_at") or ""),
        summary=str(payload.get("summary") or ""),
        command=str(payload.get("command") or ""),
        body=str(payload.get("body") or ""),
        compacted_messages=[dict(item) for item in payload.get("compacted_messages", []) if isinstance(item, dict)],
        metrics=dict(payload.get("metrics") or {}),
        artifacts=[str(item) for item in payload.get("artifacts", [])],
        auto=bool(payload.get("auto", False)),
    )


def list_resume_snapshots(project: str | Path, *, limit: int = 20) -> list[ResumeSnapshot]:
    directory = resume_snapshot_dir(project)
    if not directory.exists():
        return []
    rows: list[ResumeSnapshot] = []
    for path in sorted(directory.glob("resume-*.json"), reverse=True):
        try:
            rows.append(load_resume_snapshot(project, path.stem))
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:190", exc)
            continue
    return rows[: max(0, limit)]


def render_resume_snapshot(snapshot: ResumeSnapshot, *, include_body: bool = False) -> str:
    lines = [
        f"# Resume Snapshot {snapshot.snapshot_id}",
        "",
        f"- kind: {snapshot.kind}",
        f"- source_id: {snapshot.source_id or '-'}",
        f"- created_at: {snapshot.created_at}",
        f"- auto: {str(snapshot.auto).lower()}",
        f"- command: {snapshot.command}",
        f"- artifacts: {len(snapshot.artifacts)}",
    ]
    if snapshot.metrics:
        metrics = CompactMetrics(**snapshot.metrics) if _compact_metrics_compatible(snapshot.metrics) else None
        if metrics:
            lines.append(
                f"- tokens: {metrics.original_estimated_tokens} -> {metrics.compacted_estimated_tokens} "
                f"(saved {metrics.saved_estimated_tokens})"
            )
    lines.extend(["", "## Summary", "", snapshot.summary.strip() or "(empty summary)"])
    if snapshot.artifacts:
        lines.extend(["", "## Artifacts", ""])
        lines.extend(f"- {item}" for item in snapshot.artifacts)
    if include_body:
        lines.extend(["", "## Resume Body", "", snapshot.body.rstrip()])
    return "\n".join(lines).rstrip() + "\n"


def render_resume_snapshots(snapshots: list[ResumeSnapshot]) -> str:
    if not snapshots:
        return "No resume snapshots.\n"
    lines = ["# Resume Snapshots", ""]
    for snapshot in snapshots:
        auto = " auto" if snapshot.auto else ""
        lines.append(f"- {snapshot.snapshot_id} [{snapshot.kind}{auto}] {snapshot.created_at} source={snapshot.source_id or '-'}")
        lines.append(f"  {snapshot.summary.replace(chr(10), ' ')[:180]}")
    return "\n".join(lines) + "\n"


def _snapshot_source(project: Path, kind: str, source_id: str) -> tuple[ResumeBundle, list[dict[str, Any]], list[str]]:
    if kind == "session":
        record = load_session(project, source_id) if source_id else latest_session(project)
        if not record:
            raise KeyError("session not found")
        return (
            ResumeBundle("session", f"resume session {record.session_id}", f"mako session --project {project} --show {record.session_id}", render_session(record, limit=50)),
            [
                {
                    "role": message.role,
                    "content": message.content,
                    "timestamp": message.timestamp,
                    "meta": message.meta,
                }
                for message in record.messages
            ],
            [],
        )
    if kind == "task":
        for task in load_tasks(project):
            if task.id == source_id:
                body = render_tasks([task])
                messages = [
                    {"role": "task", "content": task.title, "meta": {"status": task.status, "detail": task.detail}},
                    *[{"role": "event", "content": json.dumps(item, ensure_ascii=False, sort_keys=True), "meta": {"kind": "task_history"}} for item in task.history],
                ]
                return ResumeBundle("task", f"resume task {task.id}", f"mako task --project {project} --output {task.id}", body), messages, list(task.evidence)
        raise KeyError(f"task not found: {source_id}")
    if kind == "agent":
        record = get_subagent(project, source_id) if source_id else (load_subagents(project)[-1] if load_subagents(project) else None)
        if not record:
            raise KeyError("subagent not found")
        body = render_subagents([record])
        messages = [
            {"role": "subagent", "content": record.task, "meta": {"status": record.status, "profile": record.agent_profile}},
            {"role": "progress", "content": record.progress_summary, "meta": {"outcome": record.terminal_outcome}},
        ]
        if record.context_path:
            try:
                context = Path(record.context_path).read_text(encoding="utf-8", errors="replace")
                messages.append({"role": "context", "content": context[:12_000], "meta": {"path": record.context_path}})
            except OSError:
                pass
        return ResumeBundle("agent", f"resume subagent {record.subagent_id}", f"mako subagent show {record.subagent_id}", body), messages, list(record.artifacts)
    raise ValueError("kind must be session, task, or agent")


def _source_id_from_bundle(kind: str, source_id: str, bundle: ResumeBundle) -> str:
    if source_id:
        return source_id
    marker = "resume session " if kind == "session" else "resume task " if kind == "task" else "resume subagent "
    if bundle.summary.startswith(marker):
        return bundle.summary.removeprefix(marker).strip()
    return ""


def _compact_metrics_compatible(metrics: dict[str, Any]) -> bool:
    required = {
        "original_messages",
        "final_messages",
        "preserved_first",
        "preserved_last",
        "summarized_middle",
        "original_estimated_tokens",
        "compacted_estimated_tokens",
        "saved_estimated_tokens",
        "compression_ratio",
        "summary_trimmed",
    }
    return required <= set(metrics)
