from __future__ import annotations

from .exception_audit import audit_suppressed_exception
import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Iterable

from .hook_events import QueryEvent
from .memory_extract import MemoryCandidate, extract_memory_candidates, extract_from_tool_loop
from .memory_sidecar import MemoryProposal, propose_memory_candidates
from .query_runtime import load_query_events


@dataclass(frozen=True)
class HermesLearningReport:
    query_id: str
    source: str
    event_count: int
    candidate_count: int
    proposal_count: int
    proposals: tuple[MemoryProposal, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "source": self.source,
            "event_count": self.event_count,
            "candidate_count": self.candidate_count,
            "proposal_count": self.proposal_count,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
        }


def learn_from_query_events(
    project: str | Path,
    *,
    query_id: str | None = None,
    limit: int = 200,
    min_confidence: float = 0.75,
) -> HermesLearningReport:
    project_path = Path(project).expanduser().resolve(strict=False)
    events = _select_query_events(load_query_events(project_path), query_id=query_id, limit=limit)
    resolved_query_id = _query_id(events, query_id)
    source = f"hermes_learning:{resolved_query_id or 'runtime'}"
    payload = _payload_from_events(events)
    candidates = _dedupe_candidates(extract_memory_candidates(payload, source=source))
    proposals = propose_memory_candidates(project_path, candidates, min_confidence=min_confidence)
    return HermesLearningReport(
        query_id=resolved_query_id,
        source=source,
        event_count=len(events),
        candidate_count=len(candidates),
        proposal_count=len(proposals),
        proposals=tuple(proposals),
    )


def learn_from_agent_payload(
    project: str | Path,
    *,
    task: str,
    summary: str,
    observations: Iterable[Any],
    query_id: str = "",
    ok: bool = True,
    failure_class: str = "",
    trajectory_path: str = "",
    min_confidence: float = 0.75,
) -> HermesLearningReport:
    source = f"hermes_learning:{query_id or 'agent'}"
    payload = {
        "task": task,
        "stage": "agent_learning_sidecar",
        "summary": _terminal_summary(summary, ok=ok, failure_class=failure_class),
        "trajectory_path": trajectory_path,
        "tool_results": [_tool_result_payload(item) for item in observations],
    }
    candidates = _dedupe_candidates(extract_from_tool_loop(payload, source=source))
    candidates.extend(_synthetic_candidates(payload, source=source))
    candidates = _dedupe_candidates(candidates)
    proposals = propose_memory_candidates(project, candidates, min_confidence=min_confidence)
    return HermesLearningReport(
        query_id=query_id,
        source=source,
        event_count=0,
        candidate_count=len(candidates),
        proposal_count=len(proposals),
        proposals=tuple(proposals),
    )


def render_hermes_learning_report(report: HermesLearningReport) -> str:
    lines = [
        "# Hermes Learning",
        "",
        f"- query_id: {report.query_id or '(latest)'}",
        f"- source: {report.source}",
        f"- events: {report.event_count}",
        f"- candidates: {report.candidate_count}",
        f"- new proposals: {report.proposal_count}",
    ]
    if report.proposals:
        lines.extend(["", "## Proposals", ""])
        for proposal in report.proposals:
            text = proposal.text.replace("\n", " ")
            if len(text) > 220:
                text = text[:217] + "..."
            lines.append(f"- {proposal.proposal_id} [{proposal.kind}] confidence={proposal.confidence:.2f}: {text}")
    return "\n".join(lines) + "\n"


def _select_query_events(events: list[QueryEvent], *, query_id: str | None, limit: int) -> list[QueryEvent]:
    if query_id:
        selected = [event for event in events if event.query_id == query_id]
        return selected[-max(1, limit) :]
    latest_id = ""
    for event in reversed(events):
        if event.query_id:
            latest_id = event.query_id
            break
    if latest_id:
        selected = [event for event in events if event.query_id == latest_id]
        return selected[-max(1, limit) :]
    return events[-max(1, limit) :]


def _query_id(events: list[QueryEvent], fallback: str | None) -> str:
    for event in reversed(events):
        if event.query_id:
            return event.query_id
    return fallback or ""


