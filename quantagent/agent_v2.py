from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from warnings import warn

from .agent_loop import AgentLoopObservation, AgentLoopStep, run_agent_loop
from .query_runtime import QueryRuntime
from .result_schema import AgentRunResult, ToolResult
from .skills import build_skill_snapshot, persist_skill_snapshot


@dataclass(frozen=True)
class AgentStep:
    name: str
    action: str
    args: dict[str, Any] = field(default_factory=dict)
    required: bool = True


@dataclass(frozen=True)
class AgentV2Observation:
    step: int
    name: str
    action: str
    ok: bool
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


@dataclass(frozen=True)
class AgentV2Result:
    task: str
    ok: bool
    summary: str
    plan: list[AgentStep]
    observations: list[AgentV2Observation]
    failure_class: str = ""
    trajectory_path: str = ""
    query_events_path: str = ""

    def to_agent_result(self) -> AgentRunResult:
        return AgentRunResult(
            task=self.task,
            ok=self.ok,
            stage="agent_v2_compat_agent_loop",
            summary=self.summary,
            tool_results=[
                ToolResult(name=item.name, ok=item.ok, summary=item.summary, data=item.data)
                for item in self.observations
            ],
            created_files=[path for path in (self.trajectory_path, self.query_events_path) if path],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "ok": self.ok,
            "summary": self.summary,
            "failure_class": self.failure_class,
            "trajectory_path": self.trajectory_path,
            "query_events_path": self.query_events_path,
            "plan": [asdict(step) for step in self.plan],
            "observations": [asdict(item) for item in self.observations],
            "compatibility": {
                "deprecated": True,
                "canonical_loop": "quantagent.agent_loop.run_agent_loop",
            },
        }


