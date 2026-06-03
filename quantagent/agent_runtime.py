from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .hook_events import QueryEvent, read_query_events
from .trajectory import TrajectoryEvent, read_events


PASS = "pass"
FAIL = "fail"
PENDING = "pending"
WARN = "warn"


@dataclass(frozen=True)
class RuntimeEvidence:
    evidence_id: str
    source: str
    kind: str
    status: str
    summary: str
    path: str = ""
    step: int | None = None
    ok: bool | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RuntimeVerifier:
    verifier_id: str
    name: str
    status: str
    ok: bool
    summary: str
    evidence_ids: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload


@dataclass(frozen=True)
class RuntimePlanStep:
    step_id: str
    index: int
    name: str
    kind: str
    status: str
    summary: str = ""
    required: bool = True
    evidence_ids: tuple[str, ...] = ()
    verifier_ids: tuple[str, ...] = ()
    data: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_ids"] = list(self.evidence_ids)
        payload["verifier_ids"] = list(self.verifier_ids)
        return payload


@dataclass(frozen=True)
class AgentRuntimeView:
    ok: bool
    status: str
    summary: str
    task: str
    steps: tuple[RuntimePlanStep, ...]
    evidence: tuple[RuntimeEvidence, ...]
    verifiers: tuple[RuntimeVerifier, ...]
    artifacts: dict[str, str] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "task": self.task,
            "steps": [step.to_payload() for step in self.steps],
            "evidence": [item.to_payload() for item in self.evidence],
            "verifiers": [verifier.to_payload() for verifier in self.verifiers],
            "artifacts": dict(self.artifacts),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_payload(), ensure_ascii=False, indent=2)


def build_agent_runtime_view(
    project: str | Path,
    *,
    task: str = "",
    query_events_path: str | Path | None = None,
    trajectory_path: str | Path | None = None,
    desktop_state_path: str | Path | None = None,
    eval_json_path: str | Path | None = None,
    soak_json_path: str | Path | None = None,
) -> AgentRuntimeView:
    project_path = Path(project).expanduser().resolve(strict=False)
    resolved = _resolve_artifacts(
        project_path,
        query_events_path=query_events_path,
        trajectory_path=trajectory_path,
        desktop_state_path=desktop_state_path,
        eval_json_path=eval_json_path,
        soak_json_path=soak_json_path,
    )
    evidence: list[RuntimeEvidence] = []
    steps_by_key: dict[tuple[int, str], dict[str, Any]] = {}

    task_text = str(task or "").strip()
    _ingest_query_events(resolved.get("query_events_path"), evidence, steps_by_key)
    _ingest_trajectory(resolved.get("trajectory_path"), evidence, steps_by_key)
    task_text = task_text or _ingest_desktop_state(resolved.get("desktop_state_path"), evidence, steps_by_key)
    _ingest_eval_result(resolved.get("eval_json_path"), "desktop_eval", evidence, steps_by_key)
    _ingest_eval_result(resolved.get("soak_json_path"), "desktop_soak", evidence, steps_by_key)

    verifiers = _build_verifiers(evidence)
    steps = _build_steps(steps_by_key, verifiers)
    status = _overall_status(steps, verifiers, evidence)
    summary = _summary(status, steps, evidence, verifiers)
    return AgentRuntimeView(
        ok=status == PASS,
        status=status,
        summary=summary,
        task=task_text,
        steps=tuple(steps),
        evidence=tuple(evidence),
        verifiers=tuple(verifiers),
        artifacts={key: str(value) for key, value in resolved.items() if value},
    )


def render_agent_runtime_view(view: AgentRuntimeView) -> str:
    lines = [
        "# Agent Runtime",
        "",
        f"- status: {view.status}",
        f"- ok: {str(view.ok).lower()}",
        f"- task: {view.task or '-'}",
        f"- steps: {len(view.steps)}",
        f"- evidence: {len(view.evidence)}",
        f"- verifiers: {len(view.verifiers)}",
        f"- summary: {view.summary}",
        "",
        "## Steps",
        "",
    ]
    if not view.steps:
        lines.append("- none")
    else:
        for step in view.steps:
            lines.append(f"- [{step.status}] {step.index}. {step.name} ({step.kind}): {step.summary}")
    lines.extend(["", "## Verifiers", ""])
    if not view.verifiers:
        lines.append("- none")
    else:
        for verifier in view.verifiers:
            lines.append(f"- [{verifier.status}] {verifier.name}: {verifier.summary}")
    return "\n".join(lines).rstrip() + "\n"