def _payload_from_events(events: list[QueryEvent]) -> dict[str, Any]:
    task = ""
    mode = ""
    terminal: QueryEvent | None = None
    tool_results: list[dict[str, Any]] = []
    for event in events:
        if event.kind == "query_start":
            task = str(event.data.get("task") or task)
            mode = str(event.data.get("mode") or mode)
        elif event.kind == "post_tool":
            tool_results.append(
                {
                    "name": event.name,
                    "ok": event.ok,
                    "summary": event.summary,
                    "data": event.data,
                }
            )
        elif event.kind in {"stop", "stop_failure"}:
            terminal = event
    summary = terminal.summary if terminal else "\n".join(event.summary for event in events[-5:])
    failure_class = str((terminal.data if terminal else {}).get("failure_class") or "")
    return {
        "task": task,
        "stage": "query_runtime_learning",
        "mode": mode,
        "summary": _terminal_summary(summary, ok=terminal.ok if terminal else True, failure_class=failure_class),
        "tool_results": tool_results,
    }


def _terminal_summary(summary: str, *, ok: bool | None, failure_class: str) -> str:
    status = "passed" if ok is True else "failed" if ok is False else "unknown"
    if ok is False and failure_class:
        return f"Blocker: Hermes learning observed {status} agent run with failure_class={failure_class}. {summary}"
    return f"Hermes learning observed {status} agent run. {summary}"


def _tool_result_payload(item: Any) -> dict[str, Any]:
    data = _to_mapping(item)
    return {
        "name": str(data.get("name") or data.get("tool") or ""),
        "ok": data.get("ok"),
        "summary": str(data.get("summary") or ""),
        "data": _json_safe(data.get("data") or {}),
    }


def _synthetic_candidates(payload: dict[str, Any], *, source: str) -> list[MemoryCandidate]:
    candidates: list[MemoryCandidate] = []
    task = str(payload.get("task") or "").strip()
    summary = str(payload.get("summary") or "").strip()
    trajectory_path = str(payload.get("trajectory_path") or "").strip()
    if task and _looks_learnable(task):
        candidates.append(MemoryCandidate("workflow_lesson", f"Hermes workflow lesson: task={task}; outcome={summary[:260]}", source, 0.8))
    if trajectory_path:
        candidates.append(MemoryCandidate("path", f"Path reference: {trajectory_path}", source, 0.82))
    for tool in payload.get("tool_results") or []:
        if not isinstance(tool, dict):
            continue
        if tool.get("ok") is False:
            name = str(tool.get("name") or "tool")
            text = str(tool.get("summary") or "")
            candidates.append(MemoryCandidate("blocker", f"Blocker: {name} failed during agent run: {text}", source, 0.84))
    return candidates


def _looks_learnable(text: str) -> bool:
    lowered = text.lower()
    needles = (
        "p4",
        "pf",
        "tick",
        "slippage",
        "capacity",
        "evidence",
        "strategy",
        "backtest",
        "subagent",
        "skill",
        "memory",
        "runtime",
        "逐笔",
        "滑点",
        "容量",
        "证据",
        "策略",
        "回测",
        "子agent",
        "技能",
        "记忆",
    )
    return any(needle in lowered or needle in text for needle in needles)


def _dedupe_candidates(candidates: Iterable[MemoryCandidate]) -> list[MemoryCandidate]:
    best: dict[tuple[str, str], MemoryCandidate] = {}
    for candidate in candidates:
        text = " ".join(candidate.text.split())
        if not text:
            continue
        normalized = MemoryCandidate(candidate.kind, text, candidate.source, round(float(candidate.confidence), 3))
        key = (normalized.kind, normalized.text)
        old = best.get(key)
        if old is None or normalized.confidence > old.confidence:
            best[key] = normalized
    return list(best.values())


def _to_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        return asdict(value)
    if hasattr(value, "to_dict"):
        try:
            payload = value.to_dict()
            if isinstance(payload, dict):
                return payload
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:253", exc)
            pass
    return {}


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        return value
    except TypeError:
        return str(value)