def _deprecated(name: str) -> None:
    warn(
        f"quantagent.agent_v2.{name} is deprecated; use quantagent.agent_loop.run_agent_loop instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def build_agent_v2_plan(task: str, *, include_validation: bool = True) -> list[AgentStep]:
    _deprecated("build_agent_v2_plan")
    lowered = task.lower()
    plan = [
        AgentStep("context", "tool", {"tool": "context", "args": {"task": task}}),
        AgentStep("audit", "tool", {"tool": "audit", "args": {}}),
    ]
    if include_validation:
        plan.append(AgentStep("validate", "tool", {"tool": "validate", "args": {}}))
    if any(token in lowered for token in ("pf", "slippage", "capacity", "tick", "p4", "1253", "滑点", "容量", "逐笔")):
        plan.append(AgentStep("claim_guard", "tool", {"tool": "safety_claim", "args": {"claim": task}}, required=False))
    if any(token in lowered for token in ("test", "unittest", "pytest", "验证", "自测")):
        plan.append(
            AgentStep(
                "unit_tests",
                "command",
                {"command": ["python3", "-m", "unittest", "discover", "-s", "tests"], "allow_risky": True},
            )
        )
    plan.append(AgentStep("memory_extract", "memory_extract", {}, required=False))
    return plan


def classify_failure(observations: list[AgentV2Observation]) -> str:
    failed = [item for item in observations if not item.ok]
    if not failed:
        return ""
    if any(item.data.get("goal_guard", {}).get("action") == "block" for item in failed):
        return "goal_conflict"
    if any(item.data.get("blocked") or item.data.get("error_kind") == "policy_blocked" for item in failed):
        return "policy_blocked"
    joined = " ".join(item.summary.lower() for item in failed)
    if "diagnostic" in joined or "syntaxerror" in joined:
        return "diagnostic_failed"
    if "validation" in joined or "unittest" in joined or "pytest" in joined or "test" in joined:
        return "verification_failed"
    if "permission" in joined or "blocked" in joined or "denied" in joined or "ask" in joined:
        return "policy_blocked"
    if "read failed" in joined or "not found" in joined or "no such file" in joined or "missing" in joined:
        return "missing_context"
    return "tool_failed"


def render_agent_v2_summary(task: str, observations: list[AgentV2Observation], failure_class: str) -> str:
    ok_count = sum(1 for item in observations if item.ok)
    lines = [
        f"Task: {task} source: user request",
        f"Agent v2 completed via deprecated compatibility wrapper over canonical agent loop: {ok_count}/{len(observations)} steps ok. source: agent_v2.observations",
    ]
    if failure_class:
        lines.append(f"Failure class: {failure_class}")
        for item in [obs for obs in observations if not obs.ok][:5]:
            lines.append(f"- {item.name}: {item.summary}")
    else:
        lines.append("No blocking local observations from the canonical loop.")
    lines.append("Trajectory was recorded by quantagent.agent_loop.run_agent_loop.")
    return "\n".join(lines)


def run_agent_v2(
    project: Path,
    task: str,
    *,
    plan: list[AgentStep] | None = None,
    include_validation: bool = True,
    stop_on_required_failure: bool = False,
    query_runtime: QueryRuntime | None = None,
    agent_profile: str = "project",
    context_path: str = "",
) -> AgentV2Result:
    _deprecated("run_agent_v2")
    project_path = Path(project)
    runtime = query_runtime or QueryRuntime(project_path)
    skill_snapshot = build_skill_snapshot(task, project=project_path)
    persist_skill_snapshot(project_path, skill_snapshot, run_id=runtime.query_id)
    active_plan = plan or build_agent_v2_plan(task, include_validation=include_validation)
    loop_plan = tuple(_to_loop_step(step, agent_profile=agent_profile) for step in active_plan)
    result = run_agent_loop(
        project_path,
        task,
        include_validation=include_validation,
        stop_on_required_failure=stop_on_required_failure,
        input_provenance="agent_v2_compat",
        query_runtime=runtime,
        plan=loop_plan,
        runtime_mode="agent_v2_compat",
        runtime_data={
            "skill_snapshot_id": skill_snapshot.snapshot_id,
            "agent_profile": agent_profile,
            "context_path": context_path,
            "deprecated_wrapper": "quantagent.agent_v2.run_agent_v2",
            "canonical_loop": "quantagent.agent_loop.run_agent_loop",
        },
    )
    observations = [_from_loop_observation(item) for item in result.observations]
    failure_class = result.failure_class or classify_failure(observations)
    summary = render_agent_v2_summary(task, observations, failure_class)
    return AgentV2Result(
        task,
        result.ok,
        summary,
        active_plan,
        observations,
        failure_class,
        result.trajectory_path,
        result.query_events_path,
    )


def _to_loop_step(step: AgentStep, *, agent_profile: str) -> AgentLoopStep:
    if step.action == "tool":
        args = step.args.get("args") if isinstance(step.args.get("args"), dict) else {}
        tool_args = dict(args)
        if step.args.get("profile"):
            tool_args["profile"] = step.args["profile"]
        elif agent_profile:
            tool_args["profile"] = agent_profile
        if step.args.get("enforce_ask"):
            tool_args["enforce_ask"] = step.args["enforce_ask"]
        return AgentLoopStep(
            step.name,
            "tool",
            tool=str(step.args.get("tool") or ""),
            args=tool_args,
            required=step.required,
        )
    if step.action == "command":
        command = step.args.get("command")
        argv = tuple(str(item) for item in command) if isinstance(command, list) else ()
        args = dict(step.args)
        if args.get("allow_risky") and "owner_approved" not in args:
            args["owner_approved"] = True
        return AgentLoopStep(
            step.name,
            "command",
            args=args,
            command=argv,
            required=step.required,
            mode="build" if args.get("allow_risky") else "",
        )
    if step.action == "memory_extract":
        return AgentLoopStep(step.name, "memory_extract", args=dict(step.args), required=step.required)
    return AgentLoopStep(step.name, step.action, args=dict(step.args), required=step.required)


def _from_loop_observation(observation: AgentLoopObservation) -> AgentV2Observation:
    return AgentV2Observation(
        step=observation.step,
        name=observation.name,
        action=observation.kind,
        ok=observation.ok,
        summary=observation.summary,
        data=observation.data,
        timestamp=observation.timestamp,
    )


__all__ = [
    "AgentStep",
    "AgentV2Observation",
    "AgentV2Result",
    "build_agent_v2_plan",
    "classify_failure",
    "render_agent_v2_summary",
    "run_agent_v2",
]
