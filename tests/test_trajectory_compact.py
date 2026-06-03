from __future__ import annotations

import unittest

from quantagent.sessions import SessionMessage
from quantagent.trajectory_compact import compact_trajectory, estimate_tokens


class TrajectoryCompactTest(unittest.TestCase):
    def test_compact_protects_first_and_last_messages(self) -> None:
        messages = [
            {"role": "system", "content": "rules"},
            {"role": "user", "content": "start the audit"},
            {"role": "assistant", "content": "I will inspect context. " * 80},
            {"role": "tool", "content": "context ok with many ranked files and handoff details. " * 80, "meta": {"tool": "context", "ok": True}},
            {"role": "tool", "content": "validate failed because one script has a syntax error. " * 80, "meta": {"tool": "validate", "ok": False}},
            {"role": "assistant", "content": "Need to fix tests after reading the validation stderr. " * 80},
            {"role": "user", "content": "keep going"},
            {"role": "assistant", "content": "latest answer"},
        ]

        result = compact_trajectory(messages, first_n=2, last_n=2)

        self.assertEqual(result.messages[0]["content"], "rules")
        self.assertEqual(result.messages[1]["content"], "start the audit")
        self.assertEqual(result.messages[-2]["content"], "keep going")
        self.assertEqual(result.messages[-1]["content"], "latest answer")
        self.assertEqual(result.messages[2]["meta"]["kind"], "trajectory_summary")
        self.assertIn("validate:failed", result.messages[2]["content"])
        self.assertEqual(result.metrics.original_messages, 8)
        self.assertEqual(result.metrics.final_messages, 5)
        self.assertEqual(result.metrics.summarized_middle, 4)
        self.assertGreater(result.metrics.original_estimated_tokens, 0)
        self.assertLessEqual(result.metrics.compacted_estimated_tokens, result.metrics.original_estimated_tokens)

    def test_no_middle_returns_normalized_messages_without_summary(self) -> None:
        messages = [
            {"role": "user", "content": "one"},
            {"role": "assistant", "content": "two"},
        ]

        result = compact_trajectory(messages, first_n=1, last_n=1)

        self.assertEqual(result.messages, messages)
        self.assertIsNone(result.summary_entry)
        self.assertEqual(result.metrics.summarized_middle, 0)
        self.assertEqual(result.metrics.compression_ratio, 1.0)

    def test_accepts_session_message_dataclasses(self) -> None:
        messages = [
            SessionMessage(role="user", content="first"),
            SessionMessage(role="assistant", content="middle"),
            SessionMessage(role="user", content="last"),
        ]

        result = compact_trajectory(messages, first_n=1, last_n=1)

        self.assertEqual(result.messages[0]["role"], "user")
        self.assertEqual(result.messages[-1]["content"], "last")
        self.assertEqual(result.summary_entry["meta"]["summarized_messages"], 1)

    def test_summary_trims_deterministically(self) -> None:
        messages = [{"role": "tool", "content": "alpha " * 50, "meta": {"tool": "scan"}} for _ in range(6)]

        result_a = compact_trajectory(messages, first_n=0, last_n=0, target_summary_chars=140)
        result_b = compact_trajectory(messages, first_n=0, last_n=0, target_summary_chars=140)

        self.assertTrue(result_a.metrics.summary_trimmed)
        self.assertEqual(result_a.summary_entry["content"], result_b.summary_entry["content"])
        self.assertLessEqual(len(result_a.summary_entry["content"]), 140)

    def test_estimate_tokens_handles_ascii_and_cjk(self) -> None:
        self.assertGreater(estimate_tokens("hello world"), 0)
        self.assertGreaterEqual(estimate_tokens("量化研究"), 4)


if __name__ == "__main__":
    unittest.main()
