from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.agent_context_runtime import build_agent_runtime_context, context_prompt_fragment
from quantagent.agent_loop_v3 import build_agent_v3_plan, run_agent_loop_v3
from quantagent.mode_router import route_agent_mode, validate_mode_router
from quantagent.tool_call_transcript import list_tool_call_traces
from quantagent.tui_status_model import build_tui_status_model, render_tui_status_model


class AgentLoopV3ModeRouterTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent agent v3 ")

    def test_mode_router_classifies_core_intents(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            self.assertEqual(route_agent_mode(project, "设计一个补丁计划但不要改文件").mode, "plan")
            self.assertEqual(route_agent_mode(project, "实现 auto mode router 并接入 CLI").mode, "build")
            self.assertEqual(route_agent_mode(project, "review this diff for regression risk").mode, "review")
            self.assertEqual(route_agent_mode(project, "tests failed with traceback, repair it").mode, "repair")
            self.assertEqual(route_agent_mode(project, "学习源码思路看看怎么写的").mode, "research")
            self.assertEqual(route_agent_mode(project, "start MCP daemon and inspect approvals").mode, "admin")
            self.assertFalse([item for item in validate_mode_router(project) if item.level == "error"])

    def test_runtime_context_collects_mode_repo_checks_and_runtime(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "quantagent").mkdir()
            (project / "quantagent" / "sample.py").write_text("def route_agent_mode():\n    return 'build'\n", encoding="utf-8")
            checks = project / ".quantagent" / "checks"
            checks.mkdir(parents=True)
            (checks / "python.md").write_text(
                "---\nid: python-sample\nglobs: ['quantagent/*.py']\nrequired_patterns: ['route_agent_mode']\n---\nPython sample check.\n",
                encoding="utf-8",
            )

            context = build_agent_runtime_context(
                project,
                "实现 route_agent_mode",
                mode_name="build",
                changed_paths=("quantagent/sample.py",),
                tool_name="file_edit",
            )

            self.assertTrue(context.ok)
            self.assertEqual(context.mode, "build")
            by_name = {section.name: section for section in context.sections}
            self.assertIn("repo_map", by_name)
            self.assertIn("source_checks", by_name)
            self.assertEqual(by_name["mode_policy"].data["tool_decision"]["action"], "ask")
            self.assertIn("Mode-Aware Runtime Context", context_prompt_fragment(context))

    def test_agent_v3_runs_mode_aware_loop_and_records_trace(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "AI_协作交接").mkdir()
            (project / "CLAUDE.md").write_text("Use tests as evidence.\n", encoding="utf-8")
            (project / "AI_协作交接" / "handoff.md").write_text("Latest handoff.\n", encoding="utf-8")

            route = route_agent_mode(project, "实现一个小功能并自测")
            plan = build_agent_v3_plan("实现一个小功能并自测", route, include_validation=False)
            result = run_agent_loop_v3(project, "实现一个小功能并自测", explicit_mode="build", include_validation=False)
            traces = list_tool_call_traces(project, limit=10)

            self.assertTrue(plan)
            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.route.mode, "build")
            self.assertTrue(Path(result.trajectory_path).exists())
            self.assertTrue(any(trace.tool == "status" for trace in traces))
            payload = json.loads(Path(result.trajectory_path).read_text(encoding="utf-8").splitlines()[-1])
            self.assertEqual(payload["mode"], "build")

    def test_tui_status_model_surfaces_mode_context_panels(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            model = build_tui_status_model(project, task="review this diff", mode_name="review")
            rendered = render_tui_status_model(model)

            self.assertEqual(model.route.mode, "review")
            self.assertGreaterEqual(len(model.panels), 5)
            self.assertIn("Active Mode", rendered)


if __name__ == "__main__":
    unittest.main()
