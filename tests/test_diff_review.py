from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.diff_review import render_diff_review_report, review_changed_files


class DiffReviewTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent diff review ")

    def test_review_catches_todo_and_python_syntax_error(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "alpha.py").write_text("# TODO: tighten validation\nvalue = 1\n", encoding="utf-8")
            (project / "bad.py").write_text("def broken(:\n    return 1\n", encoding="utf-8")

            report = review_changed_files(project, ["alpha.py", "bad.py"])

            titles = {finding.title for finding in report.findings}
            self.assertIn("TODO comment", titles)
            self.assertIn("Python syntax error", titles)
            self.assertTrue(any(finding.path == "alpha.py" and finding.line == 1 for finding in report.findings))
            self.assertTrue(any(finding.path == "bad.py" and finding.line == 1 for finding in report.findings))

    def test_renderer_leads_with_findings_and_includes_rules_paths_and_diff(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            rules = project / ".quantagent" / "rules"
            rules.mkdir(parents=True)
            (rules / "python.md").write_text(
                "---\n"
                "description: Python review\n"
                "globs: '*.py'\n"
                "---\n"
                "Check syntax before handoff.\n",
                encoding="utf-8",
            )
            (project / "alpha.py").write_text("# FIXME: remove placeholder\nvalue = 1\n", encoding="utf-8")

            report = review_changed_files(project, ["alpha.py"])
            rendered = render_diff_review_report(report)

            self.assertLess(rendered.index("## Findings"), rendered.index("## Included Rules"))
            self.assertIn("alpha.py:1", rendered)
            self.assertIn(".quantagent/rules/python.md", rendered)
            self.assertIn("Check syntax before handoff.", rendered)
            self.assertIn("+++ b/alpha.py", rendered)


if __name__ == "__main__":
    unittest.main()