def _resolve_artifacts(
    project: Path,
    *,
    query_events_path: str | Path | None,
    trajectory_path: str | Path | None,
    desktop_state_path: str | Path | None,
    eval_json_path: str | Path | None,
    soak_json_path: str | Path | None,
) -> dict[str, Path | None]:
    desktop_daemon = project / "AI_协作交接" / "desktop" / "intelligence" / "daemon"
    if not desktop_daemon.exists():
        desktop_daemon = project / ".quantagent" / "desktop" / "intelligence" / "daemon"
    return {
        "query_events_path": _resolve_existing(project, query_events_path, desktop_daemon / "query_events.jsonl"),
        "trajectory_path": _resolve_existing(project, trajectory_path, desktop_daemon / "trajectory.jsonl"),
        "desktop_state_path": _resolve_existing(project, desktop_state_path, desktop_daemon / "latest_state.json"),
        "eval_json_path": _resolve_existing(project, eval_json_path, _latest_json(project / ".quantagent" / "desktop" / "eval", "run_*.json")),
        "soak_json_path": _resolve_existing(project, soak_json_path, _latest_json(project / ".quantagent" / "desktop" / "soak", "soak_*.json")),
    }


def _resolve_existing(project: Path, explicit: str | Path | None, default: Path | None) -> Path | None:
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            path = project / path
        return path if path.exists() else path
    if default is not None and default.exists():
        return default
    return None


def _latest_json(directory: Path, pattern: str) -> Path | None:
    if not directory.exists():
        return None
    candidates = [path for path in directory.glob(pattern) if path.is_file()]
    return max(candidates, key=lambda item: item.stat().st_mtime) if candidates else None


def _ingest_query_events(path: Path | None, evidence: list[RuntimeEvidence], steps: dict[tuple[int, str], dict[str, Any]]) -> None:
    if path is None or not path.exists():
        return
    try:
        events = read_query_events(path)
    except (OSError, ValueError) as exc:
        evidence.append(_evidence("query-events-unreadable", "query_events", "error", FAIL, str(exc), path=str(path), ok=False))
        return
    for index, event in enumerate(events, start=1):
        evidence_id = f"query-{index}"
        evidence.append(
            _evidence(
                evidence_id,
                "query_events",
                event.kind,
                _status_from_ok(event.ok),
                event.summary or event.kind,
                path=str(path),
                step=event.step,
                ok=event.ok,
                data=event.to_dict(),
            )
        )
        if event.step is not None or event.name:
            step_no = event.step if event.step is not None else index
            key = (step_no, event.name or event.kind)
            _merge_step(steps, key, index=step_no, name=event.name or event.kind, kind="query", evidence_id=evidence_id, summary=event.summary, status=_status_from_ok(event.ok))


def _ingest_trajectory(path: Path | None, evidence: list[RuntimeEvidence], steps: dict[tuple[int, str], dict[str, Any]]) -> None:
    if path is None or not path.exists():
        return
    try:
        events = read_events(path)
    except (OSError, ValueError) as exc:
        evidence.append(_evidence("trajectory-unreadable", "trajectory", "error", FAIL, str(exc), path=str(path), ok=False))
        return
    for index, event in enumerate(events, start=1):
        evidence_id = f"trajectory-{index}"
        evidence.append(
            _evidence(
                evidence_id,
                "trajectory",
                event.kind,
                _status_from_ok(event.ok),
                event.content or event.kind,
                path=str(path),
                step=event.step,
                ok=event.ok,
                data=event.to_dict(),
            )
        )
        if event.step is not None:
            key = (event.step, event.kind)
            _merge_step(steps, key, index=event.step, name=event.kind, kind="trajectory", evidence_id=evidence_id, summary=event.content, status=_status_from_ok(event.ok))


