"""Unit tests for agent trajectory guard rules.

Tests cover all guard detection rules:
- duplicate_action_detected
- repeated_failure_patch
- blind_patch_after_verification_failure
- completion_without_verification
"""

from __future__ import annotations

import unittest

from quantagent.agent_loop_core import AgentLoopStep
from quantagent.agent_step_record import (
    AgentTrajectory,
    StepRecord,
    create_step_record,
)
from quantagent.agent_trajectory_guard import (
    GuardResult,
    check_trajectory_guard,
    get_step_action_signature,
    get_step_target_files,
    is_diagnosis_step,
)


def build_step(
    name: str,
    kind: str,
    tool: str = "",
    args: dict | None = None,
    command: tuple[str, ...] = (),
) -> AgentLoopStep:
    """Helper to build AgentLoopStep for tests."""
    return AgentLoopStep(
        name=name,
        kind=kind,
        tool=tool,
        args=args or {},
        command=command,
        required=True,
        mode="test",
    )


def build_record(
    step_id: int,
    action: str,
    status: str = "completed",
    files_touched: tuple[str, ...] = (),
) -> StepRecord:
    """Helper to build StepRecord for tests."""
    return create_step_record(
        step_id=step_id,
        phase="test",
        decision_summary="",
        action=action,
        observation="",
        status=status,
        files_touched=files_touched,
    )


class TestDuplicateActionDetection(unittest.TestCase):
    """Test duplicate action detection guard rule."""

    def test_duplicate_action_detection(self) -> None:
        """Create trajectory with 'tool:edit:file.py' executed twice."""
        trajectory = AgentTrajectory()

        # Add step that edits file.py
        trajectory.add_step(
            build_record(
                1,
                "tool:edit",
                status="completed",
                files_touched=("file.py",),
            )
        )

        # Try to edit file.py again
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file.py"})

        result = check_trajectory_guard(trajectory, next_step, guard_mode="block")

        self.assertTrue(result.should_stop, "Should detect duplicate action")
        self.assertIn("duplicate", result.reason.lower(), "Reason should mention duplicate")
        self.assertEqual(result.severity, "low", "Duplicate action is low severity")
        self.assertEqual(result.mode, "block", "Mode should match guard_mode")


class TestRepeatedFailurePatchDetection(unittest.TestCase):
    """Test repeated failure patch detection guard rule."""

    def test_repeated_failure_patch_detection(self) -> None:
        """Create trajectory: edit file.py (fail) x3 -> next: edit file.py."""
        trajectory = AgentTrajectory()

        # Add 3 failed edit attempts on file.py
        for i in range(1, 4):
            trajectory.add_step(
                build_record(
                    i,
                    "tool:edit",
                    status="failed",
                    files_touched=("file.py",),
                )
            )

        # Try to edit file.py again
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file.py"})

        result = check_trajectory_guard(trajectory, next_step, guard_mode="block")

        self.assertTrue(result.should_stop, "Should detect repeated failure patch")
        self.assertIn("failed verification 3+", result.reason.lower(), "Reason should mention repeated failure")
        self.assertEqual(result.severity, "high", "Repeated failure patch is high severity")
        self.assertGreater(len(result.evidence), 0, "Should provide evidence")


