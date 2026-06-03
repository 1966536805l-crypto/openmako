from __future__ import annotations

import unittest

from quantagent.desktop_daemon_policy import (
    authorize_daemon_action,
    classify_goal_risk,
    daemon_action_schema,
    is_side_effect_action,
    normalize_daemon_action,
)


class DesktopDaemonPolicyTest(unittest.TestCase):
    def test_blocks_high_risk_goal_categories(self) -> None:
        cases = {
            "帮我支付账单": "payment",
            "一整晚自动买入股票": "trading",
            "输入我的 password": "credential",
            "删除桌面所有文件": "destructive",
            "给客户发送消息": "message_send",
        }
        for goal, category in cases.items():
            with self.subTest(goal=goal):
                finding = classify_goal_risk(goal)
                self.assertTrue(finding.blocked)
                self.assertEqual(finding.category, category)

    def test_side_effect_requires_three_gates(self) -> None:
        decision = authorize_daemon_action("click", goal="点击 Search")

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.status, "needs_review")
        self.assertEqual(decision.missing_gates, ("--execute", "--reviewed", "--allow-actions"))

    def test_read_only_action_does_not_require_action_gates(self) -> None:
        decision = authorize_daemon_action("screenshot", goal="截图")

        self.assertTrue(decision.allowed)
        self.assertFalse(is_side_effect_action("screenshot"))

    def test_all_gates_allow_low_risk_side_effect(self) -> None:
        decision = authorize_daemon_action({"action": "type", "args": {"text": "OpenMako"}}, goal="输入 OpenMako", execute=True, reviewed=True, allow_actions=True)

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.action, "type")

    def test_typed_secret_or_payment_text_is_blocked_even_with_gates(self) -> None:
        decision = authorize_daemon_action({"action": "type", "args": {"text": "password=abc"}}, goal="输入内容", execute=True, reviewed=True, allow_actions=True)

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.risk.category, "credential")

    def test_action_schema_and_normalization_are_stable(self) -> None:
        schema = daemon_action_schema()
        action = normalize_daemon_action({"name": "open", "kind": "app", "label": "Safari"})

        self.assertIn("click", schema["properties"]["action"]["enum"])
        self.assertEqual(action.action, "open")
        self.assertEqual(action.args["kind"], "app")
        with self.assertRaises(ValueError):
            normalize_daemon_action("wire_money")


if __name__ == "__main__":
    unittest.main()
