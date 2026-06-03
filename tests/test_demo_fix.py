from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from quantagent.cli import main
from quantagent.demo_fix import run_fix_demo


class DemoFixTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent demo fix ")

    def test_fix_demo_proves_red_to_green_without_model_calls(self) -> None:
        with self.make_project() as tmp:
            result = run_fix_demo(Path(tmp))

            self.assertTrue(result.ok)
            self.assertFalse(result.initial_test_ok)
            self.assertTrue(result.final_test_ok)
            self.assertEqual(result.model_calls, 0)
            self.assertEqual(result.changed_files, ("calculator.py",))
            self.assertTrue(result.checkpoint_id.startswith("chk-"))
            self.assertTrue(Path(result.result_json).exists())
            self.assertTrue(Path(result.result_markdown).exists())

    def test_demo_fix_cli_json(self) -> None:
        with self.make_project() as tmp:
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = main(["--no-trust-prompt", "demo", "--project", tmp, "fix", "--json"])

            payload = json.loads(stdout.getvalue())
            self.assertEqual(code, 0)
            self.assertTrue(payload["ok"])
            self.assertFalse(payload["initial_test_ok"])
            self.assertTrue(payload["final_test_ok"])
            self.assertEqual(payload["model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
