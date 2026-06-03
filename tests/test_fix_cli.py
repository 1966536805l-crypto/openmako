from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from quantagent.cli import main


class FixCliTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent fix cli ")

    def test_fix_preview_does_not_modify_file(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "a.txt"
            target.write_text("old\n", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "fix",
                        "replace value",
                        "--project",
                        tmp,
                        "--path",
                        "a.txt",
                        "--old",
                        "old",
                        "--new",
                        "new",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "old\n")
            self.assertIn("Next: rerun with `--apply`", stdout.getvalue())

    def test_fix_apply_runs_exact_replacement_without_review_flag(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            target = project / "a.txt"
            target.write_text("old\n", encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(
                    [
                        "--no-trust-prompt",
                        "fix",
                        "replace value",
                        "--project",
                        tmp,
                        "--path",
                        "a.txt",
                        "--old",
                        "old",
                        "--new",
                        "new",
                        "--apply",
                        "--test",
                        "grep",
                        "-q",
                        "new",
                        "a.txt",
                    ]
                )

            self.assertEqual(code, 0)
            self.assertEqual(target.read_text(encoding="utf-8"), "new\n")
            self.assertIn("status: applied", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
