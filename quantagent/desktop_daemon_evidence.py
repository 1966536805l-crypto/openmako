from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from .agent_autopsy import build_agent_autopsy, write_agent_autopsy
from .desktop_control import desktop_dir
from .hook_events import QueryEvent, append_query_event, read_query_events
from .trajectory import TrajectoryEvent, append_event, read_events


DEFAULT_QUERY_ID = "desktop-daemon"
DESKTOP_EVIDENCE_KINDS = frozenset({"screenshot", "ax", "ocr", "command_output"})


@dataclass(frozen=True)
class DesktopEvidenceObject:
    kind: str
    path: str
    sha256: str
    summary: str = ""
    step: int | None = None
    meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["meta"] = dict(self.meta or {})
        return payload


def build_desktop_evidence_object(
    kind: str,
    path: str | Path,
    *,
    summary: str = "",
    step: int | None = None,
    meta: Mapping[str, Any] | None = None,
) -> DesktopEvidenceObject:
    evidence_kind = str(kind or "").strip()
    if evidence_kind not in DESKTOP_EVIDENCE_KINDS:
        allowed = ", ".join(sorted(DESKTOP_EVIDENCE_KINDS))
        raise ValueError(f"desktop evidence kind must be one of: {allowed}")
    artifact = Path(path).expanduser().resolve(strict=False)
    if not artifact.exists():
        raise FileNotFoundError(f"desktop evidence artifact not found: {artifact}")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    return DesktopEvidenceObject(
        kind=evidence_kind,
        path=str(artifact),
        sha256=digest,
        summary=summary,
        step=step,
        meta=dict(meta or {}),
    )


def desktop_daemon_evidence_dir(project: str | Path) -> Path:
    path = desktop_dir(Path(project).expanduser().resolve(strict=False)) / "intelligence" / "daemon"
    path.mkdir(parents=True, exist_ok=True)
    return path


def daemon_query_events_path(project: str | Path) -> Path:
    return desktop_daemon_evidence_dir(project) / "query_events.jsonl"


def daemon_trajectory_path(project: str | Path) -> Path:
    return desktop_daemon_evidence_dir(project) / "trajectory.jsonl"


def daemon_autopsy_path(project: str | Path) -> Path:
    return desktop_daemon_evidence_dir(project) / "openmako-autopsy.md"


def append_daemon_event(
    project: str | Path,
    kind: str,
    summary: str = "",
    *,
    step: int | None = None,
    name: str = "",
    ok: bool | None = None,
    data: Mapping[str, Any] | None = None,
    query_id: str = DEFAULT_QUERY_ID,
    query_events_path: str | Path | None = None,
    failed_at: str = "",
    failure_class: str = "",
    sources: Iterable[str | Path] = (),
) -> QueryEvent:
    payload = _with_failure_metadata(data or {}, failed_at=failed_at, failure_class=failure_class, sources=sources)
    resolved_ok = False if kind == "stop_failure" and ok is None else ok
    return append_query_event(
        query_events_path or daemon_query_events_path(project),
        QueryEvent(
            kind=kind,
            query_id=query_id,
            summary=summary,
            step=step,
            name=name,
            ok=resolved_ok,
            data=payload,
        ),
    )


def append_daemon_trajectory(
    project: str | Path,
    kind: str,
    content: str,
    *,
    step: int | None = None,
    ok: bool | None = None,
    meta: Mapping[str, Any] | None = None,
    trajectory_path: str | Path | None = None,
    failed_at: str = "",
    failure_class: str = "",
    sources: Iterable[str | Path] = (),
) -> TrajectoryEvent:
    payload = _with_failure_metadata(meta or {}, failed_at=failed_at, failure_class=failure_class, sources=sources)
    return append_event(
        trajectory_path or daemon_trajectory_path(project),
        TrajectoryEvent(kind=kind, content=content, step=step, ok=ok, meta=payload),
    )


def write_daemon_failure_autopsy(
    project: str | Path,
    *,
    goal: str = "",
    status: str = "failed",
    summary: str = "",
    query_events_path: str | Path | None = None,
    trajectory_path: str | Path | None = None,
    output_path: str | Path | None = None,
    failed_at: str = "",
    failure_class: str = "",
    sources: Iterable[str | Path] = (),
    source_agent: str = "desktop_daemon",
    title: str = "",
) -> Path:
    project_path = Path(project).expanduser().resolve(strict=False)
    qpath = Path(query_events_path) if query_events_path else daemon_query_events_path(project_path)
    tpath = Path(trajectory_path) if trajectory_path else daemon_trajectory_path(project_path)
    metadata = _metadata_from_paths(qpath, tpath)

    report = build_agent_autopsy(
        project_path,
        trajectory_path=tpath,
        query_events_path=qpath,
        failure_text=summary,
        source_agent=source_agent,
        title=title or f"Desktop Daemon Autopsy: {status}",
        command=goal,
    )
    report = replace(
        report,
        failure_class=failure_class or metadata["failure_class"] or report.failure_class,
        failed_at=failed_at or metadata["failed_at"] or report.failed_at,
        sources=tuple(_dedupe([*report.sources, *metadata["sources"], *_string_sources(sources)])),
    )
    return write_agent_autopsy(report, output_path or daemon_autopsy_path(project_path))


def _with_failure_metadata(
    payload: Mapping[str, Any],
    *,
    failed_at: str,
    failure_class: str,
    sources: Iterable[str | Path],
) -> dict[str, Any]:
    data = dict(payload)
    if failed_at:
        data["failed_at"] = failed_at
    if failure_class:
        data["failure_class"] = failure_class
    source_values = _string_sources(sources)
    if source_values:
        data["sources"] = source_values
    return data


def _metadata_from_paths(query_events_path: Path, trajectory_path: Path) -> dict[str, Any]:
    failed_at = ""
    failure_class = ""
    sources: list[str] = []

    if query_events_path.exists():
        for event in read_query_events(query_events_path):
            data = event.data
            if data.get("failed_at"):
                failed_at = str(data["failed_at"])
            if data.get("failure_class"):
                failure_class = str(data["failure_class"])
            sources.extend(_coerce_sources(data.get("sources")))

    if trajectory_path.exists():
        for event in read_events(trajectory_path):
            meta = event.meta
            if meta.get("failed_at"):
                failed_at = str(meta["failed_at"])
            if meta.get("failure_class"):
                failure_class = str(meta["failure_class"])
            sources.extend(_coerce_sources(meta.get("sources")))

    return {"failed_at": failed_at, "failure_class": failure_class, "sources": _dedupe(sources)}


def _coerce_sources(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, (str, Path)):
        return [str(value)]
    if isinstance(value, Iterable):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _string_sources(sources: Iterable[str | Path]) -> list[str]:
    return _dedupe(str(source) for source in sources if str(source))


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
