from __future__ import annotations

from pathlib import Path
from typing import Iterable
from warnings import warn

from .agent_loop import (
    AgentLoopObservation,
    AgentLoopResult,
    AgentLoopStep,
    build_agent_plan,
    classify_agent_failure,
    render_agent_result,
    render_agent_summary,
    run_agent_loop,
)
from .mode_router import ModeRoute
from .query_runtime import QueryRuntime


AgentV3Step = AgentLoopStep
AgentV3Observation = AgentLoopObservation
AgentV3Result = AgentLoopResult


def _deprecated(name: str) -> None:
    warn(
        f"quantagent.agent_loop_v3.{name} is deprecated; import quantagent.agent_loop.{name.replace('_v3', '')} instead.",
        DeprecationWarning,
        stacklevel=3,
    )


def build_agent_v3_plan(
    task: str,
    route: ModeRoute,
    *,
    include_validation: bool = True,
    changed_paths: Iterable[str | Path] = (),
) -> tuple[AgentV3Step, ...]:
    _deprecated("build_agent_v3_plan")
    return build_agent_plan(task, route, include_validation=include_validation, changed_paths=changed_paths)


def run_agent_loop_v3(
    project: str | Path,
    task: str,
    *,
    explicit_mode: str = "",
    include_validation: bool = True,
    stop_on_required_failure: bool = False,
    strict_approval: bool = False,
    goal: str = "",
    goal_guard: bool = True,
    changed_paths: Iterable[str | Path] = (),
    input_provenance: str = "",
    query_runtime: QueryRuntime | None = None,
    max_duration_seconds: float | None = None,
    max_steps: int | None = None,
) -> AgentV3Result:
    _deprecated("run_agent_loop_v3")
    return run_agent_loop(
        project,
        task,
        explicit_mode=explicit_mode,
        include_validation=include_validation,
        stop_on_required_failure=stop_on_required_failure,
        strict_approval=strict_approval,
        goal=goal,
        goal_guard=goal_guard,
        changed_paths=changed_paths,
        input_provenance=input_provenance or "agent_loop_v3_compat",
        query_runtime=query_runtime,
        max_duration_seconds=max_duration_seconds,
        max_steps=max_steps,
    )


def classify_agent_v3_failure(observations: Iterable[AgentV3Observation]) -> str:
    _deprecated("classify_agent_v3_failure")
    return classify_agent_failure(observations)


def render_agent_v3_summary(
    task: str,
    route: ModeRoute,
    final_mode: str,
    observations: Iterable[AgentV3Observation],
    failure_class: str,
) -> str:
    _deprecated("render_agent_v3_summary")
    return render_agent_summary(task, route, final_mode, observations, failure_class)


def render_agent_v3_result(result: AgentV3Result) -> str:
    _deprecated("render_agent_v3_result")
    return render_agent_result(result)


__all__ = [
    "AgentV3Observation",
    "AgentV3Result",
    "AgentV3Step",
    "build_agent_v3_plan",
    "classify_agent_v3_failure",
    "render_agent_v3_result",
    "render_agent_v3_summary",
    "run_agent_loop_v3",
]