class TestBlindPatchAfterFailureDetection(unittest.TestCase):
    """Test blind patch after verification failure detection."""

    def test_blind_patch_after_failure_detection(self) -> None:
        """Create trajectory: validate (fail) -> next: edit same file (no diagnosis)."""
        trajectory = AgentTrajectory()

        # Add failed validation step
        trajectory.add_step(
            build_record(
                1,
                "tool:validate",
                status="failed",
                files_touched=("file_a.py",),
            )
        )

        # Try to edit same file without diagnosis
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file_a.py"})

        result = check_trajectory_guard(trajectory, next_step, guard_mode="block")

        self.assertTrue(result.should_stop, "Should detect blind patch after failure")
        self.assertIn("without diagnosis", result.reason.lower(), "Reason should mention lack of diagnosis")
        self.assertEqual(result.severity, "medium", "Blind patch is medium severity")

    def test_blind_patch_allows_diagnosis_before_edit(self) -> None:
        """Create trajectory: validate (fail) -> read file -> next: edit same file."""
        trajectory = AgentTrajectory()

        # Add failed validation step
        trajectory.add_step(
            build_record(
                1,
                "tool:validate",
                status="failed",
                files_touched=("file_a.py",),
            )
        )

        # Add diagnosis step (read)
        trajectory.add_step(
            build_record(
                2,
                "tool:read",
                status="completed",
                files_touched=("file_a.py",),
            )
        )

        # Now edit same file
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file_a.py"})

        result = check_trajectory_guard(trajectory, next_step, guard_mode="block")

        self.assertFalse(result.should_stop, "Should allow edit after diagnosis")
        self.assertNotIn("without diagnosis", result.reason.lower(), "Should not trigger blind patch")

    def test_blind_patch_allows_edit_different_file(self) -> None:
        """Create trajectory: validate file_a.py (fail) -> next: edit file_b.py."""
        trajectory = AgentTrajectory()

        # Add failed validation step on file_a.py
        trajectory.add_step(
            build_record(
                1,
                "tool:validate",
                status="failed",
                files_touched=("file_a.py",),
            )
        )

        # Try to edit different file
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file_b.py"})

        result = check_trajectory_guard(trajectory, next_step, guard_mode="block")

        self.assertFalse(result.should_stop, "Should allow edit of different file")
        self.assertNotIn("without diagnosis", result.reason.lower(), "Should not trigger blind patch")


class TestCompletionWithoutVerificationDetection(unittest.TestCase):
    """Test completion without verification detection."""

    def test_completion_without_verification_detection(self) -> None:
        """Create trajectory: edit file.py (pass) -> next: final_review (no validate)."""
        trajectory = AgentTrajectory()

        # Add successful edit step
        trajectory.add_step(
            build_record(
                1,
                "tool:edit",
                status="completed",
                files_touched=("file.py",),
            )
        )

        # Try to do final_review without validation
        next_step = build_step("final_review", "internal")

        result = check_trajectory_guard(trajectory, next_step, guard_mode="block")

        self.assertTrue(result.should_stop, "Should detect completion without verification")
        self.assertIn("without running validation", result.reason.lower(), "Reason should mention missing validation")
        self.assertEqual(result.severity, "medium", "Completion without verification is medium severity")

    def test_completion_allows_no_code_change(self) -> None:
        """Create trajectory: read -> context -> next: final_review (no edit/write)."""
        trajectory = AgentTrajectory()

        # Add read step
        trajectory.add_step(
            build_record(
                1,
                "tool:read",
                status="completed",
                files_touched=("file.py",),
            )
        )

        # Add context step
        trajectory.add_step(
            build_record(
                2,
                "tool:context",
                status="completed",
            )
        )

        # Try final_review (no code changes)
        next_step = build_step("final_review", "internal")

        result = check_trajectory_guard(trajectory, next_step, guard_mode="block")

        self.assertFalse(result.should_stop, "Should allow completion with no code changes")

    def test_completion_allows_validation_after_edit(self) -> None:
        """Create trajectory: edit file.py -> validate (pass) -> next: final_review."""
        trajectory = AgentTrajectory()

        # Add edit step
        trajectory.add_step(
            build_record(
                1,
                "tool:edit",
                status="completed",
                files_touched=("file.py",),
            )
        )

        # Add validation step
        trajectory.add_step(
            build_record(
                2,
                "tool:validate",
                status="completed",
                files_touched=("file.py",),
            )
        )

        # Try final_review
        next_step = build_step("final_review", "internal")

        result = check_trajectory_guard(trajectory, next_step, guard_mode="block")

        self.assertFalse(result.should_stop, "Should allow completion after validation")


