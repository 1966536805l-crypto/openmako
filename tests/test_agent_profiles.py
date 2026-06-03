from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from quantagent.agent_profiles import load_agent_profile_config, load_instructions, render_agent_profile, resolve_agent_permission
from quantagent.edit_loop import PatchPlan, PatchPlanFile, _run_patch_plan_from_patch_plan
from quantagent.mcp_runtime import call_mcp_tool
from quantagent.policy_gate import enforce_tool


class AgentProfileTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent agent profiles ")

    def test_builtin_profiles_gate_plan_and_build_permissions(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            config = load_agent_profile_config(project)

            plan_edit = enforce_tool("plan", "edit", project=project)
            build_mcp = resolve_agent_permission(project, "build", "mcp:fake:echo")

            self.assertEqual(config.default_agent, "build")
            self.assertIn("quant-auditor", config.agents)
            self.assertEqual(plan_edit.action, "deny")
            self.assertIsNotNone(build_mcp)
            self.assertEqual(build_mcp.action, "ask")

    def test_project_config_merges_agent_permissions_and_default(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(
                json.dumps(
                    {
                        "default_agent": "plan",
                        "agents": {
                            "plan": {"permission": {"shell": "deny"}},
                            "research": {"mode": "subagent", "permission": {"file_read": "allow", "*": "deny"}},
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = load_agent_profile_config(project)
            shell = enforce_tool("plan", "shell", project=project)
            research_read = enforce_tool("research", "file_read", project=project)

            self.assertEqual(config.default_agent, "plan")
            self.assertEqual(shell.action, "deny")
            self.assertEqual(research_read.action, "allow")
            self.assertEqual(config.agents["research"].mode, "subagent")

    def test_project_markdown_agent_loads_frontmatter_prompt_and_extras(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            agent_dir = project / ".quantagent" / "agents"
            agent_dir.mkdir(parents=True)
            (agent_dir / "researcher.md").write_text(
                """---
name: quant-researcher
description: Research market evidence
tools: [Read, Bash, file_search]
disallowedTools:
  - Edit
model: claude-sonnet
permissionMode: ask
maxTurns: 6
skills: [capacity, audit]
mcpServers:
  market:
    command: marketd
hooks:
  before_tool_call: inspect
memory: keep risk notes
effort: high
background: true
isolation: worktree
color: cyan
temperature: 0.2
---
You are the research agent.
Use evidence.
""",
                encoding="utf-8",
            )

            config = load_agent_profile_config(project)
            profile = config.agents["quant-researcher"]
            shell = resolve_agent_permission(project, "quant-researcher", "shell")
            edit = resolve_agent_permission(project, "quant-researcher", "edit")
            unknown = resolve_agent_permission(project, "quant-researcher", "experiment")
            rendered = render_agent_profile(profile)

            self.assertEqual(profile.mode, "subagent")
            self.assertEqual(profile.description, "Research market evidence")
            self.assertEqual(profile.prompt, "You are the research agent.\nUse evidence.")
            self.assertEqual(profile.model, "claude-sonnet")
            self.assertEqual(profile.steps, 6)
            self.assertEqual(profile.tools, ["Read", "Bash", "file_search"])
            self.assertEqual(profile.disallowed_tools, ["Edit"])
            self.assertEqual(profile.permission_mode, "ask")
            self.assertEqual(profile.skills, ["capacity", "audit"])
            self.assertEqual(profile.mcp_servers["market"]["command"], "marketd")
            self.assertEqual(profile.hooks["before_tool_call"], "inspect")
            self.assertEqual(profile.memory, "keep risk notes")
            self.assertEqual(profile.effort, "high")
            self.assertTrue(profile.background)
            self.assertEqual(profile.isolation, "worktree")
            self.assertEqual(profile.color, "cyan")
            self.assertEqual(profile.extra["temperature"], 0.2)
            self.assertIsNotNone(shell)
            self.assertIsNotNone(edit)
            self.assertIsNotNone(unknown)
            self.assertEqual(shell.action, "allow")
            self.assertEqual(edit.action, "deny")
            self.assertEqual(unknown.action, "deny")
            self.assertIn("tools: Read, Bash, file_search", rendered)
            self.assertIn("mcp_servers: market", rendered)
            self.assertIn("isolation: worktree", rendered)

    def test_markdown_agent_does_not_load_claude_paths_by_default(self) -> None:
        with self.make_project() as tmp, tempfile.TemporaryDirectory(prefix="quantagent home ") as home, tempfile.TemporaryDirectory(prefix="claude home ") as claude_home:
            project = Path(tmp)
            old_home = os.environ.get("QUANTAGENT_HOME")
            old_claude_home = os.environ.get("CLAUDE_HOME")
            old_import = os.environ.get("QUANTAGENT_LOAD_CLAUDE_AGENTS")
            try:
                os.environ["QUANTAGENT_HOME"] = home
                os.environ["CLAUDE_HOME"] = claude_home
                os.environ.pop("QUANTAGENT_LOAD_CLAUDE_AGENTS", None)
                global_claude_dir = Path(claude_home) / "agents"
                global_claude_dir.mkdir(parents=True)
                (global_claude_dir / "legacy.md").write_text(
                    "---\nname: legacy-only\ndescription: global claude\n---\nLegacy prompt.\n",
                    encoding="utf-8",
                )
                project_claude_dir = project / ".claude" / "agents"
                project_claude_dir.mkdir(parents=True)
                (project_claude_dir / "project-legacy.md").write_text(
                    "---\nname: project-legacy\ndescription: project claude\n---\nProject legacy prompt.\n",
                    encoding="utf-8",
                )

                config = load_agent_profile_config(project)

                self.assertNotIn("legacy-only", config.agents)
                self.assertNotIn("project-legacy", config.agents)
                self.assertFalse(any(".claude/agents" in source for source in config.sources))
            finally:
                _restore_env("QUANTAGENT_HOME", old_home)
                _restore_env("CLAUDE_HOME", old_claude_home)
                _restore_env("QUANTAGENT_LOAD_CLAUDE_AGENTS", old_import)

    def test_claude_agent_import_is_opt_in_and_quantagent_precedes_claude(self) -> None:
        with self.make_project() as tmp, tempfile.TemporaryDirectory(prefix="quantagent home ") as home, tempfile.TemporaryDirectory(prefix="claude home ") as claude_home:
            project = Path(tmp)
            old_home = os.environ.get("QUANTAGENT_HOME")
            old_claude_home = os.environ.get("CLAUDE_HOME")
            old_import = os.environ.get("QUANTAGENT_LOAD_CLAUDE_AGENTS")
            try:
                os.environ["QUANTAGENT_HOME"] = home
                os.environ["CLAUDE_HOME"] = claude_home
                os.environ["QUANTAGENT_LOAD_CLAUDE_AGENTS"] = "1"
                user_dir = Path(home) / "agents"
                user_dir.mkdir(parents=True)
                (user_dir / "shared.md").write_text(
                    "---\nname: shared\nmode: subagent\ndescription: user quantagent\n---\nUser prompt.\n",
                    encoding="utf-8",
                )
                project_claude_dir = project / ".claude" / "agents"
                project_claude_dir.mkdir(parents=True)
                (project_claude_dir / "shared.md").write_text(
                    "---\nname: shared\nmode: subagent\ndescription: project claude\n---\nClaude prompt.\n",
                    encoding="utf-8",
                )
                project_quantagent_dir = project / ".quantagent" / "agents"
                project_quantagent_dir.mkdir(parents=True)
                (project_quantagent_dir / "shared.md").write_text(
                    "---\nname: shared\nmode: subagent\ndescription: project quantagent\n---\nProject prompt.\n",
                    encoding="utf-8",
                )

                profile = load_agent_profile_config(project).agents["shared"]

                self.assertEqual(profile.description, "project quantagent")
                self.assertEqual(profile.prompt, "Project prompt.")
                self.assertIn(".quantagent/agents/shared.md", profile.source)
            finally:
                _restore_env("QUANTAGENT_HOME", old_home)
                _restore_env("CLAUDE_HOME", old_claude_home)
                _restore_env("QUANTAGENT_LOAD_CLAUDE_AGENTS", old_import)

    def test_env_and_managed_config_precedence(self) -> None:
        with self.make_project() as tmp, tempfile.TemporaryDirectory(prefix="quantagent home ") as home:
            project = Path(tmp)
            old_home = os.environ.get("QUANTAGENT_HOME")
            old_agent = os.environ.get("QUANTAGENT_AGENT")
            old_managed = os.environ.get("QUANTAGENT_MANAGED_CONFIG")
            managed = Path(tmp) / "managed.json"
            try:
                os.environ["QUANTAGENT_HOME"] = home
                os.environ["QUANTAGENT_AGENT"] = "plan"
                managed.write_text(json.dumps({"default_agent": "plan"}), encoding="utf-8")
                os.environ["QUANTAGENT_MANAGED_CONFIG"] = str(managed)

                config = load_agent_profile_config(project)

                self.assertEqual(config.default_agent, "plan")
                self.assertIn(str(managed), config.managed_sources)
            finally:
                _restore_env("QUANTAGENT_HOME", old_home)
                _restore_env("QUANTAGENT_AGENT", old_agent)
                _restore_env("QUANTAGENT_MANAGED_CONFIG", old_managed)

    def test_subagent_cannot_be_default_agent(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(json.dumps({"default_agent": "audit"}), encoding="utf-8")

            config = load_agent_profile_config(project)

            self.assertEqual(config.default_agent, "build")

    def test_instruction_loader_reads_project_rules(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "AGENTS.md").write_text("Use project rules.\n", encoding="utf-8")
            (project / "QUANTAGENT.md").write_text("QuantAgent memory.\n", encoding="utf-8")
            (project / ".quantagent" / "instructions").mkdir(parents=True)
            (project / ".quantagent" / "instructions" / "risk.md").write_text("Risk rule.\n", encoding="utf-8")

            instructions = load_instructions(project)
            texts = "\n".join(item.text for item in instructions)

            self.assertIn("Use project rules.", texts)
            self.assertIn("QuantAgent memory.", texts)
            self.assertIn("Risk rule.", texts)

    def test_plan_profile_blocks_patch_apply(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.txt").write_text("old\n", encoding="utf-8")
            plan = PatchPlan(
                task="plan must not edit",
                files=[PatchPlanFile("a.txt")],
                risks=["low"],
                test_command=[],
                unified_diff="--- a/a.txt\n+++ b/a.txt\n@@ -1,1 +1,1 @@\n-old\n+new\n",
            )

            result = _run_patch_plan_from_patch_plan(project, plan, apply=True, profile="plan")

            self.assertFalse(result.ok)
            self.assertIn("blocked", result.summary)
            self.assertEqual((project / "a.txt").read_text(encoding="utf-8"), "old\n")

    def test_agent_profile_blocks_mcp_tool_before_call(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            script = project / "fake_mcp.py"
            called = project / "called.txt"
            script.write_text(
                "import json, pathlib, sys\n"
                f"pathlib.Path({str(called)!r}).write_text('called')\n"
                "request = json.loads(sys.stdin.readline())\n"
                "print(json.dumps({'jsonrpc': '2.0', 'id': request.get('id'), 'result': {'content': []}}))\n",
                encoding="utf-8",
            )
            config_dir = project / ".quantagent"
            config_dir.mkdir()
            (config_dir / "config.json").write_text(json.dumps({"agents": {"locked": {"permission": {"mcp_*": "deny"}}}}), encoding="utf-8")
            (config_dir / "mcp_servers.json").write_text(json.dumps({"mcp_servers": {"fake": {"command": "python3", "args": [str(script)]}}}), encoding="utf-8")

            result = call_mcp_tool(project, "fake", "echo", {}, profile="locked")

            self.assertFalse(result.ok)
            self.assertIn("agent profile locked", result.error)
            self.assertFalse(called.exists())


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
