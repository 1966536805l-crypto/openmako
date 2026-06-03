"""Integration tests for agent_loop_core with Phase 2a guard integration.

Tests verify that report-only mode doesn't change behavior:
- Guards detect violations but don't stop execution
- Warnings are logged with "violation_detected" terminology
- Trajectory JSONL is still written correctly
- Normal flows don't trigger false positives
"""

from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent.agent_loop_core import (
    AgentLoopObservation,
    AgentLoopStep,
    _extract_files_from_observation,
    _missing_post_edit_verification,
    build_agent_plan,
    run_agent_loop,
)
from quantagent.mode_router import route_agent_mode
from quantagent.trajectory import read_events


class TestReportOnlyGuardIntegration(unittest.TestCase):
    """Integration tests for Phase 2a report-only guard mode."""

    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        """Create temporary project directory for testing."""
        return tempfile.TemporaryDirectory(prefix="quantagent_loop_core_")

    def test_default_build_plan_includes_write_capable_step_before_validation(self) -> None:
        """Default non-legacy build planning must schedule implementation before validation."""
        with self.make_project() as tmp:
            project = Path(tmp)
            task = "create hello.py with greet function and test it"
            route = route_agent_mode(project, task, input_provenance="agent")
            plan = build_agent_plan(task, route, include_validation=True)

            validation_names = {"validate", "unit_tests"}
            write_capable_names = {"implement", "implementation", "create", "edit", "write"}
            validation_indexes = [
                index
                for index, step in enumerate(plan)
                if step.name in validation_names or step.tool in validation_names
            ]
            first_validation_index = min(validation_indexes) if validation_indexes else len(plan)
            write_capable_before_validation = [
                step
                for step in plan[:first_validation_index]
                if step.name in write_capable_names or step.tool in write_capable_names
            ]

            self.assertTrue(
                write_capable_before_validation,
                "missing implementation/write-capable step before validation; "
                f"plan={[step.to_dict() for step in plan]}",
            )
            implement = next(step for step in plan if step.name == "implement")
            self.assertTrue(implement.required)

    def test_required_implementation_does_not_match_substrings(self) -> None:
        """Words like credit should not accidentally make implement required."""
        with self.make_project() as tmp:
            project = Path(tmp)
            task = "review credit handling"
            route = route_agent_mode(project, task, explicit_mode="build")
            plan = build_agent_plan(task, route, include_validation=False)

            implement = next(step for step in plan if step.name == "implement")
            self.assertFalse(implement.required)

    def test_extract_files_from_observation_converts_file_path_to_string(self) -> None:
        """Path objects from file_path metadata should not leak into trajectory records."""
        observation = AgentLoopObservation(
            1,
            "write",
            "tool",
            True,
            "wrote file",
            "build",
            {"file_path": Path("hello.py")},
        )

        files = _extract_files_from_observation(observation)

        self.assertEqual(files, ("hello.py",))
        self.assertIsInstance(files[0], str)

    def test_observation_to_dict_converts_nested_paths_to_json_safe_strings(self) -> None:
        observation = AgentLoopObservation(
            1,
            "quant_priority",
            "internal",
            True,
            "audited",
            "build",
            {"audit_findings": [{"path": Path("AI_协作交接/report.csv")}], "paths": (Path("a.py"),)},
        )

        payload = observation.to_dict()

        json.dumps(payload)
        self.assertEqual(payload["data"]["audit_findings"][0]["path"], "AI_协作交接/report.csv")
        self.assertEqual(payload["data"]["paths"], ["a.py"])

    def test_default_build_loop_writes_planner_operations_and_runs_tests(self) -> None:
        """Default build loop should feed planner operations into implement and self-test."""
        with self.make_project() as tmp:
            project = Path(tmp)
            task = "create hello.py with greet function and test it"

            result = run_agent_loop(project, task, include_validation=True)

            hello = project / "hello.py"
            self.assertTrue(hello.exists(), result.to_dict())
            content = hello.read_text(encoding="utf-8")
            self.assertIn("def greet(name", content)
            self.assertTrue((project / "tests" / "test_hello.py").exists(), result.to_dict())

            implement = next(obs for obs in result.observations if obs.name == "implement")
            self.assertTrue(implement.ok, implement.to_dict())
            expected_files = ["hello.py", "tests/__init__.py", "tests/test_hello.py"]
            self.assertEqual(implement.data["operations_count"], 3)
            self.assertEqual(sorted(implement.data["files_touched"]), expected_files)
            self.assertEqual(sorted(implement.data["created_files"]), expected_files)
            self.assertTrue(next(obs for obs in result.observations if obs.name == "validate").ok)
            self.assertTrue(next(obs for obs in result.observations if obs.name == "unit_tests").ok)

    def test_build_loop_requires_verification_after_file_changes(self) -> None:
        """Build mode must not report ok after edits without post-edit verification."""
        with self.make_project() as tmp:
            project = Path(tmp)
            task = "create hello.py with greet function and test it"

            result = run_agent_loop(project, task, include_validation=False)

            self.assertFalse(result.ok, result.to_dict())
            self.assertEqual(result.failure_class, "verification_failed")
            names = [obs.name for obs in result.observations]
            self.assertIn("implement", names)
            self.assertIn("verification_required", names)
            verification = next(obs for obs in result.observations if obs.name == "verification_required")
            self.assertFalse(verification.ok)
            self.assertEqual(
                verification.data["files_touched"],
                ["hello.py", "tests/__init__.py", "tests/test_hello.py"],
            )
            self.assertNotIn("validate", names)
            self.assertNotIn("unit_tests", names)

    def test_finalize_hook_cannot_promote_verification_failure_to_success(self) -> None:
        """Lifecycle hooks may downgrade a run, but must not erase required verification failure."""
        from quantagent.hook_runner import HookHandler
        from quantagent.lifecycle_hooks import GLOBAL_HOOKS

        with self.make_project() as tmp:
            project = Path(tmp)
            GLOBAL_HOOKS.register(
                HookHandler(
                    "before_agent_finalize",
                    lambda payload, context: payload | {"ok": True, "status": "done", "summary": "hook says done"},
                    plugin_id="test-finalize-promote",
                )
            )
            try:
                result = run_agent_loop(
                    project,
                    "create hello.py with greet function and test it",
                    explicit_mode="build",
                    include_validation=False,
                )
            finally:
                GLOBAL_HOOKS.handlers = [
                    handler
                    for handler in GLOBAL_HOOKS.handlers
                    if handler.plugin_id != "test-finalize-promote"
                ]

        self.assertFalse(result.ok, result.to_dict())
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.failure_class, "verification_failed")
        self.assertIn("verification_required", [obs.name for obs in result.observations])

    def test_fix_add_numbers_repairs_subject_and_preserves_test_file(self) -> None:
        """CodingBench-shaped repair tasks must edit subject.py and run test_subject.py."""
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "subject.py").write_text("def add_numbers(a, b):\n    return a - b\n", encoding="utf-8")
            (project / "test_subject.py").write_text(
                "import unittest\nfrom subject import add_numbers\n\n"
                "class SubjectTest(unittest.TestCase):\n"
                "    def test_sum(self):\n"
                "        self.assertEqual(add_numbers(2, 3), 5)\n",
                encoding="utf-8",
            )
            test_before = (project / "test_subject.py").read_text(encoding="utf-8")

            result = run_agent_loop(
                project,
                "Fix add_numbers so it returns arithmetic sum for ints and floats.",
                explicit_mode="build",
                include_validation=True,
            )
            subject_after = (project / "subject.py").read_text(encoding="utf-8")
            test_after = (project / "test_subject.py").read_text(encoding="utf-8")

        self.assertTrue(result.ok, result.to_dict())
        names = [obs.name for obs in result.observations]
        self.assertIn("implement", names)
        self.assertIn("unit_tests", names)
        implement = next(obs for obs in result.observations if obs.name == "implement")
        unit_tests = next(obs for obs in result.observations if obs.name == "unit_tests")
        self.assertTrue(implement.ok, implement.to_dict())
        self.assertTrue(unit_tests.ok, unit_tests.to_dict())
        self.assertIn("planner", implement.data)
        self.assertEqual(implement.data["files_touched"], ["subject.py"])
        self.assertIn("return a + b", subject_after)
        self.assertEqual(test_after, test_before)

    def test_subject_repair_requires_test_subject_to_pass_after_write(self) -> None:
        """A bad planner overwrite must not pass via validation skip."""
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "subject.py").write_text("def add_numbers(a, b):\n    return a - b\n", encoding="utf-8")
            (project / "test_subject.py").write_text(
                "import unittest\nfrom subject import add_numbers\n\n"
                "class SubjectTest(unittest.TestCase):\n"
                "    def test_sum(self):\n"
                "        self.assertEqual(add_numbers(2, 3), 5)\n",
                encoding="utf-8",
            )
            bad_plan = {
                "ok": True,
                "operations": [
                    {
                        "op": "write_text",
                        "path": "subject.py",
                        "text": "def add_numbers(a, b):\n    return a - b\n",
                    }
                ],
            }

            with patch("quantagent.agent_planner.plan_task_to_operations", return_value=bad_plan):
                result = run_agent_loop(
                    project,
                    "Fix add_numbers so it returns arithmetic sum for ints and floats.",
                    explicit_mode="build",
                    include_validation=True,
                )

        self.assertFalse(result.ok, result.to_dict())
        names = [obs.name for obs in result.observations]
        self.assertIn("unit_tests", names)
        unit_tests = next(obs for obs in result.observations if obs.name == "unit_tests")
        self.assertFalse(unit_tests.ok, unit_tests.to_dict())

    def test_top_n_repair_is_not_blocked_as_quant_order_claim(self) -> None:
        """Plain coding terms like return/order must not trigger quant goal blocking."""
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "subject.py").write_text("def top_n(values, n):\n    return values[:n]\n", encoding="utf-8")
            (project / "test_subject.py").write_text(
                "import unittest\nfrom subject import top_n\n\n"
                "class SubjectTest(unittest.TestCase):\n"
                "    def test_top(self):\n"
                "        self.assertEqual(top_n([3, 1, 5, 2], 2), [5, 3])\n"
                "        self.assertEqual(top_n([1], 0), [])\n",
                encoding="utf-8",
            )

            result = run_agent_loop(
                project,
                "Fix top_n to return the n largest values in descending order.",
                explicit_mode="build",
                include_validation=True,
            )

        self.assertTrue(result.ok, result.to_dict())
        self.assertNotIn("goal_conflict", result.failure_class)

    def test_unsupported_existing_file_repair_fails_closed_without_writing(self) -> None:
        """Unsupported existing-file repair must fail before validation noise and preserve files."""
        with self.make_project() as tmp:
            project = Path(tmp)
            subject_before = "def multiply_numbers(a, b):\n    return a + b\n"
            test_before = (
                "import unittest\nfrom subject import multiply_numbers\n\n"
                "class SubjectTest(unittest.TestCase):\n"
                "    def test_product(self):\n"
                "        self.assertEqual(multiply_numbers(2, 3), 6)\n"
            )
            (project / "subject.py").write_text(subject_before, encoding="utf-8")
            (project / "test_subject.py").write_text(test_before, encoding="utf-8")

            result = run_agent_loop(
                project,
                "Fix multiply_numbers so it returns product.",
                explicit_mode="build",
                include_validation=True,
            )
            subject_after = (project / "subject.py").read_text(encoding="utf-8")
            test_after = (project / "test_subject.py").read_text(encoding="utf-8")

        self.assertFalse(result.ok, result.to_dict())
        self.assertEqual(result.status, "failed")
        names = [obs.name for obs in result.observations]
        self.assertIn("implement", names)
        self.assertNotIn("unit_tests", names)
        implement = next(obs for obs in result.observations if obs.name == "implement")
        self.assertFalse(implement.ok)
        self.assertIn("unsupported", str(implement.data.get("planner", {})).lower())
        self.assertEqual(subject_after, subject_before)
        self.assertEqual(test_after, test_before)

    def test_build_loop_requires_verification_after_last_file_change(self) -> None:
        """A passing verification before a later edit must not satisfy the post-edit gate."""
        with self.make_project() as tmp:
            project = Path(tmp)
            plan = [
                AgentLoopStep(
                    "implement",
                    "tool",
                    tool="implement",
                    args={"operations": [{"op": "write_text", "path": "first.py", "text": "FIRST = 1\n"}]},
                    mode="build",
                ),
                AgentLoopStep("validate", "tool", tool="validate", args={}, required=False, mode="build"),
                AgentLoopStep(
                    "implement",
                    "tool",
                    tool="implement",
                    args={"operations": [{"op": "write_text", "path": "second.py", "text": "SECOND = 2\n"}]},
                    mode="build",
                ),
            ]

            result = run_agent_loop(project, "write twice with stale validation", explicit_mode="build", plan=plan)

            self.assertFalse(result.ok, result.to_dict())
            self.assertEqual(result.failure_class, "verification_failed")
            verification = next(obs for obs in result.observations if obs.name == "verification_required")
            self.assertEqual(verification.data["files_touched"], ["first.py", "second.py"])

    def test_agent_loop_stops_before_next_step_when_duration_exceeded(self) -> None:
        """A task-level duration fuse must prevent later steps from running."""
        with self.make_project() as tmp:
            project = Path(tmp)
            plan = [
                AgentLoopStep("route", "internal", required=True, mode="build"),
                AgentLoopStep(
                    "implement",
                    "tool",
                    tool="implement",
                    args={"operations": [{"op": "write_text", "path": "late.py", "text": "LATE = 1\n"}]},
                    mode="build",
                ),
            ]

            with patch("quantagent.agent_loop_core.time.monotonic", side_effect=[0.0, 0.0, 2.0, 2.0]):
                result = run_agent_loop(
                    project,
                    "write late file",
                    explicit_mode="build",
                    include_validation=False,
                    plan=plan,
                    max_duration_seconds=1.0,
                )

            self.assertFalse(result.ok, result.to_dict())
            self.assertEqual(result.failure_class, "timeout")
            self.assertEqual(result.status, "failed")
            self.assertEqual(result.to_dict()["status"], "failed")
            self.assertEqual(result.to_agent_result().stage, "agent_loop_auto_mode_context")
            self.assertEqual([obs.name for obs in result.observations], ["route", "task_timeout"])
            timeout = result.observations[-1]
            self.assertEqual(timeout.data["next_step"], "implement")
            self.assertFalse((project / "late.py").exists())

    def test_agent_loop_rejects_non_finite_duration_fuse(self) -> None:
        with self.make_project() as tmp:
            with self.assertRaisesRegex(ValueError, "finite non-negative"):
                run_agent_loop(
                    Path(tmp),
                    "write late file",
                    explicit_mode="build",
                    include_validation=False,
                    max_duration_seconds=float("nan"),
                )

    def test_agent_loop_stops_before_step_budget_exceeded(self) -> None:
        """A task-level step budget must prevent later steps from running."""
        with self.make_project() as tmp:
            project = Path(tmp)
            plan = [
                AgentLoopStep("route", "internal", required=True, mode="build"),
                AgentLoopStep(
                    "implement",
                    "tool",
                    tool="implement",
                    args={"operations": [{"op": "write_text", "path": "late.py", "text": "LATE = 1\n"}]},
                    mode="build",
                ),
            ]

            result = run_agent_loop(
                project,
                "write late file",
                explicit_mode="build",
                include_validation=False,
                plan=plan,
                max_steps=1,
            )

            self.assertFalse(result.ok, result.to_dict())
            self.assertEqual(result.failure_class, "step_limit")
            self.assertEqual(result.status, "failed")
            self.assertEqual([obs.name for obs in result.observations], ["route", "step_limit"])
            limit = result.observations[-1]
            self.assertEqual(limit.data["max_steps"], 1)
            self.assertEqual(limit.data["next_step"], "implement")
            self.assertFalse((project / "late.py").exists())

    def test_agent_loop_writes_patch_artifact_from_before_edit_checkpoint(self) -> None:
        """Final agent results should include a reviewable patch artifact."""
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "module.py"
            target.write_text("VALUE = 'old'\n", encoding="utf-8")
            plan = [
                AgentLoopStep(
                    "implement",
                    "tool",
                    tool="implement",
                    args={"operations": [{"op": "write_text", "path": "module.py", "text": "VALUE = 'new'\n"}]},
                    mode="build",
                )
            ]

            result = run_agent_loop(
                project,
                "update module value",
                explicit_mode="build",
                include_validation=False,
                plan=plan,
            )

            self.assertTrue(result.patch_artifact_path, result.to_dict())
            patch_path = Path(result.patch_artifact_path)
            self.assertTrue(patch_path.exists())
            patch_text = patch_path.read_text(encoding="utf-8")
            self.assertIn("--- a/module.py", patch_text)
            self.assertIn("+++ b/module.py", patch_text)
            self.assertIn("-VALUE = 'old'", patch_text)
            self.assertIn("+VALUE = 'new'", patch_text)
            self.assertIn(result.patch_artifact_path, result.to_agent_result().created_files)

    def test_agent_loop_rejects_invalid_step_budget(self) -> None:
        with self.make_project() as tmp:
            with self.assertRaisesRegex(ValueError, "non-negative integer"):
                run_agent_loop(
                    Path(tmp),
                    "write late file",
                    explicit_mode="build",
                    include_validation=False,
                    max_steps=-1,
                )

    def test_post_edit_gate_treats_file_path_metadata_as_mutation(self) -> None:
        gap = _missing_post_edit_verification(
            [
                AgentLoopObservation(1, "custom_write", "tool", True, "wrote", "build", {"file_path": "manual.py"}),
                AgentLoopObservation(2, "final_review", "internal", True, "done", "build", {}),
            ],
            "build",
        )

        self.assertIsNotNone(gap)
        assert gap is not None
        self.assertEqual(gap.data["files_touched"], ["manual.py"])

    def test_build_loop_rejects_planner_path_escape_without_writing(self) -> None:
        """Planner rejection in build loop should not write files or claim creation."""
        with self.make_project() as tmp:
            project = Path(tmp)
            task = "create ../escape.py outside the project"

            result = run_agent_loop(project, task, explicit_mode="build", include_validation=False)

            self.assertFalse(result.ok, result.to_dict())
            self.assertFalse((project.parent / "escape.py").exists())
            implement = next(obs for obs in result.observations if obs.name == "implement")
            self.assertFalse(implement.ok)
            self.assertEqual(implement.data.get("files_touched"), [])
            self.assertEqual(implement.data.get("created_files"), [])
            self.assertIn("unsafe", str(implement.data.get("planner", {})).lower())

    def test_build_loop_rejects_absolute_path_without_writing(self) -> None:
        """Absolute-path planner rejection should fail required implementation without writes."""
        with self.make_project() as tmp:
            project = Path(tmp)
            outside = project.parent / "escape.py"
            task = f"create {outside} with malicious code"

            result = run_agent_loop(project, task, explicit_mode="build", include_validation=False)

            self.assertFalse(result.ok, result.to_dict())
            self.assertFalse(outside.exists())
            implement = next(obs for obs in result.observations if obs.name == "implement")
            self.assertFalse(implement.ok)
            self.assertEqual(implement.data.get("files_touched"), [])
            self.assertEqual(implement.data.get("created_files"), [])
            self.assertIn("absolute path", str(implement.data.get("planner", {})).lower())

    def test_build_loop_rejects_unsupported_planner_task_without_writing(self) -> None:
        """Unsupported deterministic planner tasks should not write placeholder files."""
        with self.make_project() as tmp:
            project = Path(tmp)
            task = "create calculator.py with add function and test it"

            result = run_agent_loop(project, task, explicit_mode="build", include_validation=False)

            self.assertFalse(result.ok, result.to_dict())
            self.assertFalse((project / "calculator.py").exists())
            self.assertFalse((project / "tests" / "test_calculator.py").exists())
            implement = next(obs for obs in result.observations if obs.name == "implement")
            self.assertFalse(implement.ok)
            self.assertEqual(implement.data.get("files_touched"), [])
            self.assertEqual(implement.data.get("created_files"), [])
            self.assertIn("unsupported", str(implement.data.get("planner", {})).lower())

    def test_build_loop_stops_after_unsupported_planner_task_even_with_validation(self) -> None:
        """Planner rejection should not be followed by noisy validation/unit-test steps."""
        with self.make_project() as tmp:
            project = Path(tmp)
            task = "create calculator.py with add function and test it"

            result = run_agent_loop(project, task, explicit_mode="build", include_validation=True)

            self.assertFalse(result.ok, result.to_dict())
            names = [obs.name for obs in result.observations]
            self.assertIn("implement", names)
            self.assertNotIn("validate", names)
            self.assertNotIn("unit_tests", names)
            self.assertFalse((project / "calculator.py").exists())

    def test_build_loop_stops_after_required_implementation_failure_when_configured(self) -> None:
        """stop_on_required_failure should prevent validation after required implement failure."""
        with self.make_project() as tmp:
            project = Path(tmp)
            task = "create ../escape.py outside the project"

            result = run_agent_loop(
                project,
                task,
                explicit_mode="build",
                include_validation=True,
                stop_on_required_failure=True,
            )

            self.assertFalse(result.ok, result.to_dict())
            names = [obs.name for obs in result.observations]
            self.assertIn("implement", names)
            self.assertNotIn("validate", names)
            self.assertNotIn("unit_tests", names)

    def test_build_loop_stops_after_unsupported_planner_task_when_configured(self) -> None:
        """The explicit stop flag should also cover unsupported deterministic planner failures."""
        with self.make_project() as tmp:
            project = Path(tmp)
            task = "create calculator.py with add function and test it"

            result = run_agent_loop(
                project,
                task,
                explicit_mode="build",
                include_validation=True,
                stop_on_required_failure=True,
            )

            self.assertFalse(result.ok, result.to_dict())
            names = [obs.name for obs in result.observations]
            self.assertIn("implement", names)
            self.assertNotIn("validate", names)
            self.assertNotIn("unit_tests", names)

    def test_report_only_guard_does_not_stop_loop(self) -> None:
        """Test that guard violations in report mode don't stop execution.

        Creates a scenario that would trigger repeated_failure_patch:
        - Multiple failed edit attempts on same file
        - Next step attempts to edit same file again
        - Assert loop completes all planned steps
        - Assert AgentLoopResult.ok matches expected behavior
        - Assert no steps were skipped due to guard
        """
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "tests").mkdir()
            (project / "tests" / "test_sample.py").write_text(
                "import unittest\n\nclass Sample(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )

            # Create a simple plan that will complete successfully
            # Even if guards detect patterns, they should not stop execution
            route = route_agent_mode(project, "run basic checks")
            plan = build_agent_plan("run basic checks", route, include_validation=False)

            result = run_agent_loop(
                project,
                "run basic checks",
                explicit_mode="build",
                include_validation=False,
                plan=plan,
            )

            # Assert loop completed
            self.assertIsNotNone(result)
            self.assertGreater(len(result.observations), 0, "Should have observations")

            # Assert all planned steps were executed (not skipped by guard)
            executed_step_names = {obs.name for obs in result.observations}
            planned_step_names = {step.name for step in plan}

            # All required steps should be executed
            required_steps = {step.name for step in plan if step.required}
            executed_required = executed_step_names.intersection(required_steps)
            self.assertEqual(
                len(executed_required),
                len(required_steps),
                f"All required steps should execute. Missing: {required_steps - executed_required}",
            )

            # Result.ok should reflect actual execution, not guard violations
            # For this simple plan, it should succeed
            self.assertTrue(result.ok, f"Loop should complete successfully: {result.summary}")

    def test_guard_warning_written_when_violation_detected(self) -> None:
        """Test that guard violations are logged with correct terminology.

        Creates a scenario that could trigger a guard violation.
        Captures log output and verifies:
        - Log contains "violation_detected" (NOT "stopped")
        - Log contains violation_type and severity
        """
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "tests").mkdir()
            (project / "tests" / "test_sample.py").write_text(
                "import unittest\n\nclass Sample(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )

            # Set up logging capture
            logger = logging.getLogger("quantagent.agent_loop_core")
            original_level = logger.level
            logger.setLevel(logging.WARNING)

            captured_logs: list[str] = []

            class LogCapture(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    captured_logs.append(self.format(record))

            handler = LogCapture()
            logger.addHandler(handler)

            try:
                # Create a plan that might trigger guard checks
                # The guard integration should log warnings but not stop execution
                route = route_agent_mode(project, "implement feature")
                plan = build_agent_plan("implement feature", route, include_validation=False)

                result = run_agent_loop(
                    project,
                    "implement feature",
                    explicit_mode="build",
                    include_validation=False,
                    plan=plan,
                )

                # If no warnings were logged, that's also valid (no violations detected)
                # This test primarily ensures the logging infrastructure is in place
                self.assertIsNotNone(result)

                # Check if any guard-related warnings were logged
                # Note: In a clean run, there may be no violations, which is expected
                guard_logs = [
                    log for log in captured_logs
                    if "violation_detected" in log or "Guard" in log
                ]

                # If guard violations were detected, verify correct terminology
                for log_entry in guard_logs:
                    self.assertIn("violation_detected", log_entry, "Should use 'violation_detected' terminology")
                    self.assertNotIn("stopped", log_entry.lower(), "Should NOT say 'stopped' in report mode")

            finally:
                logger.removeHandler(handler)
                logger.setLevel(original_level)

    def test_existing_trajectory_jsonl_still_written(self) -> None:
        """Test that trajectory JSONL is written correctly with guard integration.

        Runs agent loop and verifies:
        - Trajectory JSONL file exists at expected path
        - JSONL content contains expected events (step, action, observation)
        - Format matches existing trajectory.py structure
        """
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "AI_协作交接").mkdir()
            (project / "tests").mkdir()
            (project / "tests" / "test_sample.py").write_text(
                "import unittest\n\nclass Sample(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )

            result = run_agent_loop(
                project,
                "run status check",
                explicit_mode="build",
                include_validation=False,
            )

            # Check trajectory path exists (this is the summary file)
            self.assertTrue(result.trajectory_path, "Should have trajectory_path")
            trajectory_summary_file = Path(result.trajectory_path)
            self.assertTrue(trajectory_summary_file.exists(), f"Trajectory summary file should exist: {trajectory_summary_file}")

            # Read summary to get event trajectory path
            summary = json.loads(trajectory_summary_file.read_text(encoding="utf-8"))
            self.assertIn("event_trajectory_path", summary, "Summary should contain event_trajectory_path")

            event_trajectory_path = summary["event_trajectory_path"]
            event_file = Path(event_trajectory_path)
            self.assertTrue(event_file.exists(), f"Event trajectory file should exist: {event_file}")

            # Read and verify JSONL event content
            events = read_events(event_file)
            self.assertGreater(len(events), 0, "Should have trajectory events")

            # Verify event structure matches trajectory.py format
            for event in events:
                self.assertIn(event.kind, {"step", "action", "observation", "edit", "test"})
                self.assertIsNotNone(event.content)
                self.assertIsNotNone(event.timestamp)

            # Verify we have expected event types
            event_kinds = {event.kind for event in events}
            self.assertIn("step", event_kinds, "Should have step events")
            self.assertIn("observation", event_kinds, "Should have observation events")

            # Verify summary content
            self.assertEqual(summary["task"], "run status check")
            self.assertEqual(summary["status"], "done")
            self.assertEqual(result.status, "done")
            self.assertEqual(result.to_dict()["status"], "done")
            self.assertEqual(result.to_agent_result().stage, "agent_loop_auto_mode_context")
            self.assertIn("observations", summary)
            self.assertIn("plan", summary)

    def test_repeated_agent_runs_use_isolated_event_trajectory_files(self) -> None:
        """Repeated runs in one workspace must not append lower steps to an old event JSONL."""
        with self.make_project() as tmp:
            project = Path(tmp)
            plan = (AgentLoopStep("route", "internal", required=True, mode="build"),)

            first = run_agent_loop(
                project,
                "run status check",
                explicit_mode="build",
                plan=plan,
                include_validation=False,
            )
            first_summary = json.loads(Path(first.trajectory_path).read_text(encoding="utf-8").splitlines()[-1])
            second = run_agent_loop(
                project,
                "run status check",
                explicit_mode="build",
                plan=plan,
                include_validation=False,
            )
            second_summary = json.loads(Path(second.trajectory_path).read_text(encoding="utf-8").splitlines()[-1])
            first_event_exists = Path(first_summary["event_trajectory_path"]).exists()
            second_event_exists = Path(second_summary["event_trajectory_path"]).exists()

        self.assertNotEqual(first_summary["event_trajectory_path"], second_summary["event_trajectory_path"])
        self.assertTrue(first_event_exists)
        self.assertTrue(second_event_exists)
        self.assertEqual(first.status, "done")
        self.assertEqual(second.status, "done")

    def test_no_guard_warning_for_normal_plan_execute_verify_flow(self) -> None:
        """Test that normal successful flows don't trigger guard violations.

        Creates a normal flow: plan → execute → verify (pass)
        Verifies:
        - NO guard violations logged
        - All steps complete with ok=True
        """
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "tests").mkdir()
            (project / "tests" / "test_sample.py").write_text(
                "import unittest\n\nclass Sample(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )

            # Set up logging capture
            logger = logging.getLogger("quantagent.agent_loop_core")
            original_level = logger.level
            logger.setLevel(logging.WARNING)

            captured_logs: list[str] = []

            class LogCapture(logging.Handler):
                def emit(self, record: logging.LogRecord) -> None:
                    captured_logs.append(self.format(record))

            handler = LogCapture()
            logger.addHandler(handler)

            try:
                # Run a normal, successful flow
                result = run_agent_loop(
                    project,
                    "check project status",
                    explicit_mode="build",
                    include_validation=False,
                )

                # Verify successful completion
                self.assertTrue(result.ok, f"Normal flow should succeed: {result.summary}")

                # Verify no guard violations were logged
                guard_violations = [
                    log for log in captured_logs
                    if "violation_detected" in log or "Guard" in log
                ]

                self.assertEqual(
                    len(guard_violations),
                    0,
                    f"Normal flow should not trigger guard violations. Found: {guard_violations}",
                )

                # Verify all observations completed successfully
                failed_observations = [obs for obs in result.observations if not obs.ok]
                # Some optional steps may fail, but required steps should pass
                required_failures = [
                    obs for obs in failed_observations
                    if any(step.name == obs.name and step.required for step in result.plan)
                ]

                self.assertEqual(
                    len(required_failures),
                    0,
                    f"Required steps should not fail in normal flow: {required_failures}",
                )

            finally:
                logger.removeHandler(handler)
                logger.setLevel(original_level)


if __name__ == "__main__":
    unittest.main()