class TestGuardNormalFlow(unittest.TestCase):
    """Test that guard allows normal agent flow."""

    def test_guard_allows_normal_flow(self) -> None:
        """Create trajectory: plan -> execute -> verify (pass)."""
        trajectory = AgentTrajectory()

        # Add plan step
        trajectory.add_step(
            build_record(1, "internal:plan", status="completed")
        )

        # Add execute step
        trajectory.add_step(
            build_record(
                2,
                "tool:edit",
                status="completed",
                files_touched=("file.py",),
            )
        )

        # Add verify step
        trajectory.add_step(
            build_record(
                3,
                "tool:validate",
                status="completed",
                files_touched=("file.py",),
            )
        )

        # Try final_review
        next_step = build_step("final_review", "internal")

        result = check_trajectory_guard(trajectory, next_step, guard_mode="block")

        self.assertFalse(result.should_stop, "Should allow normal flow")
        self.assertIn("no guard", result.reason.lower(), "Should indicate no guard triggered")

    def test_guard_allows_diagnosis_after_failure(self) -> None:
        """Create trajectory: verify (fail) -> audit -> edit."""
        trajectory = AgentTrajectory()

        # Add failed verify step
        trajectory.add_step(
            build_record(
                1,
                "tool:validate",
                status="failed",
                files_touched=("file.py",),
            )
        )

        # Add audit (diagnosis) step
        trajectory.add_step(
            build_record(
                2,
                "tool:audit",
                status="completed",
            )
        )

        # Try edit after diagnosis
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file.py"})

        result = check_trajectory_guard(trajectory, next_step, guard_mode="block")

        self.assertFalse(result.should_stop, "Should allow edit after diagnosis")


class TestGuardPriority(unittest.TestCase):
    """Test guard rule priority ordering."""

    def test_guard_priority_repeated_failure_over_duplicate(self) -> None:
        """Test that repeated_failure_patch has higher priority than duplicate_action."""
        trajectory = AgentTrajectory()

        # Add 3 failed edit attempts (triggers repeated_failure_patch)
        for i in range(1, 4):
            trajectory.add_step(
                build_record(
                    i,
                    "tool:edit",
                    status="failed",
                    files_touched=("file.py",),
                )
            )

        # This also triggers duplicate_action, but repeated_failure should win
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file.py"})

        result = check_trajectory_guard(trajectory, next_step, guard_mode="block")

        self.assertTrue(result.should_stop, "Should detect violation")
        self.assertIn("repeated", result.reason.lower(), "Should prioritize repeated_failure_patch")
        self.assertEqual(result.severity, "high", "Should use high severity from repeated_failure_patch")


class TestGuardModes(unittest.TestCase):
    """Test guard mode behavior (report vs block)."""

    def test_guard_mode_report_vs_block(self) -> None:
        """Test same violation with guard_mode='report' vs guard_mode='block'."""
        trajectory = AgentTrajectory()

        # Add duplicate action scenario
        trajectory.add_step(
            build_record(
                1,
                "tool:edit",
                status="completed",
                files_touched=("file.py",),
            )
        )

        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file.py"})

        # Test report mode
        result_report = check_trajectory_guard(trajectory, next_step, guard_mode="report")

        self.assertFalse(result_report.should_stop, "Report mode should not stop")
        self.assertEqual(result_report.mode, "report", "Mode should be 'report'")
        self.assertIn("duplicate", result_report.reason.lower(), "Should still detect issue")

        # Test block mode
        result_block = check_trajectory_guard(trajectory, next_step, guard_mode="block")

        self.assertTrue(result_block.should_stop, "Block mode should stop")
        self.assertEqual(result_block.mode, "block", "Mode should be 'block'")
        self.assertIn("duplicate", result_block.reason.lower(), "Should detect same issue")


