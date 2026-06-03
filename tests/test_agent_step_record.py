from __future__ import annotations

import unittest

from quantagent.agent_step_record import (
    AgentTrajectory,
    StepRecord,
    create_step_record,
)


class StepRecordTest(unittest.TestCase):
    def test_step_record_creation(self) -> None:
        """Create StepRecord with all fields and verify immutability."""
        step = StepRecord(
            step_id=1,
            phase="planning",
            decision_summary="Analyze requirements",
            action="tool:read",
            files_touched=("quantagent/agent_loop.py",),
            command_run=(),
            observation="File contains main loop",
            verification_result="passed",
            timestamp="2026-05-28T10:00:00",
            status="completed",
        )

        self.assertEqual(step.step_id, 1, "step_id should match")
        self.assertEqual(step.phase, "planning", "phase should match")
        self.assertEqual(step.decision_summary, "Analyze requirements", "decision_summary should match")
        self.assertEqual(step.action, "tool:read", "action should match")
        self.assertEqual(step.files_touched, ("quantagent/agent_loop.py",), "files_touched should match")
        self.assertEqual(step.command_run, (), "command_run should match")
        self.assertEqual(step.observation, "File contains main loop", "observation should match")
        self.assertEqual(step.verification_result, "passed", "verification_result should match")
        self.assertEqual(step.timestamp, "2026-05-28T10:00:00", "timestamp should match")
        self.assertEqual(step.status, "completed", "status should match")

        # Test frozen=True (immutability)
        with self.assertRaises(AttributeError, msg="StepRecord should be immutable (frozen=True)"):
            step.status = "failed"  # type: ignore[misc]

    def test_step_record_to_dict(self) -> None:
        """Convert StepRecord to dict and verify all fields."""
        step = StepRecord(
            step_id=2,
            phase="execution",
            decision_summary="Apply patch",
            action="tool:edit",
            files_touched=("quantagent/patch_engine.py",),
            command_run=(),
            observation="Patch applied successfully",
            verification_result="passed",
            timestamp="2026-05-28T10:05:00",
            status="completed",
        )

        result = step.to_dict()

        self.assertIsInstance(result, dict, "to_dict should return a dict")
        self.assertEqual(result["step_id"], 2, "dict should contain step_id")
        self.assertEqual(result["phase"], "execution", "dict should contain phase")
        self.assertEqual(result["decision_summary"], "Apply patch", "dict should contain decision_summary")
        self.assertEqual(result["action"], "tool:edit", "dict should contain action")
        self.assertEqual(result["files_touched"], ("quantagent/patch_engine.py",), "dict should contain files_touched")
        self.assertEqual(result["command_run"], (), "dict should contain command_run")
        self.assertEqual(result["observation"], "Patch applied successfully", "dict should contain observation")
        self.assertEqual(result["verification_result"], "passed", "dict should contain verification_result")
        self.assertEqual(result["timestamp"], "2026-05-28T10:05:00", "dict should contain timestamp")
        self.assertEqual(result["status"], "completed", "dict should contain status")

    def test_action_signature_normalization(self) -> None:
        """Test action signature normalization for duplicate detection."""
        # Test "tool:validate" → "tool:validate"
        step1 = StepRecord(
            step_id=1,
            phase="validation",
            decision_summary="",
            action="tool:validate",
            files_touched=(),
            command_run=(),
            observation="",
            verification_result="not_run",
            timestamp="2026-05-28T10:00:00",
            status="running",
        )
        self.assertEqual(step1.action_signature(), "tool:validate", "Simple action should remain unchanged")

        # Test "tool:edit" with files_touched → "tool:edit:file.py"
        step2 = StepRecord(
            step_id=2,
            phase="execution",
            decision_summary="",
            action="tool:edit",
            files_touched=("quantagent/agent_loop.py", "quantagent/trajectory.py"),
            command_run=(),
            observation="",
            verification_result="not_run",
            timestamp="2026-05-28T10:01:00",
            status="running",
        )
        self.assertEqual(
            step2.action_signature(),
            "tool:edit:quantagent/agent_loop.py",
            "Action with files_touched should include first file",
        )

        # Test "command:unittest" with command_run → "command:unittest:python3"
        step3 = StepRecord(
            step_id=3,
            phase="verification",
            decision_summary="",
            action="command:unittest",
            files_touched=(),
            command_run=("python3", "-m", "unittest"),
            observation="",
            verification_result="not_run",
            timestamp="2026-05-28T10:02:00",
            status="running",
        )
        self.assertEqual(
            step3.action_signature(),
            "command:unittest:python3",
            "Action with command_run should include first command",
        )

        # Test edge case: empty action
        step4 = StepRecord(
            step_id=4,
            phase="unknown",
            decision_summary="",
            action="",
            files_touched=(),
            command_run=(),
            observation="",
            verification_result="not_run",
            timestamp="2026-05-28T10:03:00",
            status="running",
        )
        self.assertEqual(step4.action_signature(), "", "Empty action should return empty string")

        # Test action without colon separator
        step5 = StepRecord(
            step_id=5,
            phase="unknown",
            decision_summary="",
            action="simple_action",
            files_touched=(),
            command_run=(),
            observation="",
            verification_result="not_run",
            timestamp="2026-05-28T10:04:00",
            status="running",
        )
        self.assertEqual(step5.action_signature(), "simple_action", "Action without colon should return as-is")


