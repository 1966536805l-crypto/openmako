from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.edit_loop import create_patch_plan
from quantagent.model_client import ModelResponse
from quantagent.repair_scheduler import render_repair_scheduler_result, run_multi_worker_repair
from quantagent.structured_diff_preview import (
    create_structured_diff_preview,
    load_structured_diff_preview,
    render_structured_diff_preview,
    save_structured_diff_preview,
)


class StructuredPreviewRepairSchedulerTest(unittest.TestCase):
    def test_structured_diff_preview_renders_file_risk_and_permissions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent preview ") as tmp:
            project = Path(tmp)
            (project / "quantagent").mkdir()
            (project / "quantagent" / "sandbox_policy.py").write_text("ALLOW = True\n", encoding="utf-8")
            diff = (
                "--- a/quantagent/sandbox_policy.py\n"
                "+++ b/quantagent/sandbox_policy.py\n"
                "@@ -1,1 +1,1 @@\n"
                "-ALLOW = True\n"
                "+ALLOW = False\n"
            )

            preview = create_structured_diff_preview(project, diff, task="tighten policy", test_command=["python3", "-m", "py_compile", "quantagent/sandbox_policy.py"])
            rendered = render_structured_diff_preview(preview)
            path = save_structured_diff_preview(project, preview)
            loaded = load_structured_diff_preview(project, preview.preview_id)

            self.assertTrue(path.exists())
            self.assertEqual(loaded.preview_id, preview.preview_id)
            self.assertEqual(preview.files[0].risk, "high")
            self.assertEqual(preview.files[0].additions, 1)
            self.assertEqual(preview.files[0].deletions, 1)
            self.assertIn("permission=", rendered)
            self.assertTrue(preview.approval_required)

    def test_multi_worker_repair_ranks_passing_worker_and_bundles_reviews(self) -> None:
        class FakeClient:
            configured = True

            def complete(self, request):
                return ModelResponse(
                    model=request.model,
                    ok=True,
                    text='{"candidates":[{"name":"fix value","summary":"minimal","edits":[{"path":"a.py","old":"VALUE = 1","new":"VALUE = 2"}]}]}',
                    provider="fake",
                )

        with tempfile.TemporaryDirectory(prefix="quantagent scheduler ") as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("# TODO: verify edge case\nVALUE = 1\n", encoding="utf-8")
            plan = create_patch_plan(project, "fix value", paths=["a.py"], test_command=["grep", "-q", "VALUE = 2", "a.py"])

            result = run_multi_worker_repair(
                project,
                plan,
                "AssertionError",
                workers=2,
                max_rounds=1,
                model="fake-model",
                client_factory=lambda _worker_id: FakeClient(),
            )
            rendered = render_repair_scheduler_result(result)

            self.assertTrue(result.ok, result.summary)
            self.assertEqual(len(result.workers), 2)
            self.assertTrue(result.bundle.recommended_worker)
            self.assertEqual(len(result.bundle.review_ids), 2)
            self.assertEqual(len(result.bundle.preview_ids), 2)
            self.assertTrue(result.bundle.approval_required)
            self.assertIn("a.py", result.bundle.changed_paths)
            self.assertTrue(all(worker.preview_id for worker in result.workers))
            self.assertTrue(any("todo_comment" in item for worker in result.workers for item in worker.diagnostics))
            self.assertIn("Multi-Worker Repair Result", rendered)
            self.assertIn("preview=", rendered)
            self.assertEqual((project / "a.py").read_text(encoding="utf-8"), "# TODO: verify edge case\nVALUE = 1\n")


if __name__ == "__main__":
    unittest.main()