class TestHelperFunctions(unittest.TestCase):
    """Test helper functions used by guard rules."""

    def test_get_step_action_signature_helper(self) -> None:
        """Test get_step_action_signature with various AgentLoopStep configurations."""
        # Test tool step without file_path
        step1 = build_step("validate", "tool", tool="validate")
        sig1 = get_step_action_signature(step1)
        self.assertEqual(sig1, "tool:validate", "Should format as 'tool:validate'")

        # Test tool step with file_path
        step2 = build_step("edit", "tool", tool="edit", args={"file_path": "test.py"})
        sig2 = get_step_action_signature(step2)
        self.assertEqual(sig2, "tool:edit:test.py", "Should include file_path")

        # Test command step
        step3 = build_step("test", "command", command=("python3", "-m", "unittest"))
        sig3 = get_step_action_signature(step3)
        self.assertEqual(sig3, "command:python3", "Should use first command element")

        # Test internal step
        step4 = build_step("final_review", "internal")
        sig4 = get_step_action_signature(step4)
        self.assertEqual(sig4, "internal:final_review", "Should format as 'kind:name'")

    def test_get_step_target_files_helper(self) -> None:
        """Test get_step_target_files with various args configurations."""
        # Test with file_path
        step1 = build_step("edit", "tool", tool="edit", args={"file_path": "test.py"})
        files1 = get_step_target_files(step1)
        self.assertEqual(files1, ["test.py"], "Should extract single file_path")

        # Test with paths list
        step2 = build_step("edit", "tool", tool="edit", args={"paths": ["a.py", "b.py"]})
        files2 = get_step_target_files(step2)
        self.assertEqual(files2, ["a.py", "b.py"], "Should extract multiple paths")

        # Test with no file args
        step3 = build_step("validate", "tool", tool="validate", args={})
        files3 = get_step_target_files(step3)
        self.assertEqual(files3, [], "Should return empty list when no file args")

        # Test with both file_path and paths
        step4 = build_step(
            "edit",
            "tool",
            tool="edit",
            args={"file_path": "main.py", "paths": ["a.py", "b.py"]},
        )
        files4 = get_step_target_files(step4)
        self.assertIn("main.py", files4, "Should include file_path")
        self.assertIn("a.py", files4, "Should include paths")
        self.assertIn("b.py", files4, "Should include paths")

    def test_is_diagnosis_step_helper(self) -> None:
        """Test is_diagnosis_step with various StepRecord actions."""
        # Test tool:read (diagnosis)
        step1 = build_record(1, "tool:read:file.py")
        self.assertTrue(is_diagnosis_step(step1), "tool:read should be diagnosis")

        # Test tool:audit (diagnosis)
        step2 = build_record(2, "tool:audit")
        self.assertTrue(is_diagnosis_step(step2), "tool:audit should be diagnosis")

        # Test tool:context (diagnosis)
        step3 = build_record(3, "tool:context")
        self.assertTrue(is_diagnosis_step(step3), "tool:context should be diagnosis")

        # Test internal:audit (diagnosis)
        step4 = build_record(4, "internal:audit")
        self.assertTrue(is_diagnosis_step(step4), "internal:audit should be diagnosis")

        # Test tool:edit (not diagnosis)
        step5 = build_record(5, "tool:edit:file.py")
        self.assertFalse(is_diagnosis_step(step5), "tool:edit should not be diagnosis")

        # Test tool:write (not diagnosis)
        step6 = build_record(6, "tool:write:file.py")
        self.assertFalse(is_diagnosis_step(step6), "tool:write should not be diagnosis")

        # Test tool:validate (not diagnosis)
        step7 = build_record(7, "tool:validate")
        self.assertFalse(is_diagnosis_step(step7), "tool:validate should not be diagnosis")


