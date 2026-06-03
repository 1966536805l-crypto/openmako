from __future__ import annotations

import tempfile
import unittest
import shlex
import sys
from dataclasses import replace
from pathlib import Path

from quantagent.event_log import append_runtime_event, event_log_stats, read_runtime_events, replay_summary
from quantagent.permission_policy_v2 import PermissionPolicyV2, PermissionRuleV2, lint_permission_policy_v2
from quantagent.skill_pipeline import (
    approve_skill_proposal,
    bind_learning_effect_report_to_proposal,
    list_skill_proposals,
    propose_skill_from_trajectory,
    run_skill_eval_command,
)
from quantagent.task_graph import build_task_graph
from quantagent.task_state import add_task, update_task
from quantagent.tool_manifest_v2 import build_tool_manifest_catalog, find_tool_manifest
from quantagent.trajectory import record_action, record_observation, record_test


class ClaudeOpenClawHermesPortsTest(unittest.TestCase):
    def test_event_log_records_replayable_runtime_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            event = append_runtime_event(
                project,
                kind="tool_call",
                summary="ran shell test",
                status="succeeded",
                tool="shell",
                task_id="qa-0001",
                data={"command": "python -m unittest"},
                artifacts=["out.txt"],
            )

            events = read_runtime_events(project)
            stats = event_log_stats(events)
            replay = replay_summary(events)

        self.assertEqual(events[0].event_id, event.event_id)
        self.assertEqual(stats.by_kind["tool_call"], 1)
        self.assertIn("ran shell test", replay)

    def test_tool_manifest_v2_wraps_builtin_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            catalog = build_tool_manifest_catalog(Path(tmp))
            shell = find_tool_manifest(catalog, "shell")

        self.assertEqual(shell.permission.mode, "ask")
        self.assertTrue(shell.permission.requires_approval)
        self.assertIn("process", shell.runtime.side_effects)

    def test_permission_policy_v2_detects_shadow_and_conflict(self) -> None:
        policy = PermissionPolicyV2(
            rules=(
                PermissionRuleV2("ask-shell", "ask", tool="shell", priority=10),
                PermissionRuleV2("allow-shell", "allow", tool="shell", priority=10),
                PermissionRuleV2("shadow-shell", "ask", tool="shell", priority=1),
            )
        )

        lints = lint_permission_policy_v2(policy)

        self.assertTrue(any(item.level == "error" and item.rule_id == "allow-shell" for item in lints))
        self.assertTrue(any(item.level == "warning" and item.rule_id == "shadow-shell" for item in lints))

    def test_task_graph_joins_tasks_and_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            task = add_task(project, "parent task")
            update_task(project, task.id, status="passed", note="done")
            append_runtime_event(project, kind="task", summary="task finished", status="succeeded", task_id=task.id)

            graph = build_task_graph(project)

        self.assertTrue(any(node.node_id == task.id for node in graph.nodes))
        self.assertTrue(any(edge.relation == "emitted" for edge in graph.edges))

    def test_skill_pipeline_promotes_trajectory_with_human_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            trajectory = project / "run.jsonl"
            record_action(trajectory, "run narrow failing test", step=1, ok=True)
            record_observation(trajectory, "assertion failed because expected path was stale", step=2, ok=False)
            record_test(trajectory, "rerun narrow test passed", step=3, ok=True)

            proposal = propose_skill_from_trajectory(project, trajectory, name="stale-path-repair", triggers=("path", "test"))
            eval_snippet = 'print("eval passed")'
            eval_result = run_skill_eval_command(
                project,
                f"{shlex.quote(sys.executable)} -c {shlex.quote(eval_snippet)}",
                summary="targeted skill pipeline promotion test passed",
                evidence=("rerun narrow test passed",),
            )
            eval_result = replace(eval_result, learning_effect_report=bind_learning_effect_report_to_proposal(_valid_learning_effect_report(), proposal))
            installed = approve_skill_proposal(project, proposal.proposal_id, eval_result=eval_result)
            proposals = list_skill_proposals(project)
            installed_text = installed.read_text(encoding="utf-8")

            self.assertTrue(installed.exists())
            self.assertIn("Procedure:", installed_text)
            self.assertEqual(proposals[0].status, "approved")


def _valid_learning_effect_report() -> dict[str, object]:
    return {
        "status": "pass",
        "total": 1,
        "solved": {"no_learning": 0, "approved_learning": 1},
        "score_delta": 1.0,
        "comparisons": [
            {
                "task_id": "stale-path-repair",
                "no_learning": {
                    "task_id": "stale-path-repair",
                    "solved": False,
                    "steps": 4,
                    "failure_class": "assertion",
                    "evidence": ["narrow test failed before learning"],
                    "invalid_reason": "",
                },
                "approved_learning": {
                    "task_id": "stale-path-repair",
                    "solved": True,
                    "steps": 2,
                    "failure_class": "",
                    "evidence": ["narrow test passed after approved learning"],
                    "invalid_reason": "",
                },
                "score_delta": 1.0,
            }
        ],
    }


if __name__ == "__main__":
    unittest.main()
