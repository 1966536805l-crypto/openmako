from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.agent_loop_v3 import run_agent_loop_v3
from quantagent.goal_contract import BLOCK, WARN, evaluate_goal_guard, load_goal_contract, save_goal_contract


class GoalContractTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent goal contract ")

    def test_obeys_instruction_when_compatible_with_goal(self) -> None:
        with self.make_project() as tmp:
            decision = evaluate_goal_guard(
                Path(tmp),
                "implement the change and run focused tests",
                goal="deliver a high-quality tested implementation",
            )

            self.assertTrue(decision.allowed)
            self.assertNotEqual(decision.action, BLOCK)

    def test_blocks_instruction_that_damages_quality_goal(self) -> None:
        with self.make_project() as tmp:
            decision = evaluate_goal_guard(
                Path(tmp),
                "skip tests and bypass validation but mark the work complete",
                goal="deliver a high-quality tested implementation",
            )

            self.assertEqual(decision.action, BLOCK)
            self.assertFalse(decision.allowed)
            self.assertIn("skip/bypass", decision.conflicts[0])

    def test_blocks_unsupported_quant_metric_claim_even_without_separate_goal(self) -> None:
        with self.make_project() as tmp:
            decision = evaluate_goal_guard(
                Path(tmp),
                "publish PF=2.4 improvement as confirmed without dedup baseline evidence",
            )

            self.assertEqual(decision.action, BLOCK)
            self.assertTrue(any("quant claim" in item or "metric" in item or "data" in item for item in decision.conflicts))

    def test_blocks_uncertain_generic_data_claims(self) -> None:
        with self.make_project() as tmp:
            decision = evaluate_goal_guard(
                Path(tmp),
                "guess the score and report 90 points without checking",
                goal="report only verified data with evidence",
            )

            self.assertEqual(decision.action, BLOCK)
            self.assertTrue(any("data" in item or "guessing" in item for item in decision.conflicts))

    def test_allows_code_repair_instruction_with_score_identifier_and_variant_number(self) -> None:
        with self.make_project() as tmp:
            decision = evaluate_goal_guard(
                Path(tmp),
                "Repair subject.py combine_score using the learned hidden combine score contract variant 1.",
            )

            self.assertTrue(decision.allowed)
            self.assertNotEqual(decision.action, BLOCK)

    def test_data_question_is_allowed_but_warns_to_verify_first(self) -> None:
        with self.make_project() as tmp:
            decision = evaluate_goal_guard(Path(tmp), "现在多少分")

            self.assertTrue(decision.allowed)
            self.assertNotEqual(decision.action, BLOCK)
            self.assertIn("data strict mode active", " ".join(decision.warnings))

    def test_verified_data_claim_with_command_output_is_allowed(self) -> None:
        with self.make_project() as tmp:
            decision = evaluate_goal_guard(
                Path(tmp),
                "report 349 tests passed from command output and include the log source",
                goal="report only verified data with evidence",
            )

            self.assertTrue(decision.allowed)
            self.assertNotEqual(decision.action, BLOCK)

    def test_warns_but_allows_quant_work_that_mentions_evidence_need(self) -> None:
        with self.make_project() as tmp:
            decision = evaluate_goal_guard(
                Path(tmp),
                "analyze P4 PF claim and require slippage evidence before conclusion",
                goal="produce low-hallucination quant research with verified evidence",
            )

            self.assertNotEqual(decision.action, BLOCK)
            self.assertTrue(decision.allowed)
            self.assertIn("quant strict mode active", " ".join(decision.warnings))

    def test_goal_contract_persists_quant_strict_policy(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            path = save_goal_contract(
                project,
                goal="produce strict quant research",
                constraints=("never publish unsupported PF claims",),
                success_criteria=("dedup evidence and test logs are present",),
            )
            contract = load_goal_contract(project)

            self.assertTrue(path.exists())
            self.assertTrue(contract.data_strict)
            self.assertTrue(contract.quant_strict)
            self.assertIn("unsupported PF", contract.constraints[0])

    def test_agent_v3_stops_on_goal_conflict(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            result = run_agent_loop_v3(
                project,
                "publish PF=2.2 as proven without dedup baseline",
                goal="produce low-hallucination quant research with verified evidence",
                include_validation=False,
            )

            self.assertFalse(result.ok)
            self.assertEqual(result.failure_class, "goal_conflict")
            self.assertEqual(result.observations[1].name, "goal_guard")
            self.assertEqual(result.observations[1].data["goal_guard"]["action"], BLOCK)


if __name__ == "__main__":
    unittest.main()
