from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .hook_events import QueryEvent, read_query_events
from .query_runtime import query_event_path
from .trajectory import TrajectoryEvent, append_event, read_events


@dataclass(frozen=True)
class AutopsyEvidence:
    evidence_id: str
    source: str
    kind: str
    summary: str
    step: int | None = None
    name: str = ""
    ok: bool | None = None
    reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AutopsyFinding:
    finding_type: str
    summary: str
    evidence_ids: tuple[str, ...] = ()
    intercept: str = ""
    confidence: str = "medium"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence_ids"] = list(self.evidence_ids)
        return payload


@dataclass(frozen=True)
class AgentAutopsyReport:
    title: str
    source_agent: str
    command: str
    status: str
    failure_class: str
    failed_at: str
    evidence: tuple[AutopsyEvidence, ...]
    findings: tuple[AutopsyFinding, ...]
    intercepts: tuple[str, ...]
    sources: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "source_agent": self.source_agent,
            "command": self.command,
            "status": self.status,
            "failure_class": self.failure_class,
            "failed_at": self.failed_at,
            "evidence": [item.to_dict() for item in self.evidence],
            "findings": [item.to_dict() for item in self.findings],
            "intercepts": list(self.intercepts),
            "sources": list(self.sources),
        }


@dataclass(frozen=True)
class AgentAutopsyRunResult:
    report: AgentAutopsyReport
    exit_code: int
    trajectory_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "exit_code": self.exit_code,
            "trajectory_path": self.trajectory_path,
            "report": self.report.to_dict(),
        }


def build_agent_autopsy(
    project: str | Path,
    *,
    trajectory_path: str | Path | None = None,
    query_events_path: str | Path | None = None,
    failure_file: str | Path | None = None,
    failure_text: str = "",
    source_agent: str = "unknown",
    title: str = "",
    command: str = "",
    limit: int = 40,
) -> AgentAutopsyReport:
    project_path = Path(project).expanduser().resolve(strict=False)
    sources: list[str] = []
    query_events: list[QueryEvent] = []
    trajectory_events: list[TrajectoryEvent] = []

    qpath = Path(query_events_path).expanduser().resolve(strict=False) if query_events_path else query_event_path(project_path)
    if qpath.exists():
        query_events = read_query_events(qpath)
        sources.append(str(qpath))

    if trajectory_path:
        tpath = Path(trajectory_path).expanduser().resolve(strict=False)
        if not tpath.is_absolute():
            tpath = project_path / tpath
        if tpath.exists():
            trajectory_events = read_events(tpath)
            sources.append(str(tpath))

    external_failure = _load_failure_text(project_path, failure_file, failure_text, sources)
    evidence = _build_evidence(query_events, trajectory_events, external_failure, limit=max(1, limit))
    if not evidence:
        return AgentAutopsyReport(
            title=title or "Agent Failure Autopsy",
            source_agent=source_agent or "unknown",
            command=command,
            status="UNVERIFIED",
            failure_class="",
            failed_at="",
            evidence=(),
            findings=(
                AutopsyFinding(
                    "missing_trace",
                    "No trajectory or query-event evidence was available, so the failure cannot be reconstructed.",
                    confidence="high",
                ),
            ),
            intercepts=(),
            sources=tuple(sources),
        )

    failure_class = _terminal_failure_class(query_events, evidence) or _classify_failure_text(external_failure)
    failed = [item for item in evidence if item.ok is False or item.kind == "stop_failure"]
    status = "FAILED" if failed or failure_class else "PASSED"
    first_failure = failed[0] if failed else None
    failed_at = _failed_at(first_failure) if first_failure else ""
    findings = _findings(evidence, failure_class=failure_class, first_failure=first_failure)
    intercepts = _dedupe(item.intercept for item in findings if item.intercept)
    return AgentAutopsyReport(
        title=title or "Agent Failure Autopsy",
        source_agent=source_agent or "unknown",
        command=command,
        status=status,
        failure_class=failure_class,
        failed_at=failed_at,
        evidence=tuple(evidence),
        findings=tuple(findings),
        intercepts=tuple(intercepts),
        sources=tuple(sources),
    )


