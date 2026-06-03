from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.repair_scheduler import RepairWorkerResult
from quantagent.review_arbitration import arbitrate_parent_reviews, render_arbitration_decision
from quantagent.worktree_isolation import create_isolated_worktree, create_isolation_review


class ReviewArbitrationTest(unittest.TestCase):
    def test_ranks_ok_score_diagnostics_risk_paths_and_approval(self) -> None:
        workers = [
            RepairWorkerResult(
                worker_id="worker-low-score",
                ok=True,
                summary="passes with smaller patch",
                review_id="review-low",
                changed_paths=["a.py"],
                score=80,
            ),
            RepairWorkerResult(
                worker_id="worker-diagnostics",
                ok=True,
                summary="higher score but diagnostic error",
                review_id="review-diag",
                changed_paths=["a.py"],
                score=90,
                diagnostics=["error:syntax:a.py:1:invalid syntax"],
            ),
            RepairWorkerResult(
                worker_id="worker-failed",
                ok=False,
                summary="failed despite high score",
                review_id="review-failed",
                changed_paths=["a.py"],
                score=99,
            ),
            RepairWorkerResult(
                worker_id="worker-high-risk",
                ok=True,
                summary="same score but higher risk",
                review_id="review-risk",
                changed_paths=["quantagent/sandbox_policy.py"],
                score=80,
                high_risk_paths=["quantagent/sandbox_policy.py"],
            ),
            RepairWorkerResult(
                worker_id="worker-approval",
                ok=True,
                summary="same score but requires approval",
                review_id="review-approval",
                changed_paths=["a.py"],
                score=80,
                approval_required=True,
            ),
        ]

        decision = arbitrate_parent_reviews(workers=workers)
        rendered = render_arbitration_decision(decision)
        payload = json.loads(render_arbitration_decision(decision, format="json"))

        self.assertEqual(decision.recommended_review_id, "review-diag")
        self.assertEqual([review.review_id for review in decision.ranked_reviews], ["review-diag", "review-low", "review-approval", "review-risk", "review-failed"])
        self.assertIn("diagnostic_errors", decision.risk_flags)
        self.assertIn("high_risk_paths", decision.risk_flags)
        self.assertIn("approval_required", decision.risk_flags)
        self.assertIn("Parent Review Arbitration", rendered)
        self.assertEqual(payload["recommended_review_id"], "review-diag")

    def test_aggregates_risk_flags_and_approval_requirement(self) -> None:
        workers = [
            RepairWorkerResult(
                worker_id="worker-1",
                ok=True,
                summary="safe patch",
                review_id="review-safe",
                changed_paths=["a.py"],
                score=90,
            ),
            RepairWorkerResult(
                worker_id="worker-2",
                ok=True,
                summary="risky patch",
                review_id="review-risk",
                changed_paths=["quantagent/sandbox_policy.py"],
                score=70,
                approval_required=True,
                high_risk_paths=["quantagent/sandbox_policy.py"],
                diagnostics=["error:ruff:quantagent/sandbox_policy.py:2:E999"],
            ),
        ]

        decision = arbitrate_parent_reviews(workers=workers)

        self.assertEqual(decision.recommended_review_id, "review-safe")
        self.assertTrue(decision.approval_required)
        self.assertTrue(decision.apply_gate_ready)
        self.assertEqual(decision.risk_flags, ["diagnostic_errors", "high_risk_paths", "approval_required"])

    def test_no_reviews_is_blocked(self) -> None:
        decision = arbitrate_parent_reviews()

        self.assertEqual(decision.recommended_review_id, "")
        self.assertEqual(decision.ranked_reviews, [])
        self.assertFalse(decision.apply_gate_ready)
        self.assertTrue(decision.approval_required)
        self.assertIn("blocked:no_reviews", decision.risk_flags)
        self.assertIn("No review candidates.", render_arbitration_decision(decision))

    def test_review_ids_load_isolation_reviews_for_parent_arbitration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="quantagent arbitration ") as tmp:
            project = Path(tmp)
            (project / "a.py").write_text("VALUE = 1\n", encoding="utf-8")
            worktree = create_isolated_worktree(project, include=["a.py"])
            (Path(worktree.workspace_path) / "a.py").write_text("VALUE = 2\n", encoding="utf-8")
            review = create_isolation_review(project, worktree.worktree_id)

            decision = arbitrate_parent_reviews(project=project, review_ids=[review.review_id])

            self.assertEqual(decision.recommended_review_id, review.review_id)
            self.assertEqual(decision.ranked_reviews[0].changed_paths, ["a.py"])
            self.assertTrue(decision.apply_gate_ready)


if __name__ == "__main__":
    unittest.main()
