from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.agent_modes import (
    get_agent_mode,
    list_agent_modes,
    mode_tool_views,
    render_agent_mode,
    render_agent_modes,
    resolve_agent_mode_permission,
    validate_agent_modes,
)
from quantagent.policy_gate import enforce_tool


class AgentModesTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent agent modes ")

    def test_builtin_modes_cover_expected_boundaries(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            modes = {mode.name: mode for mode in list_agent_modes(project)}

            self.assertIn("plan", modes)
            self.assertIn("build", modes)
            self.assertIn("review", modes)
            self.assertIn("repair", modes)
            self.assertIn("research", modes)
            self.assertIn("admin", modes)
            self.assertEqual(modes["plan"].profile, "plan")
            self.assertEqual(modes["build"].source_checks, "enforced")
            self.assertEqual(modes["repair"].isolation, "worktree")
            self.assertIn("Agent Mode plan", render_agent_mode(modes["plan"]))
            self.assertIn("build", render_agent_modes(modes.values()))

    def test_mode_permission_overlay_feeds_policy_gate(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            plan_edit = resolve_agent_mode_permission(project, "plan", "file_edit")
            build_edit = resolve_agent_mode_permission(project, "build", "file_edit")
            approved_build = resolve_agent_mode_permission(project, "build", "file_edit", owner_approved=True)
            policy_plan = enforce_tool("plan", "file_edit", project=project)
            policy_build = enforce_tool("build", "file_edit", project=project, owner_approved=True)

            self.assertIsNotNone(plan_edit)
            self.assertEqual(plan_edit.action, "deny")
            self.assertFalse(plan_edit.allowed)
            self.assertEqual(build_edit.action, "ask")
            self.assertFalse(build_edit.allowed)
            self.assertTrue(approved_build.allowed)
            self.assertEqual(policy_plan.action, "deny")
            self.assertFalse(policy_plan.allowed)
            self.assertTrue(policy_build.allowed)
            self.assertIn("mode", policy_build.policy_reason)

    def test_mode_tool_views_use_tool_manifest_catalog(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            plan_tools = mode_tool_views(project, "plan")
            build_tools = mode_tool_views(project, "build")
            plan_by_name = {tool.tool: tool for tool in plan_tools}
            build_by_name = {tool.tool: tool for tool in build_tools}

            self.assertEqual(plan_by_name["shell"].action, "deny")
            self.assertEqual(build_by_name["shell"].action, "ask")
            self.assertEqual(build_by_name["py_compile"].action, "allow")
            self.assertTrue(build_by_name["shell"].requires_approval)
            self.assertIn("process", build_by_name["shell"].side_effects)

    def test_project_mode_config_can_override_or_add_modes(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            config = project / ".quantagent" / "modes.json"
            config.parent.mkdir(parents=True)
            config.write_text(
                json.dumps(
                    {
                        "modes": {
                            "safe-build": {
                                "description": "Custom safe build.",
                                "profile": "build",
                                "source_checks": "enforced",
                                "apply_gate": "required",
                                "default_action": "deny",
                                "rules": [
                                    {"action": "allow", "patterns": ["file_read", "repo-map"]},
                                    {"action": "ask", "patterns": ["file_edit"]},
                                ],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            mode = get_agent_mode(project, "safe-build")
            read_decision = resolve_agent_mode_permission(project, "safe-build", "file_read")
            edit_decision = resolve_agent_mode_permission(project, "safe-build", "file_edit")
            shell_decision = resolve_agent_mode_permission(project, "safe-build", "shell")

            self.assertTrue(mode.source.endswith(".quantagent/modes.json"))
            self.assertEqual(read_decision.action, "allow")
            self.assertEqual(edit_decision.action, "ask")
            self.assertEqual(shell_decision.action, "deny")
            self.assertFalse(validate_agent_modes(project))


if __name__ == "__main__":
    unittest.main()
