from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.apply_gate import apply_review_with_gate, evaluate_apply_gate
from quantagent.worktree_isolation import create_isolated_worktree, create_isolation_review


class ApplyGateTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent apply gate ")

    def create_review(self, project: Path, path: str, source_text: str, isolated_text: str) -> str:
        target = project / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source_text, encoding="utf-8")
        worktree = create_isolated_worktree(project, include=[path])
        isolated_target = Path(worktree.workspace_path) / path
        isolated_target.parent.mkdir(parents=True, exist_ok=True)
        isolated_target.write_text(isolated_text, encoding="utf-8")
        return create_isolation_review(project, worktree.worktree_id).review_id

    def finding_codes(self, verdict) -> set[str]:
        return {finding.code for finding in verdict.findings}

    def test_evaluate_blocks_preview_that_requires_unapproved_apply(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            review_id = self.create_review(project, "module.py", "VALUE = 1\n", "VALUE = 2\n")

            verdict = evaluate_apply_gate(project, review_id, allow_no_tests=True)

            self.assertFalse(verdict.allowed)
            self.assertEqual(verdict.status, "blocked")
            self.assertIn("approval_required", self.finding_codes(verdict))

    def test_apply_approved_review_with_passing_tests_creates_checkpoint(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            review_id = self.create_review(project, "module.py", "VALUE = 1\n", "VALUE = 2\n")

            result = apply_review_with_gate(project, review_id, approved=True, test_command=["true"])

            self.assertTrue(result.ok, result.summary)
            self.assertTrue(result.applied)
            self.assertFalse(result.rolled_back)
            self.assertTrue(result.checkpoint_id)
            self.assertEqual(result.test_returncode, 0)
            self.assertEqual((project / "module.py").read_text(encoding="utf-8"), "VALUE = 2\n")
            self.assertTrue((project / ".quantagent" / "checkpoints" / f"{result.checkpoint_id}.json").exists())

    def test_post_apply_test_failure_rolls_back_project_file(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            review_id = self.create_review(project, "module.py", "VALUE = 1\n", "VALUE = 2\n")

            result = apply_review_with_gate(project, review_id, approved=True, test_command=["false"])

            self.assertFalse(result.ok)
            self.assertTrue(result.applied)
            self.assertTrue(result.rolled_back)
            self.assertEqual(result.test_returncode, 1)
            self.assertEqual((project / "module.py").read_text(encoding="utf-8"), "VALUE = 1\n")

    def test_python_diagnostic_blocks_gate_unless_allowed(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            review_id = self.create_review(
                project,
                "module.py",
                "def value():\n    return 1\n",
                "def value(:\n    return 2\n",
            )

            blocked = evaluate_apply_gate(project, review_id, approved=True, allow_no_tests=True)
            allowed = evaluate_apply_gate(
                project,
                review_id,
                approved=True,
                allow_no_tests=True,
                allow_diagnostic_errors=True,
            )

            self.assertFalse(blocked.allowed)
            self.assertIn("diagnostic_error", self.finding_codes(blocked))
            self.assertTrue(allowed.allowed, [finding.to_dict() for finding in allowed.findings])
            self.assertNotIn("diagnostic_error", self.finding_codes(allowed))

    def test_source_check_failure_blocks_gate(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            checks = project / ".quantagent" / "checks"
            checks.mkdir(parents=True)
            (checks / "require-value-two.md").write_text(
                "---\n"
                "id: require-value-two\n"
                "globs:\n"
                "  - \"module.py\"\n"
                "required_patterns:\n"
                "  - \"VALUE = 2\"\n"
                "---\n"
                "Module must expose the repaired value.\n",
                encoding="utf-8",
            )
            review_id = self.create_review(project, "module.py", "VALUE = 1\n", "VALUE = 3\n")

            verdict = evaluate_apply_gate(project, review_id, approved=True, allow_no_tests=True)

            self.assertFalse(verdict.allowed)
            self.assertIn("source_check_failed", self.finding_codes(verdict))

    def test_source_check_warning_does_not_block_gate(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            checks = project / ".quantagent" / "checks"
            checks.mkdir(parents=True)
            (checks / "warn-print.md").write_text(
                "---\n"
                "id: warn-print\n"
                "severity: warning\n"
                "globs:\n"
                "  - \"module.py\"\n"
                "forbidden_patterns:\n"
                "  - \"print\\\\(\"\n"
                "---\n"
                "Avoid debug prints.\n",
                encoding="utf-8",
            )
            review_id = self.create_review(project, "module.py", "VALUE = 1\n", "VALUE = 2\nprint('debug')\n")

            verdict = evaluate_apply_gate(project, review_id, approved=True, allow_no_tests=True)

            self.assertTrue(verdict.allowed, [finding.to_dict() for finding in verdict.findings])
            warnings = [finding for finding in verdict.findings if finding.code == "source_check_failed"]
            self.assertEqual(warnings[0].level, "warn")


if __name__ == "__main__":
    unittest.main()