class AgentTrajectoryTest(unittest.TestCase):
    def test_trajectory_add_step(self) -> None:
        """Add steps to trajectory and verify order."""
        trajectory = AgentTrajectory()

        step1 = create_step_record(1, "planning", "tool:read")
        step2 = create_step_record(2, "execution", "tool:edit")
        step3 = create_step_record(3, "verification", "command:test")

        trajectory.add_step(step1)
        trajectory.add_step(step2)
        trajectory.add_step(step3)

        self.assertEqual(len(trajectory.steps), 3, "Trajectory should contain 3 steps")
        self.assertEqual(trajectory.steps[0].step_id, 1, "First step should have step_id=1")
        self.assertEqual(trajectory.steps[1].step_id, 2, "Second step should have step_id=2")
        self.assertEqual(trajectory.steps[2].step_id, 3, "Third step should have step_id=3")
        self.assertEqual(trajectory.steps[0].phase, "planning", "Order should be preserved")
        self.assertEqual(trajectory.steps[1].phase, "execution", "Order should be preserved")
        self.assertEqual(trajectory.steps[2].phase, "verification", "Order should be preserved")

    def test_trajectory_last_n_steps(self) -> None:
        """Test retrieving last N steps from trajectory."""
        trajectory = AgentTrajectory()

        for i in range(1, 6):
            trajectory.add_step(create_step_record(i, f"phase_{i}", f"action_{i}"))

        # Test last_n_steps(3) returns last 3
        last_3 = trajectory.last_n_steps(3)
        self.assertEqual(len(last_3), 3, "Should return last 3 steps")
        self.assertEqual([s.step_id for s in last_3], [3, 4, 5], "Should return steps 3, 4, 5")

        # Test last_n_steps(0) returns []
        last_0 = trajectory.last_n_steps(0)
        self.assertEqual(last_0, [], "Should return empty list for n=0")

        # Test last_n_steps(10) when only 5 steps exist
        last_10 = trajectory.last_n_steps(10)
        self.assertEqual(len(last_10), 5, "Should return all 5 steps when n > total steps")
        self.assertEqual([s.step_id for s in last_10], [1, 2, 3, 4, 5], "Should return all steps in order")

        # Test negative n
        last_neg = trajectory.last_n_steps(-5)
        self.assertEqual(last_neg, [], "Should return empty list for negative n")

    def test_trajectory_failed_steps(self) -> None:
        """Test filtering failed steps from trajectory."""
        trajectory = AgentTrajectory()

        trajectory.add_step(create_step_record(1, "planning", "tool:read", status="completed"))
        trajectory.add_step(create_step_record(2, "execution", "tool:edit", status="failed"))
        trajectory.add_step(create_step_record(3, "verification", "command:test", status="completed"))
        trajectory.add_step(create_step_record(4, "execution", "tool:write", status="failed"))
        trajectory.add_step(create_step_record(5, "reflection", "tool:analyze", status="completed"))

        failed = trajectory.failed_steps()

        self.assertEqual(len(failed), 2, "Should return only failed steps")
        self.assertEqual([s.step_id for s in failed], [2, 4], "Should return steps 2 and 4")
        self.assertEqual(failed[0].status, "failed", "All returned steps should have status='failed'")
        self.assertEqual(failed[1].status, "failed", "All returned steps should have status='failed'")
        self.assertEqual(failed[0].phase, "execution", "Order should be preserved")
        self.assertEqual(failed[1].phase, "execution", "Order should be preserved")

    def test_trajectory_files_modified(self) -> None:
        """Test extracting modified files from trajectory."""
        trajectory = AgentTrajectory()

        trajectory.add_step(
            create_step_record(
                1,
                "execution",
                "tool:edit",
                files_touched=("quantagent/agent_loop.py",),
            )
        )
        trajectory.add_step(
            create_step_record(
                2,
                "execution",
                "tool:write",
                files_touched=("quantagent/trajectory.py",),
            )
        )
        trajectory.add_step(
            create_step_record(
                3,
                "planning",
                "tool:read",
                files_touched=("quantagent/patch_engine.py",),
            )
        )
        trajectory.add_step(
            create_step_record(
                4,
                "execution",
                "tool:edit",
                files_touched=("quantagent/agent_loop.py", "quantagent/memory_extract.py"),
            )
        )

        modified = trajectory.files_modified()

        self.assertIsInstance(modified, set, "Should return a set")
        self.assertEqual(
            modified,
            {
                "quantagent/agent_loop.py",
                "quantagent/trajectory.py",
                "quantagent/memory_extract.py",
            },
            "Should only include files from edit/write actions",
        )
        self.assertNotIn("quantagent/patch_engine.py", modified, "Should not include files from read actions")

    def test_trajectory_find_step_index(self) -> None:
        """Test finding step index by step_id."""
        trajectory = AgentTrajectory()

        trajectory.add_step(create_step_record(1, "planning", "tool:read"))
        trajectory.add_step(create_step_record(3, "execution", "tool:edit"))
        trajectory.add_step(create_step_record(5, "verification", "command:test"))

        # Test find_step_index(3) returns 1
        index_3 = trajectory.find_step_index(3)
        self.assertEqual(index_3, 1, "Step with step_id=3 should be at index 1")

        # Test find_step_index(1) returns 0
        index_1 = trajectory.find_step_index(1)
        self.assertEqual(index_1, 0, "Step with step_id=1 should be at index 0")

        # Test find_step_index(5) returns 2
        index_5 = trajectory.find_step_index(5)
        self.assertEqual(index_5, 2, "Step with step_id=5 should be at index 2")

        # Test find_step_index(99) returns None
        index_99 = trajectory.find_step_index(99)
        self.assertIsNone(index_99, "Non-existent step_id should return None")

    def test_trajectory_steps_after(self) -> None:
        """Test retrieving steps after a given step_id."""
        trajectory = AgentTrajectory()

        trajectory.add_step(create_step_record(1, "planning", "tool:read"))
        trajectory.add_step(create_step_record(2, "execution", "tool:edit"))
        trajectory.add_step(create_step_record(3, "verification", "command:test"))
        trajectory.add_step(create_step_record(4, "reflection", "tool:analyze"))
        trajectory.add_step(create_step_record(5, "completion", "tool:report"))

        # Test steps_after(step_id=2) returns steps 3,4,5
        after_2 = trajectory.steps_after(2)
        self.assertEqual(len(after_2), 3, "Should return 3 steps after step_id=2")
        self.assertEqual([s.step_id for s in after_2], [3, 4, 5], "Should return steps 3, 4, 5")

        # Test steps_after(step_id=1) returns steps 2,3,4,5
        after_1 = trajectory.steps_after(1)
        self.assertEqual(len(after_1), 4, "Should return 4 steps after step_id=1")
        self.assertEqual([s.step_id for s in after_1], [2, 3, 4, 5], "Should return steps 2, 3, 4, 5")

        # Test steps_after(step_id=5) returns []
        after_5 = trajectory.steps_after(5)
        self.assertEqual(after_5, [], "Should return empty list when step_id is last")

        # Test steps_after(step_id=99) returns []
        after_99 = trajectory.steps_after(99)
        self.assertEqual(after_99, [], "Should return empty list for non-existent step_id")


