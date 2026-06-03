from __future__ import annotations

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent.tool_execution import execute_tool


class DesktopEvalToolExecutionTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="desktop eval tool execution ")

    def fake_desktop_eval_module(self, calls: list[dict[str, object]]) -> types.ModuleType:
        module = types.ModuleType("quantagent.desktop_eval")

        class EvalResult:
            ok = True
            status = "passed"
            summary = "desktop eval passed"

            def to_payload(self) -> dict[str, object]:
                return {"ok": self.ok, "status": self.status, "summary": self.summary, "cases": 1}

            def to_json(self) -> str:
                return '{"ok":true,"status":"passed"}'

        def run_desktop_eval(project: Path, **kwargs: object) -> EvalResult:
            calls.append({"project": project, **kwargs})
            return EvalResult()

        def render_desktop_eval_result(result: EvalResult, json: bool = False) -> str:
            return '{"status":"passed"}' if json else "# Desktop Eval\n\npassed\n"

        module.run_desktop_eval = run_desktop_eval
        module.render_desktop_eval_result = render_desktop_eval_result
        return module

    def test_desktop_eval_fails_closed_when_runner_module_is_missing(self) -> None:
        with self.make_project() as tmp, patch("quantagent.tool_execution.importlib.import_module", side_effect=ImportError("missing desktop_eval")):
            result = execute_tool(Path(tmp), "desktop.eval")

        self.assertFalse(result.ok)
        self.assertTrue(result.blocked)
        self.assertEqual(result.error_kind, "missing_dependency")
        self.assertIn("Desktop eval runner unavailable", result.summary)

    def test_desktop_eval_dry_run_strips_execution_flags_without_owner_approval(self) -> None:
        calls: list[dict[str, object]] = []
        module = self.fake_desktop_eval_module(calls)
        with self.make_project() as tmp, patch.dict(sys.modules, {"quantagent.desktop_eval": module}):
            result = execute_tool(
                Path(tmp),
                "desktop.eval",
                {
                    "suite": "smoke",
                    "scenario": "search",
                    "duration_minutes": 0.25,
                    "max_steps": 3,
                    "execute": True,
                    "reviewed": True,
                    "allow_actions": True,
                    "stop_file": "STOP",
                    "json": True,
                },
            )

        self.assertTrue(result.ok, result.summary)
        self.assertEqual(result.name, "desktop.eval")
        self.assertEqual(result.policy["action"], "ask")
        self.assertFalse(result.policy["allowed"])
        self.assertEqual(calls[0]["suite"], "smoke")
        self.assertEqual(calls[0]["scenario"], "search")
        self.assertEqual(calls[0]["duration_minutes"], 0.25)
        self.assertEqual(calls[0]["max_steps"], 3)
        self.assertEqual(calls[0]["stop_file"], "STOP")
        self.assertFalse(calls[0]["execute"])
        self.assertFalse(calls[0]["reviewed"])
        self.assertFalse(calls[0]["allow_actions"])
        self.assertIn("json", result.data)
        self.assertEqual(result.data["json"], '{"ok":true,"status":"passed"}')

    def test_desktop_eval_owner_approval_allows_execution_flags(self) -> None:
        calls: list[dict[str, object]] = []
        module = self.fake_desktop_eval_module(calls)
        with self.make_project() as tmp, patch.dict(sys.modules, {"quantagent.desktop_eval": module}):
            result = execute_tool(
                Path(tmp),
                "desktop.eval",
                {"execute": True, "reviewed": True, "allow_actions": True},
                owner_approved=True,
            )

        self.assertTrue(result.ok, result.summary)
        self.assertTrue(result.policy["allowed"])
        self.assertTrue(calls[0]["execute"])
        self.assertTrue(calls[0]["reviewed"])
        self.assertTrue(calls[0]["allow_actions"])
        self.assertIn("markdown", result.data)


if __name__ == "__main__":
    unittest.main()