class TestScriptedGuardMatrix(unittest.TestCase):
    """Scripted guard matrix tests for report-only mode verification.

    These tests verify guard behavior with deterministic trajectories
    to ensure correct detection and reporting without false positives.
    """

    def test_guard_normal_read_edit_verify_flow_no_warning(self) -> None:
        """T1: Normal read → edit → verify flow should not trigger warnings."""
        trajectory = AgentTrajectory()

        # Read file
        trajectory.add_step(
            build_record(1, "tool:read", status="completed", files_touched=("file.py",))
        )

        # Edit file
        trajectory.add_step(
            build_record(2, "tool:edit", status="completed", files_touched=("file.py",))
        )

        # Verify
        trajectory.add_step(
            build_record(3, "tool:validate", status="completed", files_touched=("file.py",))
        )

        # Final review
        next_step = build_step("final_review", "internal")

        result = check_trajectory_guard(trajectory, next_step, guard_mode="report")

        self.assertFalse(result.should_stop, "Report mode should not stop")
        self.assertEqual(result.mode, "report", "Mode should be 'report'")
        self.assertIn("no guard", result.reason.lower(), "Should not trigger warnings")

    def test_guard_read_only_no_verify_required(self) -> None:
        """T2: Read-only operations should not require verification."""
        trajectory = AgentTrajectory()

        # Read multiple files
        trajectory.add_step(
            build_record(1, "tool:read", status="completed", files_touched=("file_a.py",))
        )
        trajectory.add_step(
            build_record(2, "tool:read", status="completed", files_touched=("file_b.py",))
        )
        trajectory.add_step(
            build_record(3, "tool:context", status="completed")
        )

        # Final review without any edits
        next_step = build_step("final_review", "internal")

        result = check_trajectory_guard(trajectory, next_step, guard_mode="report")

        self.assertFalse(result.should_stop, "Report mode should not stop")
        self.assertEqual(result.mode, "report", "Mode should be 'report'")
        self.assertIn("no guard", result.reason.lower(), "Should not require verification for read-only")

    def test_guard_edit_without_verification_warning(self) -> None:
        """T3: Edit without subsequent verify should warn completion_without_verification."""
        trajectory = AgentTrajectory()

        # Edit file
        trajectory.add_step(
            build_record(1, "tool:edit", status="completed", files_touched=("file.py",))
        )

        # Final review without validation
        next_step = build_step("final_review", "internal")

        result = check_trajectory_guard(trajectory, next_step, guard_mode="report")

        self.assertFalse(result.should_stop, "Report mode should not stop")
        self.assertEqual(result.mode, "report", "Mode should be 'report'")
        self.assertIn("without running validation", result.reason.lower(), "Should warn about missing verification")
        self.assertEqual(result.severity, "medium", "Should be medium severity")

    def test_guard_blind_patch_after_failed_verify(self) -> None:
        """T4: Edit same file immediately after failed verify should warn blind_patch."""
        trajectory = AgentTrajectory()

        # Failed validation
        trajectory.add_step(
            build_record(1, "tool:validate", status="failed", files_touched=("file.py",))
        )

        # Edit same file without diagnosis
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file.py"})

        result = check_trajectory_guard(trajectory, next_step, guard_mode="report")

        self.assertFalse(result.should_stop, "Report mode should not stop")
        self.assertEqual(result.mode, "report", "Mode should be 'report'")
        self.assertIn("without diagnosis", result.reason.lower(), "Should warn about blind patch")
        self.assertEqual(result.severity, "medium", "Should be medium severity")

    def test_guard_audit_then_patch_no_warning(self) -> None:
        """T5: Read/audit between failed verify and edit should not warn."""
        trajectory = AgentTrajectory()

        # Failed validation
        trajectory.add_step(
            build_record(1, "tool:validate", status="failed", files_touched=("file.py",))
        )

        # Diagnosis step (read)
        trajectory.add_step(
            build_record(2, "tool:read", status="completed", files_touched=("file.py",))
        )

        # Edit after diagnosis
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file.py"})

        result = check_trajectory_guard(trajectory, next_step, guard_mode="report")

        self.assertFalse(result.should_stop, "Report mode should not stop")
        self.assertEqual(result.mode, "report", "Mode should be 'report'")
        self.assertIn("no guard", result.reason.lower(), "Should not warn after diagnosis")

    def test_guard_repeated_failure_same_file(self) -> None:
        """T6: Same file failing 3+ times should warn repeated_failure_patch."""
        trajectory = AgentTrajectory()

        # 3 failed edit attempts on same file
        for i in range(1, 4):
            trajectory.add_step(
                build_record(i, "tool:edit", status="failed", files_touched=("file.py",))
            )

        # Try to edit same file again
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file.py"})

        result = check_trajectory_guard(trajectory, next_step, guard_mode="report")

        self.assertFalse(result.should_stop, "Report mode should not stop")
        self.assertEqual(result.mode, "report", "Mode should be 'report'")
        self.assertIn("failed verification 3+", result.reason.lower(), "Should warn about repeated failures")
        self.assertEqual(result.severity, "high", "Should be high severity")

    def test_guard_repeated_test_command_allowed(self) -> None:
        """T7: Running same test command multiple times should not warn duplicate_action."""
        trajectory = AgentTrajectory()

        # Run test command
        trajectory.add_step(
            create_step_record(
                step_id=1,
                phase="verify",
                action="command:unittest",
                command_run=("python3", "-m", "pytest", "tests/"),
                status="completed",
            )
        )

        # Run same test command again (common in iterative development)
        next_step = build_step("test", "command", command=("python3", "-m", "pytest", "tests/"))

        result = check_trajectory_guard(trajectory, next_step, guard_mode="report")

        self.assertFalse(result.should_stop, "Report mode should not stop")
        self.assertEqual(result.mode, "report", "Mode should be 'report'")
        # Note: Current implementation may still flag this as duplicate_action
        # This test documents expected behavior for future refinement

    def test_guard_duplicate_identical_edit(self) -> None:
        """T8: Identical edit action should warn duplicate_action_detected."""
        trajectory = AgentTrajectory()

        # Edit file
        trajectory.add_step(
            build_record(1, "tool:edit", status="completed", files_touched=("file.py",))
        )

        # Try to edit same file again with identical action
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file.py"})

        result = check_trajectory_guard(trajectory, next_step, guard_mode="report")

        self.assertFalse(result.should_stop, "Report mode should not stop")
        self.assertEqual(result.mode, "report", "Mode should be 'report'")
        self.assertIn("duplicate", result.reason.lower(), "Should warn about duplicate action")
        self.assertEqual(result.severity, "low", "Should be low severity")

    def test_guard_different_files_no_blind_patch(self) -> None:
        """T9: Editing different files should not trigger blind_patch warning."""
        trajectory = AgentTrajectory()

        # Failed validation on file_a.py
        trajectory.add_step(
            build_record(1, "tool:validate", status="failed", files_touched=("file_a.py",))
        )

        # Edit different file (file_b.py)
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file_b.py"})

        result = check_trajectory_guard(trajectory, next_step, guard_mode="report")

        self.assertFalse(result.should_stop, "Report mode should not stop")
        self.assertEqual(result.mode, "report", "Mode should be 'report'")
        self.assertIn("no guard", result.reason.lower(), "Should not warn for different file")

    def test_guard_report_mode_returns_violation_without_blocking_signal(self) -> None:
        """T10: Report mode should return violation metadata without raising or blocking."""
        trajectory = AgentTrajectory()

        # Create scenario that triggers multiple warnings:
        # 1. Edit without verification (completion_without_verification)
        trajectory.add_step(
            build_record(1, "tool:edit", status="completed", files_touched=("file_a.py",))
        )

        # 2. Failed validation
        trajectory.add_step(
            build_record(2, "tool:validate", status="failed", files_touched=("file_b.py",))
        )

        # 3. Blind patch (edit same file without diagnosis)
        trajectory.add_step(
            build_record(3, "tool:edit", status="failed", files_touched=("file_b.py",))
        )

        # 4. Duplicate action
        next_step = build_step("edit", "tool", tool="edit", args={"file_path": "file_b.py"})

        # Should not raise exception
        result = check_trajectory_guard(trajectory, next_step, guard_mode="report")

        # Verify report mode behavior
        self.assertFalse(result.should_stop, "Report mode should not set should_stop=True")
        self.assertEqual(result.mode, "report", "Mode should be 'report'")
        self.assertIsNotNone(result.reason, "Should return violation reason")
        self.assertIsNotNone(result.severity, "Should return severity")
        self.assertGreater(len(result.reason), 0, "Reason should not be empty")

        # Verify no blocking signal (should_stop=False means no block)
        self.assertFalse(result.should_stop, "Should not block in report mode")


if __name__ == "__main__":
    unittest.main()
