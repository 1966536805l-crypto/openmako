from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.patch_engine import FileSnapshot, apply_replace, preview_replace, restore_snapshot, snapshot_file


class PatchEngineTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent patch engine ")

    def test_successful_replace_returns_diff_and_snapshot(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "strategy.py"
            target.write_text("threshold = 3\nprint(threshold)\n", encoding="utf-8")

            result = apply_replace(project, "strategy.py", "threshold = 3", "threshold = 5")

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(result.path, "strategy.py")
            self.assertIn("-threshold = 3", result.data["diff"])
            self.assertIn("+threshold = 5", result.data["diff"])
            self.assertIsInstance(result.data["snapshot"], FileSnapshot)
            self.assertEqual(target.read_text(encoding="utf-8"), "threshold = 5\nprint(threshold)\n")

    def test_context_disambiguates_duplicate_old_text(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "model.py"
            original = "def slow():\n    return value\n\ndef fast():\n    return value\n"
            target.write_text(original, encoding="utf-8")

            result = apply_replace(
                project,
                "model.py",
                "return value",
                "return value * 2",
                before="def fast():\n    ",
            )

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                "def slow():\n    return value\n\ndef fast():\n    return value * 2\n",
            )
            self.assertEqual(result.data["occurrences"], 2)
            self.assertEqual(result.data["contextual_occurrences"], 1)

    def test_failed_preview_or_replace_does_not_modify_file(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "dupes.txt"
            original = "same\nsame\n"
            target.write_text(original, encoding="utf-8")

            preview = preview_replace(project, "dupes.txt", "same", "other")
            result = apply_replace(project, "dupes.txt", "same", "other")

            self.assertFalse(preview.ok)
            self.assertFalse(result.ok)
            self.assertIn("expected 1 occurrence", result.summary)
            self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_restore_snapshot_restores_original_text(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "notes.txt"
            target.write_text("alpha\nbeta\n", encoding="utf-8")

            snap_result = snapshot_file(project, "notes.txt")
            self.assertTrue(snap_result.ok, snap_result.summary)
            target.write_text("changed\n", encoding="utf-8")

            restored = restore_snapshot(project, snap_result.data["snapshot"])

            self.assertTrue(restored.ok, restored.summary)
            self.assertEqual(target.read_text(encoding="utf-8"), "alpha\nbeta\n")


if __name__ == "__main__":
    unittest.main()
