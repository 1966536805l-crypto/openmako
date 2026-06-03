from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.tool_output import (
    PERSISTED_OUTPUT_TAG,
    enforce_turn_tool_output_budget,
    load_tool_result_manifest,
)


class ToolOutputBudgetTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent tool output ")

    def test_enforce_turn_budget_collapses_largest_output_first(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            small = "small\n" * 5
            large = "large line\n" * 200
            medium = "medium line\n" * 50
            results = [{"content": small}, {"content": large}, {"content": medium}]

            returned = enforce_turn_tool_output_budget(results, project, budget_chars=1800, preview_chars=40)

            self.assertIs(returned, results)
            self.assertEqual(results[0]["content"], small)
            self.assertIn(PERSISTED_OUTPUT_TAG, results[1]["content"])
            self.assertEqual(results[2]["content"], medium)
            self.assertLess(sum(len(item["content"]) for item in results), 1800)

            manifest = load_tool_result_manifest(project)
            self.assertEqual(len(manifest), 1)
            self.assertEqual(Path(manifest[0].path).read_text(encoding="utf-8"), large)

    def test_enforce_turn_budget_appends_replay_artifact_to_data(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            stdout = "stdout row\n" * 180
            result = {
                "name": "shell",
                "data": {
                    "stdout": stdout,
                    "stderr": "ok\n",
                    "artifacts": [{"artifact_id": "existing"}],
                },
            }

            enforce_turn_tool_output_budget([result], project, budget_chars=800, preview_chars=32)

            self.assertIn(PERSISTED_OUTPUT_TAG, result["data"]["stdout"])
            self.assertEqual(result["data"]["stderr"], "ok\n")
            artifacts = result["data"]["artifacts"]
            self.assertEqual(artifacts[0]["artifact_id"], "existing")
            self.assertEqual(len(artifacts), 2)
            self.assertIn("path", artifacts[1])
            self.assertIn("preview", artifacts[1])
            self.assertEqual(Path(artifacts[1]["path"]).read_text(encoding="utf-8"), stdout)

    def test_enforce_turn_budget_continues_until_under_budget(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            first = "first row\n" * 180
            second = "second row\n" * 160
            results = [{"content": first}, {"content": second}, {"content": "tiny"}]

            enforce_turn_tool_output_budget(results, project, budget_chars=1200, preview_chars=24)

            self.assertIn(PERSISTED_OUTPUT_TAG, results[0]["content"])
            self.assertIn(PERSISTED_OUTPUT_TAG, results[1]["content"])
            self.assertEqual(results[2]["content"], "tiny")
            self.assertLess(sum(len(item["content"]) for item in results), 1200)
            self.assertEqual(len(load_tool_result_manifest(project)), 2)

    def test_enforce_turn_budget_skips_already_persisted_outputs(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            already = f"{PERSISTED_OUTPUT_TAG}\nFull output saved to: elsewhere\n</persisted-output>"
            raw = "raw row\n" * 200
            results = [{"content": already}, {"content": raw}]

            enforce_turn_tool_output_budget(results, project, budget_chars=600, preview_chars=32)

            self.assertEqual(results[0]["content"], already)
            self.assertIn(PERSISTED_OUTPUT_TAG, results[1]["content"])
            manifest = load_tool_result_manifest(project)
            self.assertEqual(len(manifest), 1)
            self.assertEqual(Path(manifest[0].path).read_text(encoding="utf-8"), raw)

    def test_enforce_turn_budget_supports_plain_string_results(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            raw = "plain result\n" * 180
            results = ["tiny", raw]

            enforce_turn_tool_output_budget(results, project, budget_chars=900, preview_chars=32)

            self.assertEqual(results[0], "tiny")
            self.assertIn(PERSISTED_OUTPUT_TAG, results[1])
            self.assertEqual(Path(load_tool_result_manifest(project)[0].path).read_text(encoding="utf-8"), raw)


if __name__ == "__main__":
    unittest.main()
