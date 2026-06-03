"""Agent trajectory guard for detecting problematic agent behavior patterns.

Phase 1: Report-only mode. Guards detect issues but do not block execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .agent_loop_core import AgentLoopStep

from .agent_step_record import AgentTrajectory, StepRecord


@dataclass(frozen=True)
class GuardResult:
    """Result from trajectory guard check.

    Attributes:
        should_stop: Whether the agent should stop (Phase 1: always False for report mode)
        reason: Human-readable explanation of the guard trigger
        evidence: List of supporting evidence (step_ids, file names, etc.)
        severity: Impact level - "low" | "medium" | "high"
        mode: Guard operating mode - "report" | "block"
    """
    should_stop: bool
    reason: str
    evidence: list[str]
    severity: str
    mode: str


def check_trajectory_guard(
    trajectory: AgentTrajectory,
    next_step: AgentLoopStep,
    *,
    guard_mode: str = "report",
) -> GuardResult:
    """Check trajectory for problematic patterns before executing next_step.

    Evaluates four guard rules in priority order:
    1. repeated_failure_patch (high severity)
    2. blind_patch_after_verification_failure (medium severity)
    3. completion_without_verification (medium severity)
    4. duplicate_action_detected (low severity)

    Args:
        trajectory: Complete agent execution history
        next_step: The step about to be executed
        guard_mode: "report" (Phase 1 default) or "block"

    Returns:
        GuardResult with detection status and evidence
    """
    # Rule 1: repeated_failure_patch (highest priority)
    if _is_repeated_failure_patch(trajectory, next_step):
        failed = [s for s in trajectory.failed_steps() if s.action.startswith(("tool:edit", "tool:write"))]
        target_files = get_step_target_files(next_step)
        file_failures: dict[str, list[int]] = {}
        for step in failed:
            for file_path in step.files_touched:
                file_failures.setdefault(file_path, []).append(step.step_id)

        evidence = []
        for file_path in target_files:
            if file_path in file_failures and len(file_failures[file_path]) >= 3:
                step_ids = file_failures[file_path]
                evidence.append(f"file={file_path} failed_steps={step_ids}")

        if not evidence:
            # Fallback: count all failures for this file
            for file_path in target_files:
                if file_path in file_failures:
                    step_ids = file_failures[file_path]
                    evidence.append(f"file={file_path} failed_steps={step_ids}")

        return GuardResult(
            should_stop=guard_mode == "block",
            reason="Same file failed verification 3+ times; consider re-diagnosis instead of repeated patching",
            evidence=evidence,
            severity="high",
            mode=guard_mode,
        )

    # Rule 2: blind_patch_after_verification_failure
    if _is_blind_patch_after_failure(trajectory, next_step):
        failed = trajectory.failed_steps()
        last_failure = failed[-1] if failed else None
        target_files = get_step_target_files(next_step)

        evidence = []
        if last_failure:
            evidence.append(f"last_failure_step={last_failure.step_id}")
            if last_failure.files_touched:
                evidence.append(f"failed_files={list(last_failure.files_touched)}")
        evidence.append(f"next_edit_targets={target_files}")

        return GuardResult(
            should_stop=guard_mode == "block",
            reason="Editing same file after verification failure without diagnosis (read/audit/context)",
            evidence=evidence,
            severity="medium",
            mode=guard_mode,
        )

    # Rule 3: completion_without_verification
    if _is_completion_without_verification(trajectory, next_step):
        modified_files = list(trajectory.files_modified())
        last_edit_steps = [
            s for s in trajectory.steps
            if s.action.startswith(("tool:edit", "tool:write"))
        ]
        last_edit = last_edit_steps[-1] if last_edit_steps else None

        evidence = [f"modified_files_count={len(modified_files)}"]
        if last_edit:
            evidence.append(f"last_edit_step={last_edit.step_id}")
            evidence.append(f"last_edit_files={list(last_edit.files_touched)}")

        return GuardResult(
            should_stop=guard_mode == "block",
            reason="Attempting final_review after code modifications without running validation",
            evidence=evidence,
            severity="medium",
            mode=guard_mode,
        )

    # Rule 4: duplicate_action_detected
    if _is_exact_duplicate_action(trajectory, next_step):
        next_sig = get_step_action_signature(next_step)
        duplicate_steps = [
            s.step_id for s in trajectory.steps
            if s.action_signature() == next_sig
        ]

        evidence = [
            f"action_signature={next_sig}",
            f"previous_steps={duplicate_steps}",
        ]

        return GuardResult(
            should_stop=guard_mode == "block",
            reason="Exact duplicate action detected; may indicate loop or redundant work",
            evidence=evidence,
            severity="low",
            mode=guard_mode,
        )

    # No guard triggered
    return GuardResult(
        should_stop=False,
        reason="No guard rules triggered",
        evidence=[],
        severity="low",
        mode=guard_mode,
    )


def _is_repeated_failure_patch(trajectory: AgentTrajectory, next_step: AgentLoopStep) -> bool:
    """Detect if same file failed verification 3+ times and is being edited again.

    Rule: If a file has failed verification 3 or more times in the trajectory,
    and next_step is attempting to edit/write that file again, trigger the guard.
    """
    # Only trigger for edit/write actions
    if not next_step.kind in ("tool",) or not next_step.tool in ("edit", "write"):
        return False

    target_files = get_step_target_files(next_step)
    if not target_files:
        return False

    # Count failures per file
    failed_edits = [
        s for s in trajectory.failed_steps()
        if s.action.startswith(("tool:edit", "tool:write"))
    ]

    file_failure_count: dict[str, int] = {}
    for step in failed_edits:
        for file_path in step.files_touched:
            file_failure_count[file_path] = file_failure_count.get(file_path, 0) + 1

    # Check if any target file has 3+ failures
    for file_path in target_files:
        if file_failure_count.get(file_path, 0) >= 3:
            return True

    return False


def _is_blind_patch_after_failure(trajectory: AgentTrajectory, next_step: AgentLoopStep) -> bool:
    """Detect editing same file after verification failure without diagnosis.

    Rule: If last step was a failed verification (validate/test) on a file,
    and next_step is editing that same file, check if there were any diagnosis
    steps (read/audit/context) AFTER the failure and BEFORE this edit.
    """
    # Only trigger for edit/write actions
    if not next_step.kind in ("tool",) or not next_step.tool in ("edit", "write"):
        return False

    target_files = get_step_target_files(next_step)
    if not target_files:
        return False

    # Find last failed verification step
    failed = trajectory.failed_steps()
    if not failed:
        return False

    last_failure = failed[-1]

    # Check if last failure was verification-related
    if not any(keyword in last_failure.action.lower() for keyword in ["validate", "test", "verify", "check"]):
        return False

    # Check if last failure touched any of the target files
    failure_files = set(last_failure.files_touched)
    target_files_set = set(target_files)

    if not failure_files.intersection(target_files_set):
        return False

    # Check for diagnosis steps AFTER the failure
    steps_after_failure = trajectory.steps_after(last_failure.step_id)

    # Look for diagnosis actions in steps after failure
    for step in steps_after_failure:
        if is_diagnosis_step(step):
            return False  # Found diagnosis, so NOT a blind patch

    # No diagnosis found between failure and this edit
    return True


def _is_completion_without_verification(trajectory: AgentTrajectory, next_step: AgentLoopStep) -> bool:
    """Detect final_review after code modifications without validation.

    Rule: If next_step is final_review, and there were edit/write actions,
    check if there was a validate step after the last edit.
    """
    # Only trigger for final_review
    if next_step.name != "final_review":
        return False

    # Check if any files were modified
    if not trajectory.files_modified():
        return False

    # Find last edit/write step
    edit_steps = [
        s for s in trajectory.steps
        if s.action.startswith(("tool:edit", "tool:write"))
    ]

    if not edit_steps:
        return False

    last_edit = edit_steps[-1]

    # Check for validation steps after last edit
    steps_after_edit = trajectory.steps_after(last_edit.step_id)

    for step in steps_after_edit:
        if "validate" in step.action.lower() or "test" in step.action.lower():
            return False  # Found validation, so OK

    # No validation found after last edit
    return True


def _is_exact_duplicate_action(trajectory: AgentTrajectory, next_step: AgentLoopStep) -> bool:
    """Detect if exact same action was already executed.

    Rule: Compare action signatures. If next_step's signature matches
    any previous step's signature, it's a duplicate.
    """
    next_signature = get_step_action_signature(next_step)

    for step in trajectory.steps:
        if step.action_signature() == next_signature:
            return True

    return False


def get_step_action_signature(step: AgentLoopStep) -> str:
    """Build action signature from AgentLoopStep fields.

    Format: "kind:name" or "kind:tool:file" if tool and args have file_path

    Examples:
        - "tool:validate"
        - "tool:edit:quantagent/agent_loop_core.py"
        - "command:unittest"
        - "internal:final_review"
    """
    if step.kind == "tool" and step.tool:
        # Check for file_path in args
        file_path = step.args.get("file_path") if step.args else None
        if file_path:
            return f"{step.kind}:{step.tool}:{file_path}"
        return f"{step.kind}:{step.tool}"

    if step.kind == "command" and step.command:
        # Use first command element
        cmd = step.command[0] if step.command else ""
        return f"{step.kind}:{cmd}"

    # Default: kind:name
    return f"{step.kind}:{step.name}"


def get_step_target_files(step: AgentLoopStep) -> list[str]:
    """Extract target files from AgentLoopStep.args if present.

    Checks for:
    - args["file_path"] (single file)
    - args["paths"] (multiple files)

    Returns:
        List of file paths, empty if none found
    """
    if not step.args:
        return []

    files: list[str] = []

    # Check for single file_path
    file_path = step.args.get("file_path")
    if file_path and isinstance(file_path, str):
        files.append(file_path)

    # Check for multiple paths
    paths = step.args.get("paths")
    if paths and isinstance(paths, (list, tuple)):
        files.extend(str(p) for p in paths if p)

    return files


def is_diagnosis_step(step: StepRecord) -> bool:
    """Check if step is a diagnosis action (read/audit/context).

    Diagnosis actions are those that gather information without modifying state:
    - tool:read
    - tool:audit
    - tool:context
    - internal:audit
    """
    return step.action.startswith(("tool:read", "tool:audit", "tool:context", "internal:audit"))
