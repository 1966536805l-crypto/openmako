from __future__ import annotations

import difflib
import json
import math
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .agent_context_runtime import AgentRuntimeContext, build_agent_runtime_context, context_prompt_fragment
from .agent_step_record import AgentTrajectory, create_step_record
from .agent_trajectory_guard import check_trajectory_guard
from .answer_guard import guard_answer
from .better_option import apply_better_option_prefix, suggest_better_option
from .checkpoints import load_checkpoint
from .evidence_ledger import EvidenceRecord, append_evidence, create_evidence_record, evidence_from_tool_result
from .exception_audit import audit_suppressed_exception
from .goal_contract import BLOCK, GoalGuardDecision, evaluate_goal_guard
from .hermes_learning import learn_from_agent_payload
from .lifecycle_hooks import run_lifecycle_hook
from .memory_extract import add_candidates_to_store, extract_from_tool_loop
from .mode_router import ModeRoute, route_agent_mode
from .quant_auto_evidence import run_quant_auto_evidence
from .quant_priority import build_quant_priority_review, is_quant_task, render_quant_priority_review
from .quant_run_gate import QuantRunSpec, build_quant_run_verdict, latest_quant_evidence_bundle, render_quant_verdict, requires_quant_run_gate, run_quant_gate
from .query_runtime import QueryRuntime
from .result_schema import AgentRunResult, ToolResult
from .tool_call_transcript import ToolCallTrace, trace_from_execution
from .tool_execution import ToolExecutionResult, execute_command_step, execute_tool
from .trajectory import record_action, record_observation, record_step


@dataclass(frozen=True)
class AgentLoopStep:
    name: str
    kind: str
    tool: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    command: tuple[str, ...] = ()
    required: bool = True
    mode: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["command"] = list(self.command)
        return payload


@dataclass(frozen=True)
class AgentLoopObservation:
    step: int
    name: str
    kind: str
    ok: bool
    summary: str
    mode: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["data"] = _sanitize_for_json(payload.get("data", {}))
        return payload


@dataclass(frozen=True)
class AgentLoopResult:
    task: str
    ok: bool
    summary: str
    route: ModeRoute
    final_mode: str
    plan: tuple[AgentLoopStep, ...]
    observations: tuple[AgentLoopObservation, ...]
    runtime_context: AgentRuntimeContext
    failure_class: str = ""
    status: str = ""
    trajectory_path: str = ""
    query_events_path: str = ""
    patch_artifact_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        status = self.status or _derive_agent_status(self.ok, self.failure_class)
        return {
            "task": self.task,
            "ok": self.ok,
            "status": status,
            "summary": self.summary,
            "route": self.route.to_dict(),
            "final_mode": self.final_mode,
            "failure_class": self.failure_class,
            "plan": [step.to_dict() for step in self.plan],
            "observations": [item.to_dict() for item in self.observations],
            "runtime_context": self.runtime_context.to_dict(),
            "trajectory_path": self.trajectory_path,
            "query_events_path": self.query_events_path,
            "patch_artifact_path": self.patch_artifact_path,
        }

    def to_agent_result(self) -> AgentRunResult:
        return AgentRunResult(
            task=self.task,
            ok=self.ok,
            stage="agent_loop_auto_mode_context",
            summary=self.summary,
            tool_results=[
                ToolResult(name=item.name, ok=item.ok, summary=item.summary, data=_sanitize_for_json(item.data))
                for item in self.observations
            ],
            created_files=[path for path in (self.trajectory_path, self.query_events_path, self.patch_artifact_path) if path],
        )


def build_agent_plan(
    task: str,
    route: ModeRoute,
    *,
    include_validation: bool = True,
    changed_paths: Iterable[str | Path] = (),
) -> tuple[AgentLoopStep, ...]:
    mode = route.mode
    lowered = task.lower()
    paths = tuple(str(path) for path in changed_paths)
    steps: list[AgentLoopStep] = [
        AgentLoopStep("route", "internal", required=True, mode=mode),
        AgentLoopStep("goal_guard", "internal", required=True, mode=mode),
    ]
    if is_quant_task(task):
        steps.append(AgentLoopStep("quant_evidence_gate", "internal", required=True, mode=mode))
        steps.append(AgentLoopStep("quant_run_gate", "internal", required=True, mode=mode))
    steps.extend(
        [
        AgentLoopStep("runtime_context", "internal", required=True, mode=mode),
        AgentLoopStep("status", "tool", tool="status", args={}, required=False, mode=mode),
        AgentLoopStep("context", "tool", tool="context", args={"task": task}, required=True, mode=mode),
        ]
    )
    if mode in {"build", "repair", "review"} or is_quant_task(task):
        steps.append(AgentLoopStep("audit", "tool", tool="audit", args={}, required=False, mode=mode))
    if mode in {"build", "repair"}:
        steps.append(AgentLoopStep("implement", "tool", tool="implement", args={"task": task}, required=_requires_implementation(task), mode=mode))
    if mode in {"build", "repair"} and include_validation:
        steps.append(AgentLoopStep("validate", "tool", tool="validate", args={}, required=False, mode=mode))
    if mode == "review":
        steps.append(AgentLoopStep("review_context", "internal", required=True, mode=mode))
    if mode == "repair":
        steps.append(AgentLoopStep("repair_context", "internal", required=True, mode=mode))
    if _wants_unit_tests(lowered) and include_validation:
        steps.append(
            AgentLoopStep(
                "unit_tests",
                "command",
                command=("python3", "-m", "unittest", "discover", "-s", "tests"),
                args={"timeout": 180, "allow_risky": True},
                required=False,
                mode=mode,
            )
        )
    if mode == "admin":
        steps.append(AgentLoopStep("admin_runtime_context", "internal", required=True, mode=mode))
    if paths:
        steps.append(AgentLoopStep("changed_path_context", "internal", args={"paths": list(paths)}, required=True, mode=mode))
    steps.append(AgentLoopStep("final_review", "internal", required=True, mode=mode))
    return tuple(steps)


