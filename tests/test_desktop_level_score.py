from __future__ import annotations

import unittest

from quantagent.desktop_level_score import (
    DesktopLevelScore,
    render_desktop_level_score,
    score_desktop_level,
)


class DesktopLevelScoreTest(unittest.TestCase):
    def test_perfect_metrics_reach_l5_and_score_100(self) -> None:
        score = score_desktop_level(
            {
                "long_run_hours": 8,
                "success_rate": 0.96,
                "misoperations": 0,
                "misoperation_rate": 0,
                "crashes": 0,
                "autopsy_coverage": 0.99,
                "recovery_rate": 0.91,
            }
        )

        self.assertIsInstance(score, DesktopLevelScore)
        self.assertEqual(score.level, "L5")
        self.assertGreaterEqual(score.score, 90)
        self.assertTrue(all(score.gates.values()))
        self.assertEqual(score.metrics["success_rate"], 0.96)

    def test_l4_thresholds_are_explicit_hard_gates(self) -> None:
        score = score_desktop_level(
            {
                "duration_minutes": 240,
                "success_rate": 85,
                "misoperations": 1,
                "total_actions": 200,
                "crashes": 0,
                "autopsies_written": 9,
                "failed_runs": 10,
                "recovered_failures": 7,
                "recoverable_failures": 10,
            }
        )

        self.assertEqual(score.level, "L4")
        self.assertGreaterEqual(score.score, 80)
        self.assertTrue(score.gates["L4 long_run_hours >= 4.00"])
        self.assertTrue(score.gates["L4 success_rate >= 0.85"])
        self.assertTrue(score.gates["L4 misoperation_rate <= 0.01"])
        self.assertTrue(score.gates["L4 misoperations <= 1"])
        self.assertTrue(score.gates["L4 crashes <= 0"])
        self.assertTrue(score.gates["L4 autopsy_coverage >= 0.90"])
        self.assertTrue(score.gates["L4 recovery_rate >= 0.70"])
        self.assertFalse(score.gates["L5 long_run_hours >= 8.00"])

    def test_short_long_run_blocks_l4_even_when_score_is_high(self) -> None:
        score = score_desktop_level(
            {
                "long_run_hours": 1,
                "success_rate": 1.0,
                "misoperations": 0,
                "misoperation_rate": 0,
                "crashes": 0,
                "autopsy_coverage": 1.0,
                "recovery_rate": 1.0,
            }
        )

        self.assertGreaterEqual(score.score, 80)
        self.assertEqual(score.level, "L3")
        self.assertFalse(score.gates["L4 long_run_hours >= 4.00"])
        self.assertIn("L4 blocked by", "\n".join(score.reasons))

    def test_crash_and_misoperation_fail_l4_and_penalize_score(self) -> None:
        score = score_desktop_level(
            {
                "long_run_hours": 8,
                "success_rate": 0.97,
                "misoperations": 2,
                "misoperation_rate": 0.02,
                "crashes": 1,
                "autopsy_coverage": 1.0,
                "recovery_rate": 0.95,
            }
        )

        self.assertEqual(score.level, "L3")
        self.assertLess(score.score, 80)
        self.assertFalse(score.gates["L4 misoperation_rate <= 0.01"])
        self.assertFalse(score.gates["L4 misoperations <= 1"])
        self.assertFalse(score.gates["L4 crashes <= 0"])

    def test_counts_can_derive_rates_without_nondeterminism(self) -> None:
        metrics = {
            "duration_seconds": 8 * 3600,
            "passed_tasks": 19,
            "total_tasks": 20,
            "misoperation_count": 0,
            "action_count": 1000,
            "crash_count": 0,
            "failed_runs": 4,
            "failed_runs_with_autopsy": 4,
            "recovery_opportunities": 10,
            "successful_recoveries": 9,
        }

        first = score_desktop_level(metrics)
        second = score_desktop_level(dict(reversed(list(metrics.items()))))

        self.assertEqual(first, second)
        self.assertEqual(first.level, "L5")
        self.assertEqual(first.metrics["success_rate"], 0.95)
        self.assertEqual(first.metrics["recovery_rate"], 0.9)

    def test_missing_metrics_default_conservatively(self) -> None:
        score = score_desktop_level({})

        self.assertEqual(score.level, "L1")
        self.assertEqual(score.score, 0)
        self.assertFalse(score.gates["L4 success_rate >= 0.85"])
        self.assertIn("missing metrics defaulted conservatively", "\n".join(score.reasons))

    def test_render_is_stable_and_human_readable(self) -> None:
        score = score_desktop_level(
            {
                "long_run_hours": 4,
                "success_rate": 0.9,
                "misoperations": 0,
                "misoperation_rate": 0,
                "crashes": 0,
                "autopsy_coverage": 1,
                "recovery_rate": 0.8,
            }
        )

        rendered = render_desktop_level_score(score)

        self.assertIn("Desktop level: L4", rendered)
        self.assertIn("Score:", rendered)
        self.assertIn("- L4 long_run_hours >= 4.00: pass", rendered)
        self.assertIn("- success_rate: 0.9", rendered)
        self.assertEqual(rendered, render_desktop_level_score(score))


if __name__ == "__main__":
    unittest.main()
