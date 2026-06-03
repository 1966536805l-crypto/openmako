from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from quantagent.file_ops import (
    diff_exact_replace_preview,
    read_preview,
    replace_exact,
    resolve_project_path,
    search_text,
    unified_diff_preview,
    write_text,
)


class FileOpsTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent file ops ")

    def test_write_and_read_preview_stay_inside_project(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)

            written = write_text(project, "notes/review.md", "alpha\nbeta\n")
            preview = read_preview(project, "notes/review.md", max_chars=7)

            self.assertTrue(written.ok, written.summary)
            self.assertEqual(written.path, "notes/review.md")
            self.assertTrue(preview.ok, preview.summary)
            self.assertEqual(preview.data["preview"], "alpha\nb")
            self.assertTrue(preview.data["trimmed"])

            with self.assertRaises(ValueError):
                resolve_project_path(project, "../outside.txt")

    def test_diff_preview_and_exact_replace(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "strategy.py"
            target.write_text("threshold = 3\nprint(threshold)\n", encoding="utf-8")

            preview = diff_exact_replace_preview(project, "strategy.py", "threshold = 3", "threshold = 5")
            changed = replace_exact(project, "strategy.py", "threshold = 3", "threshold = 5")
            no_change = unified_diff_preview(project, "strategy.py", target.read_text(encoding="utf-8"))

            self.assertTrue(preview.ok, preview.summary)
            self.assertIn("-threshold = 3", preview.data["diff"])
            self.assertIn("+threshold = 5", preview.data["diff"])
            self.assertTrue(changed.ok, changed.summary)
            self.assertIn("threshold = 5", target.read_text(encoding="utf-8"))
            self.assertTrue(no_change.ok, no_change.summary)
            self.assertFalse(no_change.data["changed"])

    def test_replace_requires_expected_occurrence_count(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "dupes.txt"
            target.write_text("same\nsame\n", encoding="utf-8")

            result = replace_exact(project, "dupes.txt", "same", "other")

            self.assertFalse(result.ok)
            self.assertIn("expected 1 occurrence", result.summary)
            self.assertEqual(target.read_text(encoding="utf-8"), "same\nsame\n")

    @unittest.skipIf(shutil.which("rg") is None, "rg is not installed")
    def test_search_text_uses_rg_with_project_paths(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("alpha = 1\nneedle = alpha\n", encoding="utf-8")
            (project / "b.txt").write_text("needle in text\n", encoding="utf-8")

            result = search_text(project, "needle", glob="*.py")

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(len(result.data["matches"]), 1)
            self.assertEqual(result.data["matches"][0]["path"], "a.py")


if __name__ == "__main__":
    unittest.main()
