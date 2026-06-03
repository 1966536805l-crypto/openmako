from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from quantagent.result_schema import ToolResult
from quantagent.tool_loop import _enforce_tool_result_budget, _tool_loop_failure_class
from quantagent.tool_output import PERSISTED_OUTPUT_TAG, load_tool_result_manifest


class ToolLoopHardeningTest(unittest.TestCase):
    def test_tool_loop_result_budget_collapses_large_nested_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent tool loop hardening ") as tmp:
            project = Path(tmp)
            old_budget = os.environ.get("QUANTAGENT_TOOL_OUTPUT_TURN_BUDGET_CHARS")
            old_preview = os.environ.get("QUANTAGENT_TOOL_OUTPUT_PREVIEW_CHARS")
            os.environ["QUANTAGENT_TOOL_OUTPUT_TURN_BUDGET_CHARS"] = "700"
            os.environ["QUANTAGENT_TOOL_OUTPUT_PREVIEW_CHARS"] = "32"
            try:
                raw = "line with lots of detail\n" * 120
                result = ToolResult("shell", True, "ok", {"stdout_preview": raw, "stderr_preview": "clean"})

                _enforce_tool_result_budget(project, [result])
            finally:
                if old_budget is None:
                    os.environ.pop("QUANTAGENT_TOOL_OUTPUT_TURN_BUDGET_CHARS", None)
                else:
                    os.environ["QUANTAGENT_TOOL_OUTPUT_TURN_BUDGET_CHARS"] = old_budget
                if old_preview is None:
                    os.environ.pop("QUANTAGENT_TOOL_OUTPUT_PREVIEW_CHARS", None)
                else:
                    os.environ["QUANTAGENT_TOOL_OUTPUT_PREVIEW_CHARS"] = old_preview

            self.assertIn(PERSISTED_OUTPUT_TAG, result.data["stdout_preview"])
            self.assertEqual(result.data["stderr_preview"], "clean")
            self.assertEqual(Path(load_tool_result_manifest(project)[0].path).read_text(encoding="utf-8"), raw)
            self.assertIn("artifacts", result.data)

    def test_tool_loop_failure_class_uses_model_error_kind(self) -> None:
        observation = type("Observation", (), {"ok": False, "data": {"error_kind": "rate_limit"}})()

        self.assertEqual(_tool_loop_failure_class([observation]), "rate_limit")


if __name__ == "__main__":
    unittest.main()
