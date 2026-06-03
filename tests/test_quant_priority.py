from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from quantagent.agent_loop_v3 import build_agent_v3_plan
from quantagent.answer_guard import guard_answer
from quantagent.cli import main
from quantagent.evidence_ledger import record_evidence
from quantagent.mode_router import route_agent_mode
from quantagent.quant_priority import BLOCK, WARN, build_quant_priority_review, render_quant_priority_review


class QuantPriorityTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="mako quant priority ")

    def test_quant_publish_claim_blocks_without_evidence(self) -> None:
        with self.make_project() as tmp:
            review = build_quant_priority_review(
                Path(tmp),
                "报告 PF=2.1 已确认，可以实盘下单",
                audit=False,
            )

            self.assertEqual(review.action, BLOCK)
            self.assertFalse(review.ok)
            self.assertIn("execution_evidence", {item.key for item in review.missing_evidence})
            self.assertIn("Do not approve live trading", " ".join(review.blocked_conclusions))

    def test_quant_research_warns_but_allows_safe_analysis(self) -> None:
        with self.make_project() as tmp:
            review = build_quant_priority_review(
                Path(tmp),
                "分析 PF 和滑点容量，但先不要下结论",
                audit=False,
            )

            self.assertEqual(review.action, WARN)
            self.assertTrue(review.ok)
            self.assertIn("quant-first mode active", " ".join(review.notes))

    def test_quant_gate_allows_when_required_evidence_is_recorded(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            record_evidence(project, claim="dedup baseline", value="scenario_A_dedup.csv", source="registry")
            record_evidence(project, claim="artifact hashes and row count", value="sha256 abc rows 100", source="run artifact")
            record_evidence(project, claim="yearly OOS split", value="2025 split present", source="report")
            record_evidence(project, claim="broker fill slippage capacity", value="tick fill broker slippage capacity", source="execution log")

            review = build_quant_priority_review(
                project,
                "报告 PF=2.1 已确认，可以实盘下单，含 09:30 成交滑点容量",
                audit=False,
            )

            self.assertEqual(review.action, "allow")
            self.assertTrue(review.ok)
            self.assertFalse(review.missing_evidence)

    def test_answer_guard_blocks_quant_conclusion_without_evidence(self) -> None:
        with self.make_project() as tmp:
            verdict = guard_answer(
                Path(tmp),
                "PF=2.1 is confirmed and safe to trade live.",
                task="publish quant conclusion",
            )

            self.assertFalse(verdict.ok)
            self.assertEqual(verdict.action, BLOCK)
            self.assertTrue(any("quant priority gate" in item.reason for item in verdict.findings))

    def test_agent_v3_plan_inserts_quant_evidence_gate(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            route = route_agent_mode(project, "分析 PF 滑点容量")
            plan = build_agent_v3_plan("分析 PF 滑点容量", route, include_validation=False)

            self.assertIn("quant_evidence_gate", [step.name for step in plan])
            self.assertIn("audit", [step.name for step in plan])

    def test_quant_cli_check_returns_blocking_review(self) -> None:
        with self.make_project() as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "quant",
                        "--project",
                        tmp,
                        "check",
                        "报告 PF=2.1 已确认，可以实盘",
                        "--no-audit",
                    ]
                )

            self.assertEqual(rc, 1)
            self.assertIn("# Quant Priority Review", stdout.getvalue())
            self.assertIn("action: block", stdout.getvalue())

    def test_render_non_quant_review_is_clean(self) -> None:
        with self.make_project() as tmp:
            rendered = render_quant_priority_review(build_quant_priority_review(Path(tmp), "打开终端", audit=False))

            self.assertIn("is_quant: false", rendered)
            self.assertIn("action: allow", rendered)


if __name__ == "__main__":
    unittest.main()
