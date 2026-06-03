"""Agent step recording and trajectory tracking.

This module provides data structures for recording agent execution steps
and maintaining a trajectory of agent actions for memory and analysis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class StepRecord:
    """Record of a single agent execution step.

    Captures the decision, action, observation, and verification result
    for one step in the agent loop.

    Attributes:
        step_id: Unique identifier for this step
        phase: Execution phase ("plan" | "execute" | "verify" | "reflect")
        decision_summary: Brief description of the decision made
        action: Action taken, format "kind:name" (e.g., "tool:validate", "command:unittest")
        files_touched: Files explicitly modified by this step (from edit/write actions only)
        command_run: Command executed, if any
        observation: Result or output from the action
        verification_result: Verification status ("passed" | "failed" | "skipped" | "not_run")
        timestamp: ISO format timestamp of step execution
        status: Current step status ("planned" | "running" | "passed" | "failed" | "skipped")
    """

    step_id: int
    phase: str
    decision_summary: str
    action: str
    files_touched: tuple[str, ...]
    command_run: tuple[str, ...]
    observation: str
    verification_result: str
    timestamp: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        """Convert step record to dictionary representation.

        Returns:
            Dictionary with all step record fields
        """
        return {
            "step_id": self.step_id,
            "phase": self.phase,
            "decision_summary": self.decision_summary,
            "action": self.action,
            "files_touched": self.files_touched,
            "command_run": self.command_run,
            "observation": self.observation,
            "verification_result": self.verification_result,
            "timestamp": self.timestamp,
            "status": self.status,
        }

    def action_signature(self) -> str:
        """Generate signature for duplicate detection.

        Format:
        - For file actions: "kind:name:file"
        - For command actions: "kind:name:command"
        - For other actions: "kind:name"

        Returns:
            Action signature string

        Examples:
            "tool:validate"
            "tool:edit:quantagent/agent_loop_core.py"
            "command:unittest:python3"
        """
        if self.files_touched:
            return f"{self.action}:{self.files_touched[0]}"
        if self.command_run:
            return f"{self.action}:{self.command_run[0]}"
        return self.action


class AgentTrajectory:
    """Collection of agent execution steps forming a trajectory.

    Maintains the sequence of steps taken by the agent and provides
    methods for querying and analyzing the trajectory.
    """

    def __init__(self) -> None:
        """Initialize empty trajectory."""
        self.steps: list[StepRecord] = []

    def add_step(self, step: StepRecord) -> None:
        """Add a step to the trajectory.

        Args:
            step: Step record to add
        """
        self.steps.append(step)

    def last_n_steps(self, n: int) -> list[StepRecord]:
        """Get the last n steps from the trajectory.

        Args:
            n: Number of steps to retrieve

        Returns:
            List of up to n most recent steps
        """
        return self.steps[-n:] if n > 0 else []

    def failed_steps(self) -> list[StepRecord]:
        """Get all steps with failed status.

        Returns:
            List of steps where status is "failed"
        """
        return [step for step in self.steps if step.status == "failed"]

    def files_modified(self) -> set[str]:
        """Get set of all files modified across all steps.

        Only includes files from explicit edit/write actions,
        not inferred from observations.

        Returns:
            Set of file paths that were modified
        """
        modified = set()
        for step in self.steps:
            if step.action.startswith(("tool:edit", "tool:write")):
                modified.update(step.files_touched)
        return modified

    def to_dict(self) -> dict[str, Any]:
        """Convert trajectory to dictionary representation.

        Returns:
            Dictionary with steps list and metadata
        """
        return {
            "steps": [step.to_dict() for step in self.steps],
            "total_steps": len(self.steps),
            "failed_count": len(self.failed_steps()),
            "files_modified": sorted(self.files_modified()),
        }

    def find_step_index(self, step_id: int) -> int | None:
        """Find the list index for a given step_id.

        Helper for safe indexing since step_id may not match list position.

        Args:
            step_id: Step identifier to find

        Returns:
            List index if found, None otherwise
        """
        for idx, step in enumerate(self.steps):
            if step.step_id == step_id:
                return idx
        return None

    def steps_after(self, step_id: int) -> list[StepRecord]:
        """Get all steps that occurred after the given step_id.

        Helper for guard rules that need to check subsequent steps.

        Args:
            step_id: Step identifier to search from

        Returns:
            List of steps after the given step_id, empty if not found
        """
        idx = self.find_step_index(step_id)
        if idx is None:
            return []
        return self.steps[idx + 1:]


def create_step_record(
    step_id: int,
    phase: str,
    action: str,
    decision_summary: str = "",
    observation: str = "",
    files_touched: tuple[str, ...] = (),
    command_run: tuple[str, ...] = (),
    verification_result: str = "not_run",
    status: str = "running",
    timestamp: str | None = None,
) -> StepRecord:
    """Factory function to create a StepRecord with sensible defaults.

    Args:
        step_id: Unique step identifier
        phase: Execution phase
        action: Action taken (format "kind:name")
        decision_summary: Brief description of decision (default: empty)
        observation: Result or output (default: empty)
        files_touched: Files modified (default: empty tuple)
        command_run: Command executed (default: empty tuple)
        verification_result: Verification status (default: "not_run")
        status: Step status (default: "running")
        timestamp: ISO timestamp (default: current time)

    Returns:
        New StepRecord instance
    """
    if timestamp is None:
        timestamp = datetime.now().isoformat(timespec="seconds")

    return StepRecord(
        step_id=step_id,
        phase=phase,
        decision_summary=decision_summary,
        action=action,
        files_touched=files_touched,
        command_run=command_run,
        observation=observation,
        verification_result=verification_result,
        timestamp=timestamp,
        status=status,
    )
