from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .agent_loop_v3 import AgentV3Result, run_agent_loop_v3
from .answer_guard import AnswerGuardVerdict, guard_answer
from .evidence_ledger import EvidenceRecord, load_evidence, record_evidence
from .mode_router import ModeRoute, route_agent_mode


@dataclass(frozen=True)
class HeadlessRunRequest:
    task: str
    mode: str = ""
    goal: str = ""
    changed_paths: tuple[str, ...] = ()
    include_validation: bool = True
    strict_approval: bool = False
    input_provenance: str = "headless_sdk"
    max_duration_seconds: float | None = None
    max_steps: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["changed_paths"] = list(self.changed_paths)
        return payload


@dataclass(frozen=True)
class HeadlessRunResult:
    request: HeadlessRunRequest
    route: ModeRoute
    agent: AgentV3Result
    answer_guard: AnswerGuardVerdict
    evidence: tuple[EvidenceRecord, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.agent.ok and self.answer_guard.ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request.to_dict(),
            "route": self.route.to_dict(),
            "agent": self.agent.to_dict(),
            "answer_guard": self.answer_guard.to_dict(),
            "evidence": [record.to_dict() for record in self.evidence],
            "ok": self.ok,
        }


class QuantAgentHeadless:
    def __init__(self, project: str | Path):
        self.project = Path(project).expanduser().resolve(strict=False)

    def route(self, task: str, *, mode: str = "", goal: str = "", changed_paths: Iterable[str | Path] = ()) -> ModeRoute:
        return route_agent_mode(self.project, task, explicit_mode=mode, changed_paths=tuple(str(path) for path in changed_paths), input_provenance="headless_sdk")

    def run(
        self,
        task: str,
        *,
        mode: str = "",
        goal: str = "",
        changed_paths: Iterable[str | Path] = (),
        include_validation: bool = True,
        strict_approval: bool = False,
        max_duration_seconds: float | None = None,
        max_steps: int | None = None,
    ) -> HeadlessRunResult:
        request = HeadlessRunRequest(
            task=task,
            mode=mode,
            goal=goal,
            changed_paths=tuple(str(path) for path in changed_paths),
            include_validation=include_validation,
            strict_approval=strict_approval,
            max_duration_seconds=max_duration_seconds,
            max_steps=max_steps,
        )
        route = self.route(task, mode=mode, goal=goal, changed_paths=changed_paths)
        agent = run_agent_loop_v3(
            self.project,
            task,
            explicit_mode=mode,
            include_validation=include_validation,
            strict_approval=strict_approval,
            goal=goal,
            changed_paths=changed_paths,
            input_provenance="headless_sdk",
            max_duration_seconds=max_duration_seconds,
            max_steps=max_steps,
        )
        evidence = tuple(load_evidence(self.project, limit=80))
        answer_guard = guard_answer(self.project, agent.summary, goal=goal, task=task, evidence=evidence)
        return HeadlessRunResult(request, route, agent, answer_guard, evidence)

    def record_evidence(self, **kwargs: Any) -> EvidenceRecord:
        return record_evidence(self.project, **kwargs)

    def guard_answer(self, answer: str, *, goal: str = "", task: str = "") -> AnswerGuardVerdict:
        return guard_answer(self.project, answer, goal=goal, task=task)


def run_headless(project: str | Path, task: str, **kwargs: Any) -> HeadlessRunResult:
    return QuantAgentHeadless(project).run(task, **kwargs)


def render_headless_result(result: HeadlessRunResult) -> str:
    lines = [
        "# Mako Headless Run",
        "",
        f"- ok: {str(result.ok).lower()}",
        f"- mode: {result.route.mode}",
        f"- confidence: {result.route.confidence:.2f}",
        f"- answer_guard: {result.answer_guard.action}",
        f"- evidence: {len(result.evidence)}",
        "",
        "## Summary",
        "",
        result.agent.summary,
    ]
    return "\n".join(lines).rstrip() + "\n"


def render_headless_json(result: HeadlessRunResult) -> str:
    return json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
