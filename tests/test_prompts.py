from __future__ import annotations

import unittest

from quantagent.prompts import (
    build_subagent_system_prompt,
    build_system_prompt,
    build_tool_loop_system_prompt,
    prompt_manifest,
)
from quantagent.tool_loop import SYSTEM_PROMPT


class PromptArchitectureTest(unittest.TestCase):
    def test_default_prompt_contains_quant_specific_layers(self) -> None:
        prompt = build_system_prompt()

        self.assertIn("Mako Role", prompt)
        self.assertIn("Tool Discipline", prompt)
        self.assertIn("Safety Boundary", prompt)
        self.assertIn("Quant Evidence Rules", prompt)
        self.assertIn("Memory And Compaction", prompt)
        self.assertIn("Reporting Discipline", prompt)
        self.assertIn("raw/tick/level2", prompt.lower())
        self.assertIn("Stop Verification", prompt)

    def test_tool_loop_prompt_keeps_json_contract(self) -> None:
        prompt = build_tool_loop_system_prompt()

        self.assertIn("Return only JSON", prompt)
        self.assertIn('"tool_calls"', prompt)
        self.assertIn('"final"', prompt)
        self.assertEqual(SYSTEM_PROMPT, prompt)

    def test_subagent_prompt_adds_role_without_losing_contract(self) -> None:
        prompt = build_subagent_system_prompt("auditor")

        self.assertIn("Subagent Contract", prompt)
        self.assertIn("Assigned Role", prompt)
        self.assertIn("auditor", prompt)

    def test_prompt_manifest_is_small_and_stable(self) -> None:
        manifest = prompt_manifest()
        keys = [item["key"] for item in manifest]

        self.assertIn("core_agent", keys)
        self.assertIn("tool_discipline", keys)
        self.assertIn("memory_compaction", keys)
        self.assertIn("reporting_discipline", keys)
        self.assertIn("stop_verification", keys)
        self.assertTrue(all(set(item) == {"key", "title", "cacheable"} for item in manifest))

    def test_prompts_are_original_quantagent_text(self) -> None:
        prompt = build_tool_loop_system_prompt()

        self.assertNotIn("Claude Code", prompt)
        self.assertNotIn("Anthropic", prompt)
        self.assertNotIn("claude", prompt.lower())


if __name__ == "__main__":
    unittest.main()