def _infer_phase(step_kind: str) -> str:
    """Infer execution phase from step kind.

    Args:
        step_kind: Step kind from AgentLoopStep

    Returns:
        Phase string: "plan" | "execute" | "verify" | "reflect"
    """
    if step_kind == "internal":
        return "plan"
    elif step_kind == "tool":
        return "execute"
    elif step_kind == "command":
        return "verify"
    return "execute"


def _extract_files_from_observation(observation: AgentLoopObservation) -> tuple[str, ...]:
    """Extract files from observation data, never from text parsing.

    Only extracts from explicit data fields:
    - observation.data["file_path"]
    - observation.data["paths"]
    - observation.data["changed_files"]

    Args:
        observation: Agent loop observation

    Returns:
        Tuple of file paths
    """
    files = []
    if "file_path" in observation.data:
        files.append(str(observation.data["file_path"]))
    if "paths" in observation.data:
        paths = observation.data["paths"]
        if isinstance(paths, (list, tuple)):
            files.extend(str(p) for p in paths)
    if "changed_files" in observation.data:
        changed = observation.data["changed_files"]
        if isinstance(changed, (list, tuple)):
            files.extend(str(f) for f in changed)
    if "files_touched" in observation.data:
        touched = observation.data["files_touched"]
        if isinstance(touched, (list, tuple)):
            files.extend(str(f) for f in touched)
    if "created_files" in observation.data:
        created = observation.data["created_files"]
        if isinstance(created, (list, tuple)):
            files.extend(str(f) for f in created)
    return tuple(files)


