from __future__ import annotations

import unittest

from quantagent.desktop_daemon_core import DesktopDaemonRecord
from quantagent.desktop_recovery import RECOVERY_CHAIN, classify_recovery_risk, plan_desktop_recovery, plan_recovery_strategy


class DesktopRecoveryTest(unittest.TestCase):
    def test_recovery_chain_is_stable(self) -> None:
        self.assertEqual(RECOVERY_CHAIN, ("ax", "ocr", "som", "grid", "browser_reopen", "wait", "pause"))

    def test_starts_with_ax_when_daemon_failed_without_prior_recovery(self) -> None:
        strategy = plan_recovery_strategy(
            "tokenize_failed",
            [DesktopDaemonRecord(1, "tokenize", "failed", "no usable tokens", {})],
        )

        self.assertEqual(strategy.action, "retry_ax_snapshot")
        self.assertEqual(strategy.source, "ax")
        self.assertFalse(strategy.paused)
        self.assertEqual(strategy.args["capture"], "ax")

    def test_escalates_from_ax_to_ocr_to_som_to_grid(self) -> None:
        cases = (
            ("ax", "retry_ocr_snapshot", "ocr"),
            ("ax ocr", "retry_som_capture", "som"),
            ("ax ocr som", "retry_grid_capture", "grid"),
        )
        for summary, action, source in cases:
            with self.subTest(summary=summary):
                strategy = plan_recovery_strategy(
                    "verify_failed",
                    [{"step": 1, "phase": "recovery", "status": "failed", "summary": summary}],
                )

                self.assertEqual(strategy.action, action)
                self.assertEqual(strategy.source, source)

    def test_exhausted_visual_paths_reopen_browser_then_wait_then_pause(self) -> None:
        reopen = plan_recovery_strategy(
            "action_failed",
            [{"phase": "recovery", "status": "failed", "summary": "ax ocr som grid exhausted"}],
            browser="Chrome",
        )
        wait = plan_recovery_strategy(
            "action_failed",
            [{"phase": "recovery", "status": "failed", "summary": "ax ocr som grid browser_reopen failed"}],
            wait_seconds=4,
        )
        pause = plan_recovery_strategy(
            "action_failed",
            [{"phase": "recovery", "status": "failed", "summary": "ax ocr som grid browser_reopen wait exhausted"}],
        )

        self.assertEqual(reopen.action, "reopen_browser")
        self.assertEqual(reopen.args["browser"], "Chrome")
        self.assertEqual(wait.action, "wait")
        self.assertEqual(wait.args["seconds"], 4.0)
        self.assertTrue(pause.paused)

    def test_high_risk_goal_pauses_even_before_ax(self) -> None:
        for goal, category in (
            ("type password into login", "credential"),
            ("pay the invoice", "payment"),
            ("buy 100 shares", "trading"),
            ("高风险操作", "high_risk"),
        ):
            with self.subTest(goal=goal):
                strategy = plan_recovery_strategy("tokenize_failed", [], goal=goal)

                self.assertTrue(strategy.paused)
                self.assertEqual(strategy.status, "paused")
                self.assertEqual(strategy.risk.category, category)
                self.assertIn("high-risk", strategy.reason)

    def test_high_risk_record_data_pauses(self) -> None:
        strategy = plan_recovery_strategy(
            "verify_failed",
            [{"phase": "act", "status": "failed", "summary": "typed text", "data": {"text": "otp 123456"}}],
            goal="continue",
        )

        self.assertTrue(strategy.paused)
        self.assertEqual(strategy.risk.category, "credential")

    def test_mapping_payload_input_and_to_payload_are_json_ready(self) -> None:
        payload = {
            "status": "verify_failed",
            "goal": "click search",
            "records": [{"phase": "recovery", "status": "failed", "summary": "ax failed"}],
        }

        strategy = plan_recovery_strategy(payload)
        rendered = strategy.to_payload()

        self.assertEqual(strategy.source, "ocr")
        self.assertEqual(rendered["attempted"], ["ax"])
        self.assertEqual(rendered["risk"]["blocked"], False)

    def test_plan_desktop_recovery_alias_matches_primary_api(self) -> None:
        strategy = plan_desktop_recovery("tokenize_failed", [])

        self.assertEqual(strategy.source, "ax")
        self.assertEqual(strategy.action, "retry_ax_snapshot")

    def test_blocked_or_stopped_status_pauses(self) -> None:
        for status in ("blocked", "stopped"):
            with self.subTest(status=status):
                strategy = plan_recovery_strategy(status, [{"summary": "operator boundary"}])

                self.assertTrue(strategy.paused)
                self.assertIn(status, strategy.reason)

    def test_non_failure_status_waits_instead_of_escalating(self) -> None:
        strategy = plan_recovery_strategy("running", [{"phase": "observe", "status": "ok", "summary": "screen ok"}])

        self.assertEqual(strategy.action, "wait")
        self.assertEqual(strategy.source, "wait")

    def test_classify_recovery_risk_is_empty_safe(self) -> None:
        risk = classify_recovery_risk("", [])

        self.assertFalse(risk.blocked)
        self.assertEqual(risk.category, "")


if __name__ == "__main__":
    unittest.main()
