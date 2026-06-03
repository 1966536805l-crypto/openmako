from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from quantagent.agent_v2 import AgentStep, build_agent_v2_plan, classify_failure, run_agent_v2
from quantagent.runtime_store import runtime_db_path


class AgentV2Test(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent agent v2 ")

    def test_plan_adds_quant_guard_for_p4_task(self) -> None:
        plan = build_agent_v2_plan("P4 PF claim needs slippage evidence")
        names = [step.name for step in plan]

        self.assertIn("context", names)
        self.assertIn("audit", names)
        self.assertIn("validate", names)
        self.assertIn("claim_guard", names)
        self.assertEqual(names[-1], "memory_extract")

    def test_run_agent_v2_records_trajectory(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "tests").mkdir()
            (project / "tests" / "test_ok.py").write_text(
                "import unittest\n\nclass Ok(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            plan = [
                AgentStep("status", "tool", {"tool": "status", "args": {}}),
                AgentStep(
                    "tests",
                    "command",
                    {"command": ["python3", "-m", "unittest", "discover", "-s", "tests"], "allow_risky": True},
                ),
                AgentStep("memory_extract", "memory_extract", {}, required=False),
            ]

            result = run_agent_v2(project, "run tests", plan=plan)
            trajectory = Path(result.trajectory_path)

            self.assertTrue(result.ok, result.summary)
            self.assertTrue(trajectory.exists())
            payload = json.loads(trajectory.read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(payload["task"], "run tests")
            self.assertEqual(len(payload["observations"]), 3)

    def test_run_agent_v2_persists_skill_snapshot(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            result = run_agent_v2(project, "P4逐笔验证要检查滑点容量和证据hash", plan=[AgentStep("status", "tool", {"tool": "status", "args": {}})])
            conn = sqlite3.connect(runtime_db_path(project))
            try:
                row = conn.execute("SELECT id, skills_json FROM skill_snapshots").fetchone()
                start = conn.execute("SELECT data_json FROM query_events WHERE kind = 'query_start'").fetchone()
            finally:
                conn.close()

            self.assertTrue(result.ok, result.summary)
            self.assertIsNotNone(row)
            self.assertIn("p4-tick-validation", row[1])
            self.assertIn(row[0], start[0])

    def test_required_failure_marks_result_failed(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            plan = [AgentStep("bad", "command", {"command": ["python3", "-c", "raise SystemExit(7)"], "allow_risky": True})]

            result = run_agent_v2(project, "bad command", plan=plan)

            self.assertFalse(result.ok)
            self.assertEqual(result.failure_class, "tool_failed")
            self.assertIn("bad", result.summary)

    def test_classifies_validation_failures(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            plan = [
                AgentStep(
                    "unit_tests",
                    "command",
                    {
                        "command": ["python3", "-c", "import sys; sys.stderr.write('unittest failed'); raise SystemExit(1)"],
                        "allow_risky": True,
                    },
                )
            ]

            result = run_agent_v2(project, "run unittest", plan=plan)

            self.assertEqual(classify_failure(result.observations), "verification_failed")


if __name__ == "__main__":
    unittest.main()