def _sanitize_for_json(obj: Any) -> Any:
    """Recursively convert Path objects to strings for JSON serialization.

    Args:
        obj: Object to sanitize (dict, list, Path, or primitive)

    Returns:
        JSON-safe version of obj with all Path objects converted to str
    """
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {key: _sanitize_for_json(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(item) for item in obj]
    return obj


def _extract_verification_result(observation: AgentLoopObservation) -> str:
    """Extract verification result from observation.

    Args:
        observation: Agent loop observation

    Returns:
        Verification result: "passed" | "failed" | "skipped" | "not_run"
    """
    if observation.name in ("validate", "unit_tests", "audit"):
        return "passed" if observation.ok else "failed"
    if observation.name == "final_review":
        return "skipped"
    return "not_run"


def _mutation_files_from_observation(observation: AgentLoopObservation) -> tuple[str, ...]:
    return tuple(sorted(set(_extract_files_from_observation(observation))))


def _missing_post_edit_verification(observations: list[AgentLoopObservation], mode: str) -> AgentLoopObservation | None:
    if mode not in {"build", "repair"}:
        return None
    touched: list[str] = []
    last_mutation_index = -1
    for index, observation in enumerate(observations):
        files = _mutation_files_from_observation(observation) if observation.ok else ()
        if not files:
            continue
        last_mutation_index = index
        touched.extend(files)
    if last_mutation_index < 0:
        return None
    verified = any(_satisfies_post_edit_verification(observation) for observation in observations[last_mutation_index + 1 :])
    if verified:
        return None
    files_touched = sorted(set(touched))
    return AgentLoopObservation(
        len(observations) + 1,
        "verification_required",
        "internal",
        False,
        "post-edit verification missing after file changes",
        mode,
        {
            "files_touched": files_touched,
            "required_verification": ["validate", "unit_tests"],
        },
    )


def _satisfies_post_edit_verification(observation: AgentLoopObservation) -> bool:
    if observation.name == "unit_tests":
        return observation.ok
    if observation.name != "validate" or not observation.ok:
        return False
    results = observation.data.get("results")
    if not isinstance(results, list):
        return True
    return any(isinstance(item, dict) and item.get("status") != "skip" for item in results)


def _augment_plan_with_subject_tests(
    project: Path,
    plan: tuple[AgentLoopStep, ...],
    mode: str,
    *,
    include_validation: bool,
) -> tuple[AgentLoopStep, ...]:
    if not include_validation or mode not in {"build", "repair"}:
        return plan
    node_step = _node_unit_test_step(project, mode)
    if node_step is not None:
        if any(step.name == "unit_tests" for step in plan):
            return tuple(node_step if _is_default_python_unit_test_step(step) else step for step in plan)
        if plan and plan[-1].name == "final_review":
            return (*plan[:-1], node_step, plan[-1])
        return (*plan, node_step)
    if any(step.name == "unit_tests" for step in plan):
        return plan
    if not (project / "test_subject.py").exists():
        return plan
    unit_step = AgentLoopStep(
        "unit_tests",
        "command",
        command=("python3", "-m", "unittest", "-q", "test_subject"),
        args={"timeout": 180, "allow_risky": True},
        required=True,
        mode=mode,
    )
    if plan and plan[-1].name == "final_review":
        return (*plan[:-1], unit_step, plan[-1])
    return (*plan, unit_step)


def _node_unit_test_step(project: Path, mode: str) -> AgentLoopStep | None:
    tests = tuple(sorted(path.relative_to(project).as_posix() for path in project.glob("tests/test_*.mjs") if path.is_file()))
    if not tests:
        return None
    return AgentLoopStep(
        "unit_tests",
        "command",
        command=("node", "--test", *tests),
        args={"timeout": 180, "allow_risky": True},
        required=False,
        mode=mode,
    )


def _is_default_python_unit_test_step(step: AgentLoopStep) -> bool:
    return (
        step.name == "unit_tests"
        and step.kind == "command"
        and step.command == ("python3", "-m", "unittest", "discover", "-s", "tests")
    )


def _normalize_max_duration_seconds(value: float | None) -> float | None:
    if value is None:
        return None
    duration = float(value)
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("max_duration_seconds must be a finite non-negative number")
    return duration


def _normalize_max_steps(value: int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("max_steps must be a non-negative integer")
    if value < 0:
        raise ValueError("max_steps must be a non-negative integer")
    return value


def _log_guard_violation(
    step_id: int,
    violation_type: str,
    evidence: list[str],
    severity: str,
) -> None:
    """Log guard violation without affecting execution.

    Uses "violation_detected" terminology, NOT "stopped".

    Args:
        step_id: Step identifier where violation detected
        violation_type: Type of violation (e.g., "repeated_failure_patch")
        evidence: List of evidence strings
        severity: Severity level ("low" | "medium" | "high")
    """
    import logging
    logger = logging.getLogger(__name__)

    evidence_str = "; ".join(evidence)
    logger.warning(
        f"Guard violation_detected (report-only) at step {step_id}: "
        f"{violation_type} [severity={severity}] - {evidence_str}"
    )


def run_agent_loop(
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
    plan: Iterable[AgentLoopStep] | None = None,
    runtime_mode: str = "agent_loop",
    runtime_data: dict[str, Any] | None = None,
    max_duration_seconds: float | None = None,
    max_steps: int | None = None,
    learning_context: str = "auto",
    learning_project: str | Path | None = None,
) -> AgentLoopResult:
    project_path = Path(project).expanduser().resolve(strict=False)
    max_duration = _normalize_max_duration_seconds(max_duration_seconds)
    max_step_count = _normalize_max_steps(max_steps)
    learning_context_mode = _normalize_learning_context_mode(learning_context)
    learning_project_path = _normalize_learning_project(learning_project)
    paths = tuple(_normalize_path(path) for path in changed_paths if str(path).strip())
    route = route_agent_mode(project_path, task, explicit_mode=explicit_mode, changed_paths=paths, input_provenance=input_provenance)
    runtime_context = build_agent_runtime_context(project_path, task, mode_name=route.mode, changed_paths=paths, input_provenance=input_provenance)
    active_plan = tuple(plan) if plan is not None else build_agent_plan(task, route, include_validation=include_validation, changed_paths=paths)
    if plan is None:
        active_plan = _augment_plan_with_subject_tests(
            project_path,
            active_plan,
            route.mode,
            include_validation=include_validation,
        )
    runtime = query_runtime or QueryRuntime(project_path)
    runtime.start(
        task,
        mode=runtime_mode,
        data={
            "mode": route.mode,
            "profile": route.profile,
            "confidence": route.confidence,
            "changed_paths": list(paths),
            **({"max_duration_seconds": max_duration} if max_duration is not None else {}),
            **({"max_steps": max_step_count} if max_step_count is not None else {}),
            "learning_context": learning_context_mode,
            **({"learning_project": str(learning_project_path)} if learning_project_path is not None else {}),
        }
        | dict(runtime_data or {}),
    )
    runtime.user_prompt(task)

    observations: list[AgentLoopObservation] = []
    active_mode = route.mode
    active_route = route
    failure_class = ""
    trajectory = AgentTrajectory()
    started_monotonic = time.monotonic()

    for index, step in enumerate(active_plan, start=1):
        if max_step_count is not None and index > max_step_count:
            limit_observation = AgentLoopObservation(
                index,
                "step_limit",
                "internal",
                False,
                f"agent loop exceeded max_steps={max_step_count} before step {index}",
                active_mode,
                {
                    "max_steps": max_step_count,
                    "next_step": step.name,
                    "planned_steps": len(active_plan),
                    "executed_steps": len(observations),
                },
            )
            observations.append(limit_observation)
            runtime.post_tool(
                limit_observation.name,
                step=limit_observation.step,
                ok=limit_observation.ok,
                summary=limit_observation.summary,
                data=limit_observation.data,
            )
            failure_class = "step_limit"
            break
        if max_duration is not None and time.monotonic() - started_monotonic >= max_duration:
            timeout_observation = AgentLoopObservation(
                index,
                "task_timeout",
                "internal",
                False,
                f"agent loop exceeded max_duration_seconds={max_duration:g} before step {index}",
                active_mode,
                {
                    "max_duration_seconds": max_duration,
                    "elapsed_seconds": round(time.monotonic() - started_monotonic, 6),
                    "next_step": step.name,
                },
            )
            observations.append(timeout_observation)
            runtime.post_tool(
                timeout_observation.name,
                step=timeout_observation.step,
                ok=timeout_observation.ok,
                summary=timeout_observation.summary,
                data=timeout_observation.data,
            )
            failure_class = "timeout"
            break
        step_for_mode = AgentLoopStep(
            step.name,
            step.kind,
            tool=step.tool,
            args=step.args,
            command=step.command,
            required=step.required,
            mode=step.mode or active_mode,
        )
        runtime.pre_tool(step_for_mode.name, step=index, args=step_for_mode.to_dict())

        # Phase 2a: Create initial step record
        step_record = create_step_record(
            step_id=index,
            phase=_infer_phase(step_for_mode.kind),
            action=f"{step_for_mode.kind}:{step_for_mode.name}",
            command_run=step_for_mode.command,
        )
        trajectory.add_step(step_record)

        # Phase 2a: Guard check (report-only, does NOT affect execution)
        guard_result = check_trajectory_guard(
            trajectory, step_for_mode, guard_mode="report"
        )
        if guard_result.should_stop:
            # Log as violation_detected, NOT as stopped
            # This does NOT break the loop
            _log_guard_violation(
                step_id=index,
                violation_type=guard_result.reason,
                evidence=guard_result.evidence,
                severity=guard_result.severity,
            )

        observation = _execute_agent_step(
            project_path,
            task,
            index,
            step_for_mode,
            active_route,
            paths,
            strict_approval=strict_approval,
            query_id=runtime.query_id,
            input_provenance=input_provenance,
            goal=goal,
            goal_guard=goal_guard,
            learning_context=learning_context_mode,
            learning_project=learning_project_path,
        )
        observations.append(observation)
        runtime.post_tool(observation.name, step=index, ok=observation.ok, summary=observation.summary, data=observation.data)

        # Phase 2a: Update step record with execution results
        files_touched = _extract_files_from_observation(observation)
        updated_record = create_step_record(
            step_id=index,
            phase=step_record.phase,
            action=step_record.action,
            observation=observation.summary,
            verification_result=_extract_verification_result(observation),
            status="passed" if observation.ok else "failed",
            files_touched=files_touched,
            command_run=step_record.command_run,
        )
        trajectory.steps[-1] = updated_record

        if not observation.ok and step_for_mode.required:
            failure_class = classify_agent_failure(observations)
            if failure_class == "goal_conflict":
                break
            next_route = route_agent_mode(
                project_path,
                task,
                previous_mode=active_mode,
                failure_class=failure_class,
                changed_paths=paths,
                input_provenance=input_provenance,
            )
            if next_route.mode != active_mode:
                active_mode = next_route.mode
                active_route = next_route
                transition_observation = AgentLoopObservation(
                    len(observations) + 1,
                    "mode_transition",
                    "internal",
                    True,
                    f"mode switched to {active_mode} after {failure_class}",
                    active_mode,
                    {"route": next_route.to_dict(), "failure_class": failure_class},
                )
                observations.append(transition_observation)
                runtime.post_tool(
                    transition_observation.name,
                    step=transition_observation.step,
                    ok=True,
                    summary=transition_observation.summary,
                    data=transition_observation.data,
                )
            if stop_on_required_failure or _is_planner_rejection_observation(observation):
                break

    verification_gap = _missing_post_edit_verification(observations, active_mode)
    if verification_gap is not None:
        observations.append(verification_gap)
        runtime.post_tool(
            verification_gap.name,
            step=verification_gap.step,
            ok=verification_gap.ok,
            summary=verification_gap.summary,
            data=verification_gap.data,
        )
        failure_class = failure_class or "verification_failed"

    failure_class = failure_class or classify_agent_failure(observations)
    hard_stopped = any(item.name in {"task_timeout", "step_limit"} and not item.ok for item in observations)
    ok = (
        verification_gap is None
        and not hard_stopped
        and not any(not item.ok and _is_required_observation(item.name, active_plan) for item in observations)
    )
    evidence = _record_agent_evidence(project_path, task, route, active_mode, observations)
    summary = render_agent_summary(task, route, active_mode, observations, failure_class)
    summary = apply_better_option_prefix(summary, suggest_better_option(task, goal=goal, mode=route.mode))
    status = _derive_agent_status(ok, failure_class)
    pre_finalize_ok = ok
    finalize = run_lifecycle_hook(
        project_path,
        "before_agent_finalize",
        {
            "task": task,
            "ok": ok,
            "status": status,
            "summary": summary,
            "failure_class": failure_class,
            "mode": active_mode,
            "profile": active_mode,
        },
        run_id=runtime.query_id,
        query_id=runtime.query_id,
    )
    if finalize.payload:
        summary = str(finalize.payload.get("summary") or summary)
        failure_class = str(finalize.payload.get("failure_class") or failure_class)
        hook_ok = bool(finalize.payload.get("ok", ok))
        ok = hook_ok if pre_finalize_ok else False
    if finalize.blocked:
        ok = False
        failure_class = failure_class or "hook_blocked"
        summary = "; ".join(finalize.summaries or finalize.errors or ("agent finalize blocked by hook",))
    answer_verdict = guard_answer(project_path, summary, goal=goal, task=task, evidence=evidence)
    if not answer_verdict.ok:
        ok = False
        failure_class = failure_class or "answer_guard_blocked"
        summary = answer_verdict.answer
    else:
        summary = answer_verdict.answer
    status = _derive_agent_status(ok, failure_class)
    runtime.post_tool_batch(ok=ok, count=len(observations))
    runtime.stop(summary, ok=ok, failure_class=failure_class, status=status)
    patch_artifact_path = _write_agent_patch_artifact(project_path, observations)
    trajectory_path = _write_agent_trajectory(
        project_path,
        task,
        route,
        active_mode,
        active_plan,
        observations,
        ok,
        status,
        failure_class,
        patch_artifact_path=str(patch_artifact_path or ""),
    )
    run_lifecycle_hook(
        project_path,
        "after_agent_finalize",
        {
            "task": task,
            "ok": ok,
            "status": status,
            "summary": summary,
            "failure_class": failure_class,
            "mode": active_mode,
            "profile": active_mode,
            "trajectory_path": str(trajectory_path),
            "patch_artifact_path": str(patch_artifact_path or ""),
        },
        run_id=runtime.query_id,
        query_id=runtime.query_id,
    )
    try:
        learn_from_agent_payload(
            project_path,
            task=task,
            summary=summary,
            observations=observations,
            query_id=runtime.query_id,
            ok=ok,
            failure_class=failure_class,
            trajectory_path=str(trajectory_path),
        )
    except Exception as exc:
        audit_suppressed_exception(f"{__name__}:314", exc)
        pass
    return AgentLoopResult(
        task=task,
        ok=ok,
        status=status,
        summary=summary,
        route=route,
        final_mode=active_mode,
        plan=active_plan,
        observations=tuple(observations),
        runtime_context=runtime_context,
        failure_class=failure_class,
        trajectory_path=str(trajectory_path),
        query_events_path=str(runtime.event_path or ""),
        patch_artifact_path=str(patch_artifact_path or ""),
    )


def _derive_agent_status(ok: bool, failure_class: str) -> str:
    if ok:
        return "done"
    normalized = str(failure_class or "").strip().lower()
    if normalized == "approval_required":
        return "needs_approval"
    if normalized in {"goal_conflict", "policy_blocked", "hook_blocked", "answer_guard_blocked"}:
        return "blocked"
    return "failed"


def _normalize_learning_context_mode(value: str) -> str:
    mode = str(value or "auto").strip().lower()
    if mode not in {"auto", "on", "off"}:
        raise ValueError(f"invalid learning_context: {value!r}")
    return mode


def _normalize_learning_project(value: str | Path | None) -> Path | None:
    if value is None or str(value).strip() == "":
        return None
    return Path(value).expanduser().resolve(strict=False)


def classify_agent_failure(observations: Iterable[AgentLoopObservation]) -> str:
    failed = [item for item in observations if not item.ok]
    if not failed:
        return ""
    if any(item.data.get("goal_guard", {}).get("action") == BLOCK for item in failed):
        return "goal_conflict"
    if any(item.data.get("blocked") or item.data.get("error_kind") == "policy_blocked" for item in failed):
        return "policy_blocked"
    joined = " ".join(item.summary.lower() for item in failed)
    if "diagnostic" in joined or "syntaxerror" in joined:
        return "diagnostic_failed"
    if "validation" in joined or "unittest" in joined or "pytest" in joined or "test" in joined:
        return "verification_failed"
    if "permission" in joined or "blocked" in joined or "denied" in joined:
        return "policy_blocked"
    if "not found" in joined or "no such file" in joined or "missing" in joined:
        return "missing_context"
    return "tool_failed"


def render_agent_summary(
    task: str,
    route: ModeRoute,
    final_mode: str,
    observations: Iterable[AgentLoopObservation],
    failure_class: str,
) -> str:
    items = list(observations)
    ok_count = sum(1 for item in items if item.ok)
    lines = [
        f"Task: {task} source: user request",
        f"Agent loop mode route: {route.mode} ({route.confidence:.2f}) -> final {final_mode}.",
        f"Completed: {ok_count}/{len(items)} observations ok. source: agent_loop.observations",
    ]
    if failure_class:
        lines.append(f"Failure class: {failure_class}")
        lines.extend(f"- {item.name}: {item.summary}" for item in items if not item.ok)
    else:
        lines.append("No blocking local observations from the mode-aware loop.")
    lines.append("Runtime context, tool transcripts, and trajectory were recorded for review.")
    return "\n".join(lines)


def render_agent_result(result: AgentLoopResult) -> str:
    lines = [
        "# Agent Loop Result",
        "",
        result.summary,
        "",
        "## Route",
        "",
        f"- mode: {result.route.mode}",
        f"- final_mode: {result.final_mode}",
        f"- status: {result.status or _derive_agent_status(result.ok, result.failure_class)}",
        f"- profile: {result.route.profile}",
        f"- intent: {result.route.intent}",
        f"- confidence: {result.route.confidence:.2f}",
        "",
        "## Observations",
        "",
    ]
    for item in result.observations:
        lines.append(f"- [{ 'ok' if item.ok else 'failed' }] {item.step}. {item.name} mode={item.mode}: {item.summary}")
    lines.extend(["", f"trajectory: {result.trajectory_path}", f"query_events: {result.query_events_path}"])
    return "\n".join(lines) + "\n"


def _execute_agent_step(
    project: Path,
    task: str,
    index: int,
    step: AgentLoopStep,
    route: ModeRoute,
    changed_paths: tuple[str, ...],
    *,
    strict_approval: bool,
    query_id: str,
    input_provenance: str,
    goal: str,
    goal_guard: bool,
    learning_context: str,
    learning_project: Path | None,
) -> AgentLoopObservation:
    if step.kind == "internal":
        return _internal_observation(
            project,
            task,
            index,
            step,
            route,
            changed_paths,
            input_provenance=input_provenance,
            goal=goal,
            goal_guard=goal_guard,
        )
    if step.kind == "tool":
        planner_payload: dict[str, Any] | None = None
        if step.tool == "implement" and "operations" not in step.args:
            step, planner_payload = _step_with_planned_implement_operations(
                project,
                task,
                step,
                learning_context=learning_context,
                learning_project=learning_project,
            )
        profile = str(step.args.get("profile") or step.mode or route.mode)
        enforce_ask = strict_approval or bool(step.args.get("enforce_ask", False))
        context = build_agent_runtime_context(
            project,
            task,
            mode_name=step.mode or route.mode,
            changed_paths=changed_paths,
            input_provenance=input_provenance,
            tool_name=step.tool,
        )
        result = execute_tool(
            project,
            step.tool,
            step.args,
            profile=profile,
            owner_approved=_step_owner_approved(step, strict_approval=strict_approval),
            enforce_ask=enforce_ask,
            query_id=query_id,
        )
        trace = trace_from_execution(result, context=context, args=step.args)
        observation = _observation_from_result(index, step, result, trace, context)
        if planner_payload is not None:
            observation.data["planner"] = planner_payload
        return observation
    if step.kind == "command":
        profile = str(step.args.get("profile") or step.mode or route.mode)
        enforce_ask = strict_approval or bool(step.args.get("enforce_ask", False))
        context = build_agent_runtime_context(
            project,
            task,
            mode_name=step.mode or route.mode,
            changed_paths=changed_paths,
            input_provenance=input_provenance,
            tool_name="shell",
        )
        result = execute_command_step(
            project,
            list(step.command),
            timeout=int(step.args.get("timeout") or 120),
            allow_risky=bool(step.args.get("allow_risky", False)),
            profile=profile,
            owner_approved=_step_owner_approved(step, strict_approval=strict_approval),
            enforce_ask=enforce_ask,
            approval_id=str(step.args.get("approval_id") or "") or None,
            query_id=query_id,
        )
        trace = trace_from_execution(result, context=context, args={"command": list(step.command), **step.args})
        return _observation_from_result(index, step, result, trace, context)
    if step.kind == "memory_extract":
        pseudo_result = AgentRunResult(
            task=task,
            ok=True,
            stage="agent_loop_partial",
            summary="memory extraction checkpoint",
            tool_results=[],
        )
        candidates = extract_from_tool_loop(pseudo_result, source="agent_loop")
        added = add_candidates_to_store(project, candidates)
        return AgentLoopObservation(
            index,
            step.name,
            step.kind,
            True,
            f"stored {len(added)} memory item(s)",
            step.mode or route.mode,
            {"candidates": len(candidates), "stored": len(added)},
        )
    return AgentLoopObservation(index, step.name, step.kind, False, f"unknown agent loop step kind: {step.kind}", step.mode or route.mode)


def _step_owner_approved(step: AgentLoopStep, *, strict_approval: bool) -> bool:
    if bool(step.args.get("owner_approved", False)):
        return True
    if strict_approval:
        return False
    if step.kind == "tool" and step.tool == "implement" and isinstance(step.args.get("operations"), list):
        return True
    if step.kind == "command" and step.name in {"unit_tests"} and bool(step.args.get("allow_risky", False)):
        return True
    return False


def _step_with_planned_implement_operations(
    project: Path,
    task: str,
    step: AgentLoopStep,
    *,
    learning_context: str = "auto",
    learning_project: Path | None = None,
) -> tuple[AgentLoopStep, dict[str, Any]]:
    from .agent_planner import plan_task_to_operations

    planner_result = _sanitize_for_json(
        plan_task_to_operations(
            project,
            task,
            learning_context=learning_context,
            learning_project=learning_project,
        )
    )
    operations = planner_result.get("operations") if planner_result.get("ok") else []
    if not isinstance(operations, list):
        operations = []
    args = {**step.args, "operations": operations}
    return (
        AgentLoopStep(
            step.name,
            step.kind,
            tool=step.tool,
            args=args,
            command=step.command,
            required=step.required,
            mode=step.mode,
        ),
        planner_result,
    )


def _internal_observation(
    project: Path,
    task: str,
    index: int,
    step: AgentLoopStep,
    route: ModeRoute,
    changed_paths: tuple[str, ...],
    *,
    input_provenance: str,
    goal: str,
    goal_guard: bool,
) -> AgentLoopObservation:
    goal_decision: GoalGuardDecision | None = None
    if step.name == "goal_guard":
        goal_decision = evaluate_goal_guard(project, task, goal=goal, task=task) if goal_guard else None
        if goal_decision is not None and goal_decision.action == BLOCK:
            return AgentLoopObservation(
                index,
                step.name,
                step.kind,
                False,
                goal_decision.reason,
                step.mode or route.mode,
                {"goal_guard": goal_decision.to_dict()},
            )
    if step.name == "quant_evidence_gate":
        review = build_quant_priority_review(project, task)
        return AgentLoopObservation(
            index,
            step.name,
            step.kind,
            review.ok,
            f"quant priority {review.action}; missing_evidence={len(review.missing_evidence)}",
            step.mode or route.mode,
            {
                "quant_priority": review.to_dict(),
                "rendered": render_quant_priority_review(review),
            },
        )
    if step.name == "quant_run_gate":
        needs_gate = requires_quant_run_gate(task)
        bundle = latest_quant_evidence_bundle(project)
        auto_run: dict[str, Any] = {}
        if bundle is None and needs_gate:
            try:
                auto = run_quant_auto_evidence(project, task, max_files=1000)
                run_payload = auto.quant_run
                bundle = latest_quant_evidence_bundle(project)
                auto_run = {
                    "triggered": bool(auto.position_path),
                    "input_path": auto.position_path,
                    "gate_id": str(run_payload.get("gate_id") or ""),
                    "ok": auto.ok,
                    "auto_id": auto.auto_id,
                    "research_ready": auto.research_ready,
                    "live_ready": auto.live_ready,
                    "data_samples": len(auto.data_samples),
                    "execution_evidence": dict(auto.execution_evidence),
                    "output_json": auto.output_json,
                }
                if not auto.position_path:
                    auto_run["reason"] = "; ".join(auto.warnings) or "no position/backtest CSV candidate found"
            except (OSError, ValueError) as exc:
                auto_run = {"triggered": True, "ok": False, "error": str(exc)}
        if bundle is None:
            ok = not needs_gate
            summary = "QuantRunGate not required for this quant task" if ok else "QuantRunGate evidence missing for material quant conclusion"
            data: dict[str, Any] = {"requires_quant_run_gate": needs_gate, "latest_gate": None, "auto_run": auto_run}
        else:
            verdict = build_quant_run_verdict(bundle, task=task)
            ok = verdict.ok or not needs_gate
            summary = f"QuantRunGate {verdict.action}; research_ready={verdict.research_ready}; live_ready={verdict.live_ready}"
            data = {
                "requires_quant_run_gate": needs_gate,
                "auto_run": auto_run,
                "evidence_bundle": bundle.to_dict(),
                "quant_run_verdict": verdict.to_dict(),
                "rendered": render_quant_verdict(verdict),
            }
        return AgentLoopObservation(index, step.name, step.kind, ok, summary, step.mode or route.mode, data)
    context = build_agent_runtime_context(
        project,
        task,
        mode_name=step.mode or route.mode,
        changed_paths=changed_paths,
        input_provenance=input_provenance,
    )
    data = {
        "route": route.to_dict(),
        "context": context.to_dict(),
        "prompt_fragment": context_prompt_fragment(context, max_chars=4000),
    }
    if goal_decision is not None:
        data["goal_guard"] = goal_decision.to_dict()
    if step.args:
        data["args"] = step.args
    return AgentLoopObservation(
        index,
        step.name,
        step.kind,
        context.ok,
        _internal_summary(step, context),
        step.mode or route.mode,
        data,
    )


def _internal_summary(step: AgentLoopStep, context: AgentRuntimeContext) -> str:
    if step.name == "route":
        return f"routed to {context.mode} with confidence {context.route.confidence:.2f}"
    if step.name == "goal_guard":
        return "goal guard passed; obey user instruction by default"
    if step.name == "runtime_context":
        return f"{len(context.sections)} runtime context section(s), estimated_tokens={context.estimated_tokens}"
    if step.name == "final_review":
        warnings = sum(1 for section in context.sections if section.status == "warn")
        return f"final context review warnings={warnings}"
    return f"{step.name} context ready for mode {context.mode}"


def _observation_from_result(
    index: int,
    step: AgentLoopStep,
    result: ToolExecutionResult,
    trace: ToolCallTrace,
    context: AgentRuntimeContext,
) -> AgentLoopObservation:
    data = dict(_sanitize_for_json(result.data))
    data.update(
        {
            "tool": result.name,
            "policy": result.policy,
            "blocked": result.blocked,
            "error_kind": result.error_kind,
            "approval_id": result.approval_id,
            "invocation_id": result.invocation_id,
            "duration_ms": result.duration_ms,
            "trace": trace.to_dict(),
            "runtime_context": context.to_dict(),
        }
    )
    return AgentLoopObservation(
        index,
        step.name,
        step.kind,
        result.ok,
        result.summary,
        step.mode,
        data,
    )


def _record_agent_evidence(
    project: Path,
    task: str,
    route: ModeRoute,
    final_mode: str,
    observations: list[AgentLoopObservation],
) -> list[EvidenceRecord]:
    ok_count = sum(1 for item in observations if item.ok)
    total = len(observations)
    records = [
        create_evidence_record(
            claim="agent_loop route confidence",
            value=f"{route.confidence:.2f}",
            evidence_type="agent_runtime",
            source="agent_loop.route",
            tool="agent_loop",
            metadata={"task": task, "mode": route.mode, "final_mode": final_mode},
        ),
        create_evidence_record(
            claim="agent_loop observation count",
            value=f"{ok_count}/{total}",
            evidence_type="agent_runtime",
            source="agent_loop.observations",
            tool="agent_loop",
            metadata={"task": task, "ok_count": ok_count, "total": total},
        ),
    ]
    for observation in observations:
        tool_name = str(observation.data.get("tool") or observation.name)
        records.extend(evidence_from_tool_result(tool_name, observation.summary, observation.data))
    for record in records:
        append_evidence(project, record)
    return records


def _is_required_observation(name: str, plan: tuple[AgentLoopStep, ...]) -> bool:
    return next((step.required for step in plan if step.name == name), False)


def _is_planner_rejection_observation(observation: AgentLoopObservation) -> bool:
    if observation.name != "implement":
        return False
    planner = observation.data.get("planner")
    if not isinstance(planner, dict):
        return False
    return planner.get("ok") is False


def _write_agent_trajectory(
    project: Path,
    task: str,
    route: ModeRoute,
    final_mode: str,
    plan: tuple[AgentLoopStep, ...],
    observations: list[AgentLoopObservation],
    ok: bool,
    status: str,
    failure_class: str,
    patch_artifact_path: str = "",
) -> Path:
    out_dir = project / "AI_协作交接"
    if not out_dir.exists():
        out_dir = project / ".quantagent"
    out_dir.mkdir(parents=True, exist_ok=True)
    event_path = out_dir / f"agent_loop_events_{time.time_ns()}.jsonl"
    record_step(event_path, f"agent-loop task: {task}", step=0, ok=ok, failure_class=failure_class, mode=route.mode, final_mode=final_mode)
    for step in plan:
        record_action(event_path, step.name, step=None, ok=None, action=step.kind, args=step.to_dict(), required=step.required)
    for item in observations:
        record_observation(event_path, item.summary, step=item.step, ok=item.ok, name=item.name, action=item.kind, data=item.data)
    path = out_dir / "agent_loop_trajectory.jsonl"
    entry = {
        "task": task,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "ok": ok,
        "status": status,
        "failure_class": failure_class,
        "mode": route.mode,
        "final_mode": final_mode,
        "route": route.to_dict(),
        "event_trajectory_path": str(event_path),
        "patch_artifact_path": patch_artifact_path,
        "plan": [step.to_dict() for step in plan],
        "observations": [item.to_dict() for item in observations],
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return path


def _write_agent_patch_artifact(project: Path, observations: list[AgentLoopObservation]) -> Path | None:
    before_by_path: dict[str, tuple[bool, str]] = {}
    for observation in observations:
        checkpoint_id = str(observation.data.get("checkpoint_id") or "")
        if not checkpoint_id:
            continue
        try:
            checkpoint = load_checkpoint(project, checkpoint_id)
        except Exception as exc:
            audit_suppressed_exception(f"{__name__}:1068", exc)
            continue
        for snapshot in checkpoint.files:
            before_by_path.setdefault(snapshot.path, (snapshot.existed, snapshot.text))
    if not before_by_path:
        return None

    lines: list[str] = []
    for rel_path, (existed, before_text) in sorted(before_by_path.items()):
        target = (project / rel_path).resolve(strict=False)
        if project.resolve(strict=False) not in target.parents and target != project.resolve(strict=False):
            continue
        current_exists = target.exists()
        current_text = target.read_text(encoding="utf-8", errors="replace") if current_exists else ""
        if existed == current_exists and before_text == current_text:
            continue
        lines.extend(
            difflib.unified_diff(
                before_text.splitlines(),
                current_text.splitlines(),
                fromfile=f"a/{rel_path}" if existed else "/dev/null",
                tofile=f"b/{rel_path}" if current_exists else "/dev/null",
                lineterm="",
            )
        )
    if not lines:
        return None

    out_dir = project / "AI_协作交接"
    if not out_dir.exists():
        out_dir = project / ".quantagent"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "agent_loop_patch.diff"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _wants_unit_tests(lowered_task: str) -> bool:
    return any(token in lowered_task for token in ("test", "unittest", "pytest", "验证", "自测", "测试"))


def _requires_implementation(task: str) -> bool:
    lowered = task.lower()
    english_patterns = (
        r"\bcreate\b",
        r"\bwrite\b",
        r"\bedit\b",
        r"\bfix\b",
        r"\brepair\b",
        r"\bpatch\b",
        r"\bupdate\b",
        r"\bmodify\b",
        r"\bchange\b",
        r"\badd\s+file\b",
        r"\bgenerate\s+file\b",
    )
    if any(re.search(pattern, lowered) for pattern in english_patterns):
        return True
    return any(token in lowered for token in ("新增", "创建", "写入", "修改", "修复", "更新", "改动"))


def _find_quant_run_candidate(project: Path) -> Path | None:
    roots = [project / "AI_协作交接", project]
    seen: set[Path] = set()
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*.csv"):
            if path in seen:
                continue
            seen.add(path)
            lowered = path.name.lower()
            if "position" not in lowered and "dedup" not in lowered and "return" not in lowered:
                continue
            try:
                header = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[0]
            except (OSError, IndexError):
                continue
            if ("entry_date" in header and "net_return" in header) or ("date" in header and "return" in header):
                candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (0 if "dedup" in item.name.lower() else 1, len(item.parts), str(item)))
    return candidates[0]


def _normalize_path(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip().lstrip("./")