def _ingest_desktop_state(path: Path | None, evidence: list[RuntimeEvidence], steps: dict[tuple[int, str], dict[str, Any]]) -> str:
    if path is None or not path.exists():
        return ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        evidence.append(_evidence("desktop-state-unreadable", "desktop_state", "error", FAIL, str(exc), path=str(path), ok=False))
        return ""
    if not isinstance(payload, Mapping):
        evidence.append(_evidence("desktop-state-invalid", "desktop_state", "error", FAIL, "desktop state must be an object", path=str(path), ok=False))
        return ""
    status = str(payload.get("status") or "")
    ok = status in {"completed", "done", "skipped", "dry_run", "time_budget_exhausted", "step_budget_exhausted"}
    evidence.append(
        _evidence(
            "desktop-state",
            "desktop_state",
            status or "state",
            PASS if ok else FAIL if status in {"failed", "blocked", "verify_failed", "stopped"} else PENDING,
            str(payload.get("summary") or status or "desktop state"),
            path=str(path),
            ok=ok if status else None,
            data=_json_safe(payload),
        )
    )
    for index, record in enumerate(_records(payload), start=1):
        step_no = _to_int(record.get("step"), index)
        phase = str(record.get("phase") or f"record-{index}")
        record_status = str(record.get("status") or "")
        record_ok = record_status not in {"failed", "blocked", "verify_failed", "stale_target", "network_failed"}
        evidence_id = f"desktop-record-{index}"
        evidence.append(
            _evidence(
                evidence_id,
                "desktop_record",
                phase,
                PASS if record_ok else FAIL,
                str(record.get("summary") or record_status or phase),
                path=str(path),
                step=step_no,
                ok=record_ok,
                data=_json_safe(record),
            )
        )
        _merge_step(steps, (step_no, phase), index=step_no, name=phase, kind="desktop", evidence_id=evidence_id, summary=str(record.get("summary") or ""), status=PASS if record_ok else FAIL)
    return str(payload.get("goal") or "")


def _ingest_eval_result(path: Path | None, source: str, evidence: list[RuntimeEvidence], steps: dict[tuple[int, str], dict[str, Any]]) -> None:
    if path is None or not path.exists():
        return
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        evidence.append(_evidence(f"{source}-unreadable", source, "error", FAIL, str(exc), path=str(path), ok=False))
        return
    if not isinstance(payload, Mapping):
        evidence.append(_evidence(f"{source}-invalid", source, "error", FAIL, f"{source} result must be an object", path=str(path), ok=False))
        return
    result_ok = bool(payload.get("ok"))
    evidence.append(_evidence(source, source, str(payload.get("status") or source), PASS if result_ok else FAIL, str(payload.get("summary") or source), path=str(path), ok=result_ok, data=_json_safe(payload.get("metrics") or {})))
    items = payload.get("scenarios") if source == "desktop_eval" else payload.get("cycles")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        return
    for index, item in enumerate(items, start=1):
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("id") or item.get("eval_run_id") or f"{source}-{index}")
        ok = bool(item.get("ok"))
        evidence_id = f"{source}-{index}"
        evidence.append(
            _evidence(
                evidence_id,
                source,
                str(item.get("status") or source),
                PASS if ok else FAIL,
                str(item.get("summary") or name),
                path=str(path),
                step=index,
                ok=ok,
                data=_json_safe(item),
            )
        )
        _merge_step(steps, (index, name), index=index, name=name, kind=source, evidence_id=evidence_id, summary=str(item.get("summary") or ""), status=PASS if ok else FAIL)


def _build_verifiers(evidence: Sequence[RuntimeEvidence]) -> list[RuntimeVerifier]:
    by_step: dict[tuple[str, int], list[RuntimeEvidence]] = {}
    for item in evidence:
        if item.step is not None:
            by_step.setdefault((item.source, item.step), []).append(item)
    verifiers: list[RuntimeVerifier] = []
    for (source, step_no), items in sorted(by_step.items()):
        failed = [item for item in items if item.status == FAIL]
        passed = [item for item in items if item.status == PASS]
        status = FAIL if failed else PASS if passed else PENDING
        summary = failed[0].summary if failed else f"{len(passed)} evidence item(s) passed" if passed else "no terminal evidence"
        verifiers.append(RuntimeVerifier(f"verify-{source}-step-{step_no}", f"{source} step {step_no}", status, status == PASS, summary, tuple(item.evidence_id for item in items)))
    if evidence and not verifiers:
        failed = [item for item in evidence if item.status == FAIL]
        status = FAIL if failed else PASS if all(item.status == PASS for item in evidence) else PENDING
        summary = failed[0].summary if failed else "artifact-level evidence passed" if status == PASS else "artifact-level evidence pending"
        verifiers.append(RuntimeVerifier("verify-artifacts", "artifacts", status, status == PASS, summary, tuple(item.evidence_id for item in evidence)))
    return verifiers


