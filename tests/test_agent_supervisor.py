from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent.agent_supervisor import build_supervisor_plan, load_agent_supervisor_runs, refresh_agent_supervisor, run_agent_supervisor
from quantagent.cli import main
from quantagent.subagents import SubagentRecord
from quantagent.task_state import FAILED, PASSED, RUNNING, load_tasks


class AgentSupervisorTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent supervisor ")

    def fake_subagent(self, role: str = "researcher", status: str = RUNNING) -> SubagentRecord:
        return SubagentRecord(
            subagent_id="sub-" + role,
            parent_task_id="qa-0001",
            child_task_id="qrt-" + role,
            child_session_id="session-" + role,
            task="child task",
            agent_profile="audit",
            status=status,
        )

    def test_build_plan_splits_quant_task_into_readonly_quant_and_verifier_roles(self) -> None:
        with self.make_project() as tmp:
            plan = build_supervisor_plan(Path(tmp), "这个策略 PF 和实盘滑点咋样", include_validation=True)
            roles = [item.role for item in plan]

            self.assertIn("researcher", roles)
            self.assertIn("quant-execution", roles)
            self.assertIn("verifier", roles)
            self.assertNotIn("coder", roles)
            self.assertEqual(next(item for item in plan if item.role == "quant-execution").agent_profile, "quant-auditor")
            self.assertEqual(next(item for item in plan if item.role == "quant-execution").depends_on, ("researcher",))

    def test_build_plan_uses_isolated_coder_for_build_tasks(self) -> None:
        with self.make_project() as tmp:
            plan = build_supervisor_plan(Path(tmp), "修一下 agent 调度 bug", changed_paths=["quantagent/agent_loop_v3.py"])
            coder = next(item for item in plan if item.role == "coder")

            self.assertEqual(coder.context_mode, "isolated")
            self.assertTrue(coder.isolate_worktree)
            self.assertEqual(coder.agent_profile, "build")
            self.assertEqual(coder.depends_on, ("researcher",))

    def test_plan_only_writes_supervisor_artifact_without_launching_children(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            run = run_agent_supervisor(project, "这个策略咋样", plan_only=True)
            tasks = load_tasks(project)
            saved = load_agent_supervisor_runs(project)

            self.assertTrue(run.ok)
            self.assertEqual(run.action, "plan")
            self.assertEqual(tasks[0].status, PASSED)
            self.assertFalse(run.launches)
            self.assertEqual(saved[-1].supervisor_id, run.supervisor_id)

    def test_supervisor_initial_launch_starts_only_ready_root_nodes(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            def _fake_start(*args, **kwargs):
                title = kwargs.get("title", "researcher")
                role = str(title).split(":", 1)[0]
                return self.fake_subagent(role)

            with patch("quantagent.agent_supervisor.start_subagent", side_effect=_fake_start) as start:
                run = run_agent_supervisor(project, "修一下 agent 调度 bug", changed_paths=["quantagent/agent_loop_v3.py"])

            self.assertTrue(run.ok)
            self.assertEqual(run.action, "launch")
            self.assertTrue(run.parent_task_id)
            self.assertEqual(start.call_count, 1)
            self.assertTrue(all(call.kwargs["parent_task_id"] == run.parent_task_id for call in start.call_args_list))
            self.assertEqual(run.launches[0].role, "researcher")
            self.assertEqual(run.node_status["coder"], "waiting")

    def test_supervisor_refresh_advances_dag_after_dependency_passes(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            with patch("quantagent.agent_supervisor.start_subagent", return_value=self.fake_subagent("researcher")):
                run = run_agent_supervisor(project, "修一下 agent 调度 bug", changed_paths=["quantagent/agent_loop_v3.py"])

            def _fake_start(*args, **kwargs):
                title = kwargs.get("title", "coder")
                role = str(title).split(":", 1)[0]
                return self.fake_subagent(role)

            with patch("quantagent.agent_supervisor.refresh_subagents", return_value=[self.fake_subagent("researcher", PASSED)]), patch(
                "quantagent.agent_supervisor.start_subagent", side_effect=_fake_start
            ):
                refreshed = refresh_agent_supervisor(project, run.parent_task_id)

            self.assertIsNotNone(refreshed)
            assert refreshed is not None
            self.assertEqual(refreshed.node_status["researcher"], PASSED)
            self.assertEqual(refreshed.node_status["coder"], RUNNING)
            self.assertTrue(any(launch.role == "coder" for launch in refreshed.launches))

    def test_supervisor_refresh_adds_repair_node_for_failed_required_child(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            with patch("quantagent.agent_supervisor.start_subagent", return_value=self.fake_subagent("researcher")):
                run = run_agent_supervisor(project, "修一下 agent 调度 bug", changed_paths=["quantagent/agent_loop_v3.py"])
            with patch("quantagent.agent_supervisor.refresh_subagents", return_value=[self.fake_subagent("researcher", PASSED)]), patch(
                "quantagent.agent_supervisor.start_subagent", return_value=self.fake_subagent("coder")
            ):
                refresh_agent_supervisor(project, run.parent_task_id)

            records = [self.fake_subagent("researcher", PASSED), self.fake_subagent("coder", FAILED)]
            with patch("quantagent.agent_supervisor.refresh_subagents", return_value=records), patch(
                "quantagent.agent_supervisor.start_subagent", return_value=self.fake_subagent("repair-coder")
            ):
                repaired = refresh_agent_supervisor(project, run.parent_task_id)

            self.assertIsNotNone(repaired)
            assert repaired is not None
            self.assertIn("repair-coder", [item.role for item in repaired.plan])
            self.assertEqual(repaired.node_status["coder"], FAILED)
            self.assertEqual(repaired.node_status["repair-coder"], RUNNING)

    def test_agent_cli_supports_supervisor_plan_only(self) -> None:
        with self.make_project() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "agent", "--project", tmp, "--subagents", "plan-only", "--json", "这个策略咋样"])
            payload = json.loads(stdout.getvalue())

            self.assertEqual(rc, 0)
            self.assertEqual(payload["action"], "plan")
            self.assertTrue(any(item["role"] == "quant-execution" for item in payload["plan"]))

    def test_agent_supervisor_cli_show_latest(self) -> None:
        with self.make_project() as tmp:
            run_agent_supervisor(Path(tmp), "这个策略咋样", plan_only=True)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "agent-supervisor", "--project", tmp, "show", "--json"])
            payload = json.loads(stdout.getvalue())

            self.assertEqual(rc, 0)
            self.assertEqual(payload["action"], "plan")


if __name__ == "__main__":
    unittest.main()
