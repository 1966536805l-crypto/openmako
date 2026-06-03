from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.path_policy import assess_project_path, resolve_project_path


class PathPolicyTests(unittest.TestCase):
    def temp_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent path policy ")

    def test_project_escape_is_denied(self) -> None:
        with self.temp_project() as tmp:
            project = Path(tmp)
            decision = assess_project_path(project, "../outside.txt", operation="read")

            self.assertEqual(decision.action, "deny")
            self.assertEqual(decision.level, "L4_PROJECT_ESCAPE")
            with self.assertRaises(ValueError):
                resolve_project_path(project, "../outside.txt")

    def test_symlink_escape_is_denied_when_supported(self) -> None:
        with self.temp_project() as tmp, tempfile.TemporaryDirectory(prefix="quantagent outside ") as outside_tmp:
            project = Path(tmp)
            outside = Path(outside_tmp)
            link = project / "linked_outside"
            try:
                link.symlink_to(outside, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"symlink unavailable: {exc}")

            decision = assess_project_path(project, link / "escaped.txt", operation="read")

            self.assertEqual(decision.action, "deny")
            self.assertEqual(decision.level, "L4_PROJECT_ESCAPE")

    def test_raw_tick_write_is_denied(self) -> None:
        with self.temp_project() as tmp:
            project = Path(tmp)

            raw_decision = assess_project_path(project, "data/raw_prices.csv", operation="write")
            tick_decision = assess_project_path(project, "data/tick_prices.csv", operation="write")

            self.assertEqual(raw_decision.action, "deny")
            self.assertEqual(raw_decision.level, "L4_RAW_DATA_PROTECTED")
            self.assertEqual(tick_decision.action, "deny")
            self.assertEqual(tick_decision.level, "L4_RAW_DATA_PROTECTED")

    def test_quantagent_dir_write_is_allowed(self) -> None:
        with self.temp_project() as tmp:
            project = Path(tmp)
            decision = assess_project_path(project, ".quantagent/tool_results/out.txt", operation="write")

            self.assertEqual(decision.action, "allow")
            self.assertEqual(decision.level, "L1_PROJECT_OUTPUT")

    def test_communication_dir_write_is_allowed(self) -> None:
        with self.temp_project() as tmp:
            project = Path(tmp)
            decision = assess_project_path(project, "AI_协作交接/report.md", operation="write")

            self.assertEqual(decision.action, "allow")
            self.assertEqual(decision.level, "L1_PROJECT_OUTPUT")

    def test_source_file_write_asks(self) -> None:
        with self.temp_project() as tmp:
            project = Path(tmp)
            decision = assess_project_path(project, "strategy.py", operation="write")

            self.assertEqual(decision.action, "ask")
            self.assertEqual(decision.level, "L2_PROJECT_WRITE")

    def test_read_inside_project_is_allowed(self) -> None:
        with self.temp_project() as tmp:
            project = Path(tmp)
            decision = assess_project_path(project, "strategy.py", operation="read")

            self.assertEqual(decision.action, "allow")
            self.assertEqual(decision.level, "L0_PROJECT_READ")


if __name__ == "__main__":
    unittest.main()

