from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.project_rules import ProjectRule, load_project_rules, match_project_rules, render_project_rules, rule_matches_paths


class ProjectRulesTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent project rules ")

    def test_frontmatter_globs_and_always_apply_match_paths(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            rules = project / ".quantagent" / "rules"
            rules.mkdir(parents=True)
            (rules / "python.md").write_text(
                "---\n"
                "description: Python changes\n"
                "globs:\n"
                "  - '*.py'\n"
                "  - src/**/*.py\n"
                "  - tools/**\n"
                "---\n"
                "Prefer small functions.\n",
                encoding="utf-8",
            )
            cursor_rules = project / ".cursor" / "rules"
            cursor_rules.mkdir(parents=True)
            (cursor_rules / "always.md").write_text(
                "---\n"
                "alwaysApply: true\n"
                "---\n"
                "Run focused tests.\n",
                encoding="utf-8",
            )

            matched = match_project_rules(project, ["src/engine.py"])

            self.assertEqual([rule.source for rule in matched], [".quantagent/rules/python.md", ".cursor/rules/always.md"])
            self.assertEqual(matched[0].description, "Python changes")
            self.assertEqual(matched[0].globs, ["*.py", "src/**/*.py", "tools/**"])
            self.assertTrue(matched[1].always_apply)
            self.assertTrue(rule_matches_paths(ProjectRule("nested", "", globs=["src/**/*.py"]), ["src/engine.py"]))

    def test_comma_globs_and_root_rule_files_are_loaded(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            rules = project / ".cursor" / "rules"
            rules.mkdir(parents=True)
            (rules / "docs.md").write_text(
                "---\n"
                "globs: docs/**, README.md\n"
                "always_apply: false\n"
                "---\n"
                "Keep docs concise.\n",
                encoding="utf-8",
            )
            (project / "AGENTS.md").write_text("Repository-wide agent guidance.\n", encoding="utf-8")
            (project / "QUANTAGENT.md").write_text("QuantAgent project memory.\n", encoding="utf-8")

            loaded = load_project_rules(project)
            matched = match_project_rules(project, ["docs/guide.md"])
            rendered = render_project_rules(matched)

            self.assertEqual([rule.source for rule in loaded], [".cursor/rules/docs.md", "AGENTS.md", "QUANTAGENT.md"])
            self.assertEqual(loaded[0].globs, ["docs/**", "README.md"])
            self.assertIn(".cursor/rules/docs.md", rendered)
            self.assertIn("AGENTS.md", rendered)
            self.assertIn("Repository-wide agent guidance.", rendered)


if __name__ == "__main__":
    unittest.main()
