from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.context_providers import gather_context_providers, parse_context_refs, render_context_provider_results


class ContextProvidersTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent context providers ")

    def test_parse_context_refs_supports_arguments(self) -> None:
        refs = parse_context_refs('fix @file:"src/app.py" with @problems and @repo-map')

        self.assertEqual(refs[0].provider, "file")
        self.assertEqual(refs[0].argument, "src/app.py")
        self.assertEqual(refs[1].provider, "problems")
        self.assertEqual(refs[2].provider, "repo-map")

    def test_file_tree_and_problems_providers_render(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "src").mkdir()
            (project / "src" / "app.py").write_text("# TODO: fix later\nx = 1\n", encoding="utf-8")

            results = gather_context_providers(project, ["@file:src/app.py", "@tree:src", "@problems"])
            rendered = render_context_provider_results(results)

            self.assertTrue(all(item.ok for item in results))
            self.assertIn("# TODO: fix later", rendered)
            self.assertIn("app.py", rendered)
            self.assertIn("todo_comment", rendered)

    def test_outside_project_file_is_blocked(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            results = gather_context_providers(project, ["@file:/etc/hosts"])

            self.assertFalse(results[0].ok)
            self.assertIn("outside project", results[0].body)


if __name__ == "__main__":
    unittest.main()
