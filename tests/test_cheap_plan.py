from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from quantagent.cheap_plan import build_cheap_plan, render_cheap_plan
from quantagent.cli import main
from quantagent.doctor import run_doctor


class CheapPlanTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent cheap plan ")

    def test_cheap_plan_is_local_and_free_first(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "CLAUDE.md").write_text("local rules\n", encoding="utf-8")

            plan = build_cheap_plan(project, "fix failing tests")
            rendered = render_cheap_plan(plan)

            self.assertEqual(plan.model_calls, 0)
            self.assertEqual(plan.context_mode, "standard")
            self.assertLessEqual(plan.estimated_tokens, plan.token_budget)
            self.assertTrue(any("doctor" in command for command in plan.free_first_commands))
            self.assertTrue(any("context" in command for command in plan.free_first_commands))
            self.assertIn("chat", plan.paid_next_step)
            self.assertIn("model_calls: 0", rendered)

    def test_chinese_fix_task_uses_standard_context(self) -> None:
        with self.make_project() as tmp:
            plan = build_cheap_plan(Path(tmp), "修复失败测试")

        self.assertEqual(plan.context_mode, "standard")
        self.assertGreaterEqual(plan.token_budget, 18_000)

    def test_cheap_cli_json_outputs_machine_readable_plan(self) -> None:
        with self.make_project() as tmp:
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(["--no-trust-prompt", "cheap", "--project", tmp, "--json", "fix", "tests"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertEqual(payload["model_calls"], 0)
            self.assertEqual(payload["task"], "fix tests")
            self.assertIn("free_first_commands", payload)

    def test_doctor_reports_cheap_first_check(self) -> None:
        with self.make_project() as tmp:
            checks = run_doctor(Path(tmp))
            cheap = next(check for check in checks if check.name == "cheap_first")

            self.assertTrue(cheap.ok)
            self.assertEqual(cheap.category, "cost")


if __name__ == "__main__":
    unittest.main()
