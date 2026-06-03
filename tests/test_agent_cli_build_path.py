from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
import warnings
from unittest import mock
from pathlib import Path

from quantagent.cli import main


class AgentCliBuildPathTest(unittest.TestCase):
    def test_default_agent_cli_build_path_writes_and_tests_hello(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent cli build ") as tmp:
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "agent",
                        "--project",
                        tmp,
                        "--json",
                        "create hello.py with greet function and test it",
                    ]
                )

            self.assertEqual(rc, 0, stdout.getvalue())
            project = Path(tmp)
            self.assertTrue((project / "hello.py").exists())
            self.assertTrue((project / "tests" / "test_hello.py").exists())

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["route"]["mode"], "build")
            observations = {item["name"]: item for item in payload["observations"]}
            self.assertTrue(observations["implement"]["ok"])
            self.assertTrue(observations["validate"]["ok"])
            self.assertTrue(observations["unit_tests"]["ok"])
            self.assertEqual(
                sorted(observations["implement"]["data"]["created_files"]),
                ["hello.py", "tests/__init__.py", "tests/test_hello.py"],
            )

    def test_default_agent_cli_build_path_does_not_call_legacy_tool_loop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent cli build ") as tmp:
            stdout = io.StringIO()

            with mock.patch("quantagent.cli.run_tool_loop", side_effect=AssertionError("legacy tool loop called")):
                with contextlib.redirect_stdout(stdout):
                    rc = main(
                        [
                            "--no-trust-prompt",
                            "agent",
                            "--project",
                            tmp,
                            "--json",
                            "create hello.py with greet function and test it",
                        ]
                    )

            self.assertEqual(rc, 0, stdout.getvalue())
            project = Path(tmp)
            self.assertEqual(
                [path.name for path in project.rglob("QUANTAGENT_AGENT_V3_LAST.json")],
                ["QUANTAGENT_AGENT_V3_LAST.json"],
            )
            self.assertEqual(list(project.rglob("QUANTAGENT_TOOL_LOOP_LAST.json")), [])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["route"]["mode"], "build")
            self.assertTrue(payload["ok"])

    def test_default_agent_cli_build_path_does_not_emit_v3_deprecation_warning(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent cli build ") as tmp:
            stdout = io.StringIO()

            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always", DeprecationWarning)
                with contextlib.redirect_stdout(stdout):
                    rc = main(
                        [
                            "--no-trust-prompt",
                            "agent",
                            "--project",
                            tmp,
                            "--json",
                            "create hello.py with greet function and test it",
                        ]
                    )

            self.assertEqual(rc, 0, stdout.getvalue())
            deprecation_messages = [
                str(warning.message)
                for warning in caught
                if issubclass(warning.category, DeprecationWarning)
            ]
            self.assertFalse(
                [message for message in deprecation_messages if "agent_loop_v3" in message],
                deprecation_messages,
            )

    def test_agent_cli_duration_fuse_stops_before_first_step(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent cli build ") as tmp:
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "agent",
                        "--project",
                        tmp,
                        "--json",
                        "--max-duration-seconds",
                        "0",
                        "create hello.py with greet function and test it",
                    ]
                )

            self.assertEqual(rc, 1, stdout.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["failure_class"], "timeout")
            self.assertEqual([item["name"] for item in payload["observations"]], ["task_timeout"])
            self.assertFalse((Path(tmp) / "hello.py").exists())

    def test_agent_cli_rejects_non_finite_duration_fuse(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main(
                    [
                        "--no-trust-prompt",
                        "agent",
                        "--project",
                        "/tmp",
                        "--max-duration-seconds",
                        "nan",
                        "create hello.py with greet function and test it",
                    ]
                )

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("finite non-negative", stderr.getvalue())

    def test_agent_cli_step_budget_stops_before_first_step(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent cli build ") as tmp:
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "agent",
                        "--project",
                        tmp,
                        "--json",
                        "--max-steps",
                        "0",
                        "create hello.py with greet function and test it",
                    ]
                )

            self.assertEqual(rc, 1, stdout.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["failure_class"], "step_limit")
            self.assertEqual([item["name"] for item in payload["observations"]], ["step_limit"])
            self.assertFalse((Path(tmp) / "hello.py").exists())

    def test_agent_v3_cli_step_budget_stops_before_first_step(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent cli build ") as tmp:
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "agent-v3",
                        "--project",
                        tmp,
                        "--json",
                        "--max-steps",
                        "0",
                        "create hello.py with greet function and test it",
                    ]
                )

            self.assertEqual(rc, 1, stdout.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["failure_class"], "step_limit")
            self.assertEqual([item["name"] for item in payload["observations"]], ["step_limit"])
            self.assertFalse((Path(tmp) / "hello.py").exists())

    def test_agent_v2_default_cli_step_budget_stops_before_first_step(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent cli build ") as tmp:
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "agent-v2",
                        "--project",
                        tmp,
                        "--json",
                        "--max-steps",
                        "0",
                        "create hello.py with greet function and test it",
                    ]
                )

            self.assertEqual(rc, 1, stdout.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["failure_class"], "step_limit")
            self.assertFalse((Path(tmp) / "hello.py").exists())

    def test_headless_cli_step_budget_stops_before_first_step(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent cli build ") as tmp:
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "headless",
                        "--project",
                        tmp,
                        "--json",
                        "--max-steps",
                        "0",
                        "create hello.py with greet function and test it",
                    ]
                )

            self.assertEqual(rc, 1, stdout.getvalue())
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["request"]["max_steps"], 0)
            self.assertEqual(payload["agent"]["failure_class"], "step_limit")
            self.assertEqual([item["name"] for item in payload["agent"]["observations"]], ["step_limit"])
            self.assertFalse((Path(tmp) / "hello.py").exists())

    def test_agent_cli_rejects_negative_step_budget(self) -> None:
        stderr = io.StringIO()

        with contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main(
                    [
                        "--no-trust-prompt",
                        "agent",
                        "--project",
                        "/tmp",
                        "--max-steps",
                        "-1",
                        "create hello.py with greet function and test it",
                    ]
                )

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("non-negative integer", stderr.getvalue())

    def test_default_agent_cli_build_path_rejects_absolute_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent cli build ") as project_tmp:
            with tempfile.TemporaryDirectory(prefix="quantagent cli outside ") as outside_tmp:
                outside = Path(outside_tmp) / "escape.py"
                stdout = io.StringIO()

                with contextlib.redirect_stdout(stdout):
                    rc = main(
                        [
                            "--no-trust-prompt",
                            "agent",
                            "--project",
                            project_tmp,
                            "--json",
                            f"create {outside} with malicious code",
                        ]
                    )

                self.assertEqual(rc, 1, stdout.getvalue())
                self.assertFalse(outside.exists())

                payload = json.loads(stdout.getvalue())
                self.assertFalse(payload["ok"])
                self.assertEqual(payload["route"]["mode"], "build")

                observations = {item["name"]: item for item in payload["observations"]}
                implement = observations["implement"]
                self.assertFalse(implement["ok"])
                self.assertEqual(implement["data"]["files_touched"], [])
                self.assertEqual(implement["data"]["created_files"], [])
                self.assertIn("absolute path", implement["data"]["planner"]["error"])

    def test_default_agent_cli_build_path_rejects_unsupported_create_without_writing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent cli build ") as tmp:
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "agent",
                        "--project",
                        tmp,
                        "--json",
                        "create calculator.py with add function and test it",
                    ]
                )

            self.assertEqual(rc, 1, stdout.getvalue())
            project = Path(tmp)
            self.assertFalse((project / "calculator.py").exists())
            self.assertFalse((project / "tests" / "test_calculator.py").exists())

            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["route"]["mode"], "build")

            observations = {item["name"]: item for item in payload["observations"]}
            implement = observations["implement"]
            self.assertFalse(implement["ok"])
            self.assertEqual(implement["data"]["files_touched"], [])
            self.assertEqual(implement["data"]["created_files"], [])
            self.assertIn("unsupported", implement["data"]["planner"]["error"])
            self.assertNotIn("validate", observations)
            self.assertNotIn("unit_tests", observations)


if __name__ == "__main__":
    unittest.main()