class CreateStepRecordFactoryTest(unittest.TestCase):
    def test_create_step_record_factory_minimal_args(self) -> None:
        """Test factory function with minimal required arguments."""
        step = create_step_record(1, "planning", "tool:read")

        self.assertEqual(step.step_id, 1, "step_id should match")
        self.assertEqual(step.phase, "planning", "phase should match")
        self.assertEqual(step.action, "tool:read", "action should match")
        self.assertEqual(step.decision_summary, "", "decision_summary should default to empty string")
        self.assertEqual(step.files_touched, (), "files_touched should default to empty tuple")
        self.assertEqual(step.command_run, (), "command_run should default to empty tuple")
        self.assertEqual(step.observation, "", "observation should default to empty string")
        self.assertEqual(step.verification_result, "not_run", "verification_result should default to 'not_run'")
        self.assertEqual(step.status, "running", "status should default to 'running'")
        self.assertNotEqual(step.timestamp, "", "timestamp should be auto-generated")
        self.assertIn("T", step.timestamp, "timestamp should be ISO format")

    def test_create_step_record_factory_all_args(self) -> None:
        """Test factory function with all arguments provided."""
        step = create_step_record(
            2,
            "execution",
            "tool:edit",
            decision_summary="Apply security patch",
            files_touched=("quantagent/agent_loop.py", "quantagent/patch_engine.py"),
            command_run=("python3", "-m", "unittest"),
            observation="Patch applied successfully",
            verification_result="passed",
            status="completed",
            timestamp="2026-05-28T12:00:00",
        )

        self.assertEqual(step.step_id, 2, "step_id should match")
        self.assertEqual(step.phase, "execution", "phase should match")
        self.assertEqual(step.action, "tool:edit", "action should match")
        self.assertEqual(step.decision_summary, "Apply security patch", "decision_summary should match")
        self.assertEqual(
            step.files_touched,
            ("quantagent/agent_loop.py", "quantagent/patch_engine.py"),
            "files_touched should match",
        )
        self.assertEqual(step.command_run, ("python3", "-m", "unittest"), "command_run should match")
        self.assertEqual(step.observation, "Patch applied successfully", "observation should match")
        self.assertEqual(step.verification_result, "passed", "verification_result should match")
        self.assertEqual(step.status, "completed", "status should match")
        self.assertEqual(step.timestamp, "2026-05-28T12:00:00", "timestamp should match provided value")

    def test_create_step_record_factory_defaults_applied(self) -> None:
        """Test that factory function applies correct defaults."""
        step = create_step_record(
            3,
            "verification",
            "command:test",
            observation="Tests passed",
        )

        self.assertEqual(step.decision_summary, "", "Unspecified decision_summary should default to empty")
        self.assertEqual(step.files_touched, (), "Unspecified files_touched should default to empty tuple")
        self.assertEqual(step.command_run, (), "Unspecified command_run should default to empty tuple")
        self.assertEqual(step.verification_result, "not_run", "Unspecified verification_result should default")
        self.assertEqual(step.status, "running", "Unspecified status should default to 'running'")
        self.assertEqual(step.observation, "Tests passed", "Specified observation should be preserved")


if __name__ == "__main__":
    unittest.main()
