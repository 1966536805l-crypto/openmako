from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from quantagent.answer_guard import guard_answer
from quantagent.better_option import suggest_better_option
from quantagent.evidence_ledger import create_evidence_record, load_evidence, record_evidence
from quantagent.headless_sdk import QuantAgentHeadless
from quantagent.subagents import SubagentRecord, load_subagents, save_subagents


class AnswerGuardHeadlessTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent answer guard ")

    def test_answer_guard_blocks_unsupported_data_fact(self) -> None:
        with self.make_project() as tmp:
            verdict = guard_answer(Path(tmp), "The score is 90 points without checking.", goal="report only verified data")

            self.assertFalse(verdict.ok)
            self.assertEqual(verdict.action, "block")
            self.assertIn("lacks verified evidence", verdict.findings[-1].reason)

    def test_answer_guard_allows_evidence_backed_data_fact(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            evidence = create_evidence_record(claim="test count", value="352", evidence_type="command_output", source="unittest output")

            verdict = guard_answer(project, "352 tests passed. source: unittest output", goal="report only verified data", evidence=(evidence,))

            self.assertTrue(verdict.ok, verdict.answer)
            self.assertTrue(verdict.evidence_used)

    def test_answer_guard_allows_internal_agent_runtime_summary_counts(self) -> None:
        with self.make_project() as tmp:
            answer = (
                "Task: run tests\n"
                "Agent v2 completed via deprecated compatibility wrapper over canonical agent loop: 3/3 steps ok. "
                "source: agent_v2.observations\n"
                "Trajectory was recorded by quantagent.agent_loop.run_agent_loop."
            )

            verdict = guard_answer(Path(tmp), answer, goal="run tests", task="run tests")

            self.assertTrue(verdict.ok, verdict.answer)

    def test_answer_guard_allows_verified_agent_loop_repair_summary(self) -> None:
        with self.make_project() as tmp:
            answer = (
                "更优解提示：先用命令或来源验证数据，再回答具体数字。\n\n"
                "Task: Repair subject.py unique_preserve_order to remove duplicates while preserving order so unit tests pass. "
                "source: user request\n"
                "Agent loop mode route: repair (1.00) -> final repair.\n"
                "Completed: 11/11 observations ok. source: agent_loop.observations\n"
                "Runtime context, tool transcripts, and trajectory were recorded for review."
            )

            verdict = guard_answer(
                Path(tmp),
                answer,
                goal="Repair subject.py unique_preserve_order to remove duplicates while preserving order so unit tests pass.",
                task="Repair subject.py unique_preserve_order to remove duplicates while preserving order so unit tests pass.",
            )

            self.assertTrue(verdict.ok, verdict.answer)

    def test_evidence_ledger_persists_manual_records(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            record = record_evidence(project, claim="line count", value="45374", evidence_type="command_output", source="wc")

            loaded = load_evidence(project)

            self.assertEqual(loaded[-1].evidence_id, record.evidence_id)
            self.assertEqual(loaded[-1].value, "45374")

    def test_better_option_recommends_verification_for_scores(self) -> None:
        hint = suggest_better_option("现在多少分")

        self.assertTrue(hint.available)
        self.assertEqual(hint.action, "verify_before_answer")

    def test_headless_sdk_routes_and_guards_answers(self) -> None:
        with self.make_project() as tmp:
            sdk = QuantAgentHeadless(Path(tmp))
            route = sdk.route("实现一个小功能", mode="build")
            verdict = sdk.guard_answer("Unknown until verified.", goal="report only verified data")

            self.assertEqual(route.mode, "build")
            self.assertTrue(verdict.ok)

    def test_headless_sdk_passes_duration_fuse_to_agent_loop(self) -> None:
        with self.make_project() as tmp:
            sdk = QuantAgentHeadless(Path(tmp))

            result = sdk.run(
                "create hello.py with greet function and test it",
                mode="build",
                include_validation=False,
                max_duration_seconds=0,
            )

            self.assertFalse(result.ok, result.to_dict())
            self.assertEqual(result.request.max_duration_seconds, 0)
            self.assertEqual(result.agent.failure_class, "timeout")
            self.assertEqual(result.agent.observations[0].name, "task_timeout")

    def test_subagent_records_permission_scope(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            record = SubagentRecord(
                subagent_id="sub-one",
                parent_task_id="task-parent",
                child_task_id="task-child",
                child_session_id="session-child",
                task="review without editing",
                context_mode="isolated",
                agent_profile="review",
                permission_mode="plan",
                tools=("file_read",),
                disallowed_tools=("file_edit",),
                background=False,
            )
            save_subagents(project, [record])
            loaded = load_subagents(project)[-1]

            self.assertEqual(record.permission_mode, "plan")
            self.assertEqual(loaded.tools, ["file_read"])
            self.assertEqual(loaded.disallowed_tools, ["file_edit"])
            self.assertFalse(loaded.background)


if __name__ == "__main__":
    unittest.main()