def run_agent_autopsy_command(
    project: str | Path,
    command: list[str],
    *,
    source_agent: str = "unknown",
    title: str = "",
    timeout: int = 600,
) -> AgentAutopsyRunResult:
    if not command:
        raise ValueError("autopsy wrapper command is empty")
    project_path = Path(project).expanduser().resolve(strict=False)
    output_dir = project_path / ".quantagent" / "autopsy"
    output_dir.mkdir(parents=True, exist_ok=True)
    trajectory_path = output_dir / f"autopsy_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.jsonl"
    command_text = shlex.join(command)

    append_event(
        trajectory_path,
        TrajectoryEvent(
            kind="action",
            content=f"wrapped agent command: {command_text}",
            ok=None,
            meta={"command": command},
        ),
    )
    failure_text = ""
    try:
        completed = subprocess.run(
            command,
            cwd=str(project_path),
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        exit_code = int(completed.returncode)
        output = _bounded_output(completed.stdout, completed.stderr)
        if exit_code != 0:
            failure_text = f"command exited {exit_code}\n{output}".strip()
        append_event(
            trajectory_path,
            TrajectoryEvent(
                kind="test",
                content=f"wrapped command exited {exit_code}\n{output}".strip(),
                ok=exit_code == 0,
                meta={"command": command, "exit_code": exit_code},
            ),
        )
    except FileNotFoundError as exc:
        exit_code = 127
        failure_text = f"command not found: {command[0]} ({exc})"
        append_event(
            trajectory_path,
            TrajectoryEvent(kind="test", content=failure_text, ok=False, meta={"command": command, "exit_code": exit_code}),
        )
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        failure_text = f"command timed out after {timeout}s\n{_bounded_output(exc.stdout, exc.stderr)}".strip()
        append_event(
            trajectory_path,
            TrajectoryEvent(kind="test", content=failure_text, ok=False, meta={"command": command, "exit_code": exit_code}),
        )

    report = build_agent_autopsy(
        project_path,
        trajectory_path=trajectory_path,
        failure_text=failure_text,
        source_agent=source_agent,
        title=title,
        command=command_text,
    )
    return AgentAutopsyRunResult(report=report, exit_code=exit_code, trajectory_path=str(trajectory_path))


def render_agent_autopsy(report: AgentAutopsyReport) -> str:
    lines = [
        f"# {report.title or 'Agent Failure Autopsy'}",
        "",
        f"- source_agent: {report.source_agent or 'unknown'}",
        f"- command: {report.command or 'unknown'}",
        f"- status: {report.status}",
        f"- failure_class: {report.failure_class or 'unknown'}",
        f"- failed_at: {report.failed_at or 'unknown'}",
        f"- evidence_items: {len(report.evidence)}",
        "",
        "## Timeline",
        "",
    ]
    if not report.evidence:
        lines.append("- no trace evidence")
    for item in report.evidence:
        status = "ok" if item.ok is True else "failed" if item.ok is False else "unknown"
        step = f" step={item.step}" if item.step is not None else ""
        name = f" name={item.name}" if item.name else ""
        lines.append(f"- {item.evidence_id} [{item.source}:{item.kind}{step}{name} {status}] {_preview(item.summary, 180)}")
        if item.reason:
            lines.append(f"  reason: {item.reason}")

    lines.extend(["", "## Findings", ""])
    if not report.findings:
        lines.append("- none")
    for finding in report.findings:
        evidence = f" evidence={','.join(finding.evidence_ids)}" if finding.evidence_ids else ""
        lines.append(f"- [{finding.finding_type}] {finding.summary}{evidence}")
        if finding.intercept:
            lines.append(f"  intercept: {finding.intercept}")
        lines.append(f"  confidence: {finding.confidence}")

    lines.extend(["", "## Earlier Intercepts", ""])
    if report.intercepts:
        lines.extend(f"- {item}" for item in report.intercepts)
    else:
        lines.append("- none proven from supplied trace")

    lines.extend(["", "## Sources", ""])
    if report.sources:
        lines.extend(f"- {source}" for source in report.sources)
    else:
        lines.append("- no source file found")
    lines.extend(
        [
            "",
            "## Middleware Trial",
            "",
            "- Wrap external agents with `mako agent-autopsy --run -- <agent command>` to capture a failure timeline without replacing the agent.",
            "",
            "## GitHub Action Trial",
            "",
            "- Use `action.yml` to upload `openmako-autopsy.md` when an agent-generated CI run fails.",
            "",
            "All conclusions above are deterministic from the supplied trace data; no model validity judgment was used.",
        ]
    )
    return "\n".join(lines) + "\n"


def _build_evidence(
    query_events: Iterable[QueryEvent],
    trajectory_events: Iterable[TrajectoryEvent],
    external_failure: str,
    *,
    limit: int,
) -> list[AutopsyEvidence]:
    evidence: list[AutopsyEvidence] = []
    for index, event in enumerate(query_events, start=1):
        reason = _reason_from_query_event(event)
        evidence.append(
            AutopsyEvidence(
                evidence_id=f"Q{index}",
                source="query",
                kind=event.kind,
                summary=event.summary,
                step=event.step,
                name=event.name,
                ok=event.ok,
                reason=reason,
                data=_compact_data(event.data),
            )
        )
    for index, event in enumerate(trajectory_events, start=1):
        evidence.append(
            AutopsyEvidence(
                evidence_id=f"T{index}",
                source="trajectory",
                kind=event.kind,
                summary=event.content,
                step=event.step,
                ok=event.ok,
                reason=_reason_from_trajectory_event(event),
                data=_compact_data(event.meta),
            )
        )
    if external_failure.strip():
        evidence.append(
            AutopsyEvidence(
                evidence_id="F1",
                source="failure",
                kind="failure_log",
                summary=external_failure.strip(),
                ok=False,
                reason="external failure log supplied",
                data={"failure_class": _classify_failure_text(external_failure)},
            )
        )
    if len(evidence) <= limit:
        return evidence
    failed_ids = {item.evidence_id for item in evidence if item.ok is False or item.kind == "stop_failure"}
    head_count = max(1, limit // 3)
    tail_count = max(1, limit - head_count)
    selected: list[AutopsyEvidence] = []
    selected.extend(evidence[:head_count])
    selected.extend(item for item in evidence if item.evidence_id in failed_ids)
    selected.extend(evidence[-tail_count:])
    deduped: dict[str, AutopsyEvidence] = {}
    for item in selected:
        deduped.setdefault(item.evidence_id, item)
    return list(deduped.values())[:limit]


def _findings(
    evidence: list[AutopsyEvidence],
    *,
    failure_class: str,
    first_failure: AutopsyEvidence | None,
) -> list[AutopsyFinding]:
    findings: list[AutopsyFinding] = []
    if failure_class:
        findings.append(
            AutopsyFinding(
                "terminal_failure_class",
                f"Trace ended with failure_class={failure_class}.",
                evidence_ids=tuple(item.evidence_id for item in evidence if item.kind == "stop_failure")[:1],
                intercept=_intercept_for_failure_class(failure_class),
                confidence="high",
            )
        )
    if first_failure is not None:
        findings.append(
            AutopsyFinding(
                "first_failed_event",
                f"First failed event was {_failed_at(first_failure)}.",
                evidence_ids=(first_failure.evidence_id,),
                intercept=_intercept_for_event(first_failure),
                confidence="high",
            )
        )

    policy = [item for item in evidence if _contains_policy_block(item)]
    if policy:
        findings.append(
            AutopsyFinding(
                "policy_gate_block",
                "A tool or command was blocked by policy before or during execution.",
                evidence_ids=(policy[0].evidence_id,),
                intercept="surface the required approval/profile mismatch before executing the step",
                confidence="high",
            )
        )

    model_failures = [item for item in evidence if item.kind == "post_model" and item.ok is False]
    if model_failures:
        err = str(model_failures[0].data.get("error_kind") or "")
        summary = f"Model call failed{f' with error_kind={err}' if err else ''}."
        findings.append(
            AutopsyFinding(
                "model_call_failure",
                summary,
                evidence_ids=(model_failures[0].evidence_id,),
                intercept=_model_intercept(err),
                confidence="high" if err else "medium",
            )
        )

    edit_index = next((idx for idx, item in enumerate(evidence) if item.kind == "edit"), None)
    test_failure = next((item for idx, item in enumerate(evidence) if item.kind == "test" and item.ok is False and (edit_index is None or idx > edit_index)), None)
    if test_failure is not None:
        findings.append(
            AutopsyFinding(
                "post_edit_validation_failure",
                "A validation/test failure appeared after an edit was made.",
                evidence_ids=(test_failure.evidence_id,),
                intercept="run patch-shape and targeted-test gates before accepting the edited state",
                confidence="medium",
            )
        )

    if any(item.kind == "stop_failure" and "answer_guard" in str(item.data.get("failure_class") or item.summary).lower() for item in evidence):
        findings.append(
            AutopsyFinding(
                "answer_guard_block",
                "Final answer was blocked by the answer guard.",
                evidence_ids=tuple(item.evidence_id for item in evidence if item.kind == "stop_failure")[:1],
                intercept="treat unsupported final claims as failed preflight before response generation",
                confidence="high",
            )
        )

    external = [item for item in evidence if item.source == "failure" and item.kind == "failure_log"]
    if external:
        findings.append(
            AutopsyFinding(
                "external_failure_log",
                "A caller-supplied failure log marks this run as failed; deeper cause attribution depends on trajectory/query evidence.",
                evidence_ids=(external[0].evidence_id,),
                intercept="capture query_events and trajectory for this external agent run before comparing behavior",
                confidence="high",
            )
        )

    if not findings:
        findings.append(
            AutopsyFinding(
                "no_failure_observed",
                "No failed event was present in the supplied trace.",
                confidence="high",
            )
        )
    return findings


def _terminal_failure_class(query_events: list[QueryEvent], evidence: list[AutopsyEvidence]) -> str:
    for event in reversed(query_events):
        if event.kind == "stop_failure":
            return str(event.data.get("failure_class") or "").strip()
    for item in reversed(evidence):
        if item.kind == "stop_failure":
            return str(item.data.get("failure_class") or "").strip()
    return ""


def _load_failure_text(project: Path, failure_file: str | Path | None, failure_text: str, sources: list[str]) -> str:
    parts: list[str] = []
    if failure_text.strip():
        parts.append(failure_text.strip())
    if failure_file:
        path = Path(failure_file).expanduser().resolve(strict=False)
        if not path.is_absolute():
            path = project / path
        text = path.read_text(encoding="utf-8", errors="replace")
        sources.append(str(path))
        parts.append(text)
    return "\n".join(part for part in parts if part.strip())


def _classify_failure_text(text: str) -> str:
    lowered = text.lower()
    if not lowered.strip():
        return ""
    if "assertionerror" in lowered or "assertion failed" in lowered:
        return "assertion"
    if "permission" in lowered or "policy_blocked" in lowered or "approval" in lowered:
        return "policy_blocked"
    if "importerror" in lowered or "modulenotfounderror" in lowered:
        return "import"
    if "syntaxerror" in lowered:
        return "syntax"
    if "timeout" in lowered:
        return "timeout"
    if "test" in lowered and ("failed" in lowered or "failure" in lowered):
        return "verification_failed"
    return "external_failure"


def _failed_at(item: AutopsyEvidence | None) -> str:
    if item is None:
        return ""
    step = f"step {item.step}" if item.step is not None else "unknown step"
    name = f" {item.name}" if item.name else ""
    return f"{item.source}:{item.kind}{name} ({step})"


def _intercept_for_failure_class(failure_class: str) -> str:
    lowered = failure_class.lower()
    if "policy" in lowered or "permission" in lowered:
        return "precompute approval requirements and block the plan before the side-effect step"
    if "answer_guard" in lowered:
        return "run answer-guard preflight on the draft before finalizing the run"
    if "verification" in lowered or "test" in lowered:
        return "require targeted validation to pass before broadening or finalizing"
    if lowered in {"auth", "rate_limit", "context_length", "model_error"}:
        return "run model credential/token preflight before entering the repair loop"
    return ""


def _intercept_for_event(item: AutopsyEvidence) -> str:
    if _contains_policy_block(item):
        return "surface the policy decision before executing the step"
    if item.kind == "post_model":
        return _model_intercept(str(item.data.get("error_kind") or ""))
    if item.kind == "test":
        return "gate completion on the failing test becoming green"
    if item.kind == "post_tool":
        return "validate tool preconditions and expected output contract before dependent steps"
    return ""


def _model_intercept(error_kind: str) -> str:
    if error_kind == "auth":
        return "check credentials before the first model call"
    if error_kind == "context_length":
        return "compress trajectory and receipts before model call"
    if error_kind == "rate_limit":
        return "route through retry/backoff or fallback model before continuing"
    if error_kind:
        return f"preflight or retry policy should classify model error_kind={error_kind}"
    return "record provider error details and stop before downstream tool steps"


def _contains_policy_block(item: AutopsyEvidence) -> bool:
    data_blob = json.dumps(item.data, ensure_ascii=False, sort_keys=True).lower()
    text = f"{item.summary} {item.reason} {data_blob}".lower()
    return "policy_blocked" in text or "blocked" in text and ("policy" in text or "approval" in text)


def _reason_from_query_event(event: QueryEvent) -> str:
    if event.kind == "stop_failure":
        failure_class = str(event.data.get("failure_class") or "").strip()
        return f"terminal failure_class={failure_class}" if failure_class else "terminal failure"
    if event.ok is False:
        err = str(event.data.get("error_kind") or "").strip()
        return f"event failed{f' error_kind={err}' if err else ''}"
    if event.data.get("blocked") is True:
        return "blocked=true"
    return ""


def _reason_from_trajectory_event(event: TrajectoryEvent) -> str:
    if event.ok is False:
        return "trajectory event failed"
    return ""


def _compact_data(data: dict[str, Any]) -> dict[str, Any]:
    allowed: dict[str, Any] = {}
    for key in (
        "failure_class",
        "error_kind",
        "blocked",
        "approval_id",
        "approval_required",
        "approval_status",
        "policy",
        "tool",
        "command",
        "files",
    ):
        if key in data:
            allowed[key] = data[key]
    if "policy" in allowed and isinstance(allowed["policy"], dict):
        policy = allowed["policy"]
        allowed["policy"] = {
            key: policy[key]
            for key in ("action", "allowed", "approval_required", "approval_status", "reason", "summary")
            if key in policy
        }
    return allowed


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = str(value).strip()
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _preview(text: str, max_chars: int) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max(0, max_chars - 1)].rstrip() + "…"


def _bounded_output(stdout: str | bytes | None, stderr: str | bytes | None, *, max_chars: int = 8000) -> str:
    stdout_text = _decode_process_text(stdout)
    stderr_text = _decode_process_text(stderr)
    return _preview(f"stdout:\n{stdout_text}\nstderr:\n{stderr_text}", max_chars)


def _decode_process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def dumps_agent_autopsy_json(report: AgentAutopsyReport) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)


def write_agent_autopsy(report: AgentAutopsyReport, path: str | Path) -> Path:
    target = Path(path).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_agent_autopsy(report), encoding="utf-8")
    return target