def _build_steps(steps: Mapping[tuple[int, str], dict[str, Any]], verifiers: Sequence[RuntimeVerifier]) -> list[RuntimePlanStep]:
    verifier_by_evidence: dict[str, list[RuntimeVerifier]] = {}
    for verifier in verifiers:
        for evidence_id in verifier.evidence_ids:
            verifier_by_evidence.setdefault(evidence_id, []).append(verifier)
    out: list[RuntimePlanStep] = []
    for offset, ((index, name), payload) in enumerate(sorted(steps.items(), key=lambda item: (item[0][0], item[0][1])), start=1):
        step_verifiers = _dedupe_verifiers(verifier for evidence_id in payload.get("evidence_ids") or () for verifier in verifier_by_evidence.get(str(evidence_id), ()))
        status = FAIL if any(verifier.status == FAIL for verifier in step_verifiers) else PASS if any(verifier.status == PASS for verifier in step_verifiers) else payload.get("status") or PENDING
        out.append(
            RuntimePlanStep(
                step_id=f"step-{offset}",
                index=index,
                name=name,
                kind=str(payload.get("kind") or "runtime"),
                status=str(status),
                summary=str(payload.get("summary") or ""),
                evidence_ids=tuple(payload.get("evidence_ids") or ()),
                verifier_ids=tuple(verifier.verifier_id for verifier in step_verifiers),
                data=_json_safe(payload.get("data") or {}),
            )
        )
    return out


def _dedupe_verifiers(items: Iterable[RuntimeVerifier]) -> list[RuntimeVerifier]:
    seen: set[str] = set()
    out: list[RuntimeVerifier] = []
    for item in items:
        if item.verifier_id in seen:
            continue
        seen.add(item.verifier_id)
        out.append(item)
    return out


def _overall_status(steps: Sequence[RuntimePlanStep], verifiers: Sequence[RuntimeVerifier], evidence: Sequence[RuntimeEvidence]) -> str:
    if any(item.status == FAIL for item in verifiers) or any(item.status == FAIL for item in steps):
        return FAIL
    if verifiers and all(item.status == PASS for item in verifiers):
        return PASS
    if evidence and all(item.status == PASS for item in evidence):
        return PASS
    if evidence or steps:
        return PENDING
    return WARN


def _summary(status: str, steps: Sequence[RuntimePlanStep], evidence: Sequence[RuntimeEvidence], verifiers: Sequence[RuntimeVerifier]) -> str:
    failed = [item for item in verifiers if item.status == FAIL]
    if failed:
        return f"runtime verification failed: {failed[0].summary}"
    return f"runtime {status}: steps={len(steps)}, evidence={len(evidence)}, verifiers={len(verifiers)}"


def _merge_step(
    steps: dict[tuple[int, str], dict[str, Any]],
    key: tuple[int, str],
    *,
    index: int,
    name: str,
    kind: str,
    evidence_id: str,
    summary: str,
    status: str,
) -> None:
    payload = steps.setdefault(key, {"index": index, "name": name, "kind": kind, "evidence_ids": [], "summary": "", "status": PENDING})
    payload["evidence_ids"].append(evidence_id)
    if summary:
        payload["summary"] = summary
    if status == FAIL or payload.get("status") != FAIL:
        payload["status"] = status


def _evidence(
    evidence_id: str,
    source: str,
    kind: str,
    status: str,
    summary: str,
    *,
    path: str = "",
    step: int | None = None,
    ok: bool | None = None,
    data: Mapping[str, Any] | None = None,
) -> RuntimeEvidence:
    return RuntimeEvidence(evidence_id, source, kind, status, summary[:500], path, step, ok, _json_safe(data or {}))


def _status_from_ok(ok: bool | None) -> str:
    if ok is True:
        return PASS
    if ok is False:
        return FAIL
    return PENDING


def _records(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    records = payload.get("records") or []
    if not isinstance(records, list):
        return []
    return [record for record in records if isinstance(record, Mapping)]


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _json_safe(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if is_dataclass(value):
        return _json_safe(asdict(value))
    return str(value)
