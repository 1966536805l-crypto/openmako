from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from subprocess import TimeoutExpired
from types import SimpleNamespace
from unittest.mock import patch


try:
    import quantagent.desktop_intelligence as desktop_intelligence
    from quantagent.desktop_control import DesktopResult
    from quantagent.desktop_intelligence import DesktopDecision, DesktopToken, DesktopTokenization, run_desktop_daemon
    from quantagent.desktop_workflow import DesktopStep
except Exception as exc:  # pragma: no cover - only used when the public API is absent.
    desktop_intelligence = None
    DesktopResult = None
    DesktopDecision = None
    DesktopToken = None
    DesktopTokenization = None
    DesktopStep = None
    run_desktop_daemon = None
    API_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    API_IMPORT_ERROR = ""

try:
    import quantagent.desktop_night_daemon as desktop_night_daemon
except Exception as exc:  # pragma: no cover - only used when the public API is absent.
    desktop_night_daemon = None
    NIGHT_API_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    NIGHT_API_IMPORT_ERROR = ""


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "desktop_daemon" / "toxic_scenarios.json"
HAS_DESKTOP_DAEMON_API = all(
    item is not None
    for item in (
        desktop_intelligence,
        DesktopResult,
        DesktopDecision,
        DesktopToken,
        DesktopTokenization,
        DesktopStep,
        run_desktop_daemon,
    )
)
HAS_NIGHT_DAEMON_API = desktop_night_daemon is not None and all(
    hasattr(desktop_night_daemon, name)
    for name in ("run_night_daemon",)
)


@unittest.skipIf(not HAS_DESKTOP_DAEMON_API, f"missing desktop daemon public API: {API_IMPORT_ERROR}")
class DesktopDaemonToxicFixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.scenarios = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    def tokenization(
        self,
        tokens: tuple[DesktopToken, ...] | None = None,
        *,
        observation_id: str = "obs-toxic",
        screen_hash: str = "screen-toxic",
        ok: bool = True,
        status: str = "ok",
        summary: str | None = None,
    ) -> DesktopTokenization:
        if tokens is None:
            tokens = (self.token("AX0001", "Search", center=(60, 35)),)
        return DesktopTokenization(
            ok,
            status,
            summary or f"{len(tokens)} token(s)",
            "shot.png",
            800,
            600,
            tokens,
            errors=() if ok else (summary or status,),
            path="tokens.json",
            observation_id=observation_id,
            screen_hash=screen_hash,
        )

    def token(
        self,
        token_id: str,
        text: str,
        *,
        role: str = "AXButton",
        source: str = "ax",
        center: tuple[int, int] = (60, 35),
        clickable: bool = True,
    ) -> DesktopToken:
        x, y = center
        return DesktopToken(
            token_id,
            text,
            role,
            source,
            bbox=(x - 50, y - 15, x + 50, y + 15),
            center=center,
            clickable=clickable,
            confidence=0.95,
        )

    def action_decision(self, action: str, args: dict[str, object], *, target_id: str = "", reason: str = "toxic action") -> DesktopDecision:
        step = DesktopStep(action, args, reason)
        return DesktopDecision(True, "action", action, args, target_id, reason, True, (), 0.9, step)

    def click_decision(self, tokenized: DesktopTokenization | None = None) -> DesktopDecision:
        tokenized = tokenized or self.tokenization()
        token = tokenized.tokens[0]
        target_hash = desktop_intelligence._token_hash(token)
        args = {
            "x": token.center[0],
            "y": token.center[1],
            "target_id": token.token_id,
            "target_hash": target_hash,
            "observation_id": tokenized.observation_id,
        }
        return self.action_decision("click", args, target_id=token.token_id, reason="click matched Search")

    def fenced_decision(self, action: str, tokenized: DesktopTokenization | None = None, **extra: object) -> DesktopDecision:
        tokenized = tokenized or self.tokenization()
        token = tokenized.tokens[0]
        args: dict[str, object] = {
            "target_id": token.token_id,
            "target_hash": desktop_intelligence._token_hash(token),
            "observation_id": tokenized.observation_id,
        }
        args.update(extra)
        return self.action_decision(action, args, target_id=token.token_id, reason=f"{action} matched Search")

    def test_stop_file_preempts_tokenization_and_desktop_actions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic stop ") as tmp:
            project = Path(tmp)
            stop_file = project / "STOP"
            stop_file.write_text("operator stop\n", encoding="utf-8")
            with patch.object(desktop_intelligence, "build_desktop_tokenization") as tokenize, patch.object(
                desktop_intelligence,
                "_execute_step",
            ) as execute:
                result = run_desktop_daemon(project, "click Search", execute=True, reviewed=True, allow_actions=True, stop_file=stop_file, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "stopped")
        tokenize.assert_not_called()
        execute.assert_not_called()

    def test_stop_file_created_mid_run_aborts_before_second_step(self) -> None:
        wait = self.action_decision("wait", {"seconds": 0}, reason="wait once")
        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic mid stop ") as tmp:
            project = Path(tmp)
            stop_file = project / "STOP"

            def stop_after_first_action(project_path: Path, step: DesktopStep) -> DesktopResult:
                stop_file.write_text("operator stopped after step 1\n", encoding="utf-8")
                return DesktopResult(step.action, True, "wait ok")

            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization()), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=wait,
            ), patch.object(desktop_intelligence, "_execute_step", side_effect=stop_after_first_action) as execute:
                result = run_desktop_daemon(project, "wait until stopped", execute=True, reviewed=True, allow_actions=True, stop_file=stop_file, max_steps=3, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "stopped")
        self.assertIn("before daemon step 2", result.summary)
        self.assertEqual(execute.call_count, 1)

    def test_tokenization_network_failure_is_failed_not_exception(self) -> None:
        secret = "sk-liveeeeeeeeeee"

        def fail_tokenization(*args: object, **kwargs: object) -> DesktopTokenization:
            raise ConnectionError(f"network token fetch failed api_key={secret}")

        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic token network ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=fail_tokenization), patch.object(
                desktop_intelligence,
                "_execute_step",
            ) as execute:
                result = run_desktop_daemon(Path(tmp), "observe desktop", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")
        self.assertIn("ConnectionError", result.summary)
        self.assertNotIn(secret, result.summary)
        execute.assert_not_called()

    def test_screenshot_permission_denied_stops_before_action(self) -> None:
        denied = DesktopResult(
            "screenshot",
            False,
            "could not create image from display; probable_cause=macOS Screen Recording permission is missing",
            {"diagnostics": {"display_available": True}},
        )
        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic screenshot ") as tmp:
            with patch.object(desktop_intelligence, "screenshot", return_value=denied), patch.object(desktop_intelligence, "_execute_step") as execute:
                result = run_desktop_daemon(Path(tmp), "observe desktop", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")
        self.assertIn("Screen Recording permission", result.summary)
        execute.assert_not_called()

    def test_daemon_artifacts_redact_sensitive_goal_and_action_payloads(self) -> None:
        secret = "sk-liveeeeeeeeeee"
        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic redact ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization()), patch.object(
                desktop_intelligence,
                "_execute_step",
            ) as execute:
                result = run_desktop_daemon(Path(tmp), f"type api_key={secret} into field", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

            artifacts = [
                Path(result.state_path).read_text(encoding="utf-8"),
                Path(result.query_events_path).read_text(encoding="utf-8"),
                Path(result.trajectory_path).read_text(encoding="utf-8"),
                Path(result.autopsy_path).read_text(encoding="utf-8"),
                json.dumps(result.to_payload(), ensure_ascii=False),
            ]

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertTrue(all(secret not in artifact for artifact in artifacts))
        self.assertTrue(any("[REDACTED]" in artifact for artifact in artifacts))
        execute.assert_not_called()

    def test_wait_dead_loop_exits_with_explicit_step_budget_status(self) -> None:
        wait = self.action_decision("wait", {"seconds": 0}, reason="wait without progress")
        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic wait ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization()), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=wait,
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("wait", True, "wait ok")):
                result = run_desktop_daemon(Path(tmp), "wait forever", execute=True, reviewed=True, allow_actions=True, max_steps=2, delay=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "step_budget_exhausted")
        self.assertIn("exhausted 2 step", result.summary)

    def test_same_point_click_loop_blocks_before_third_click(self) -> None:
        base = self.tokenization()
        changed = self.tokenization((self.token("AX0002", "Result", center=(300, 80)),), observation_id="obs-changed", screen_hash="screen-changed")
        sequence = [base, base, changed, base, base, changed, base]

        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic click loop ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=sequence), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=self.click_decision(base),
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("click", True, "click ok")) as execute:
                result = run_desktop_daemon(Path(tmp), "click Search", execute=True, reviewed=True, allow_actions=True, max_steps=4, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("loop detected", result.summary)
        self.assertEqual(execute.call_count, 2)

    def test_password_field_input_goal_blocks_before_action(self) -> None:
        password_field = self.token("AX0009", "Password", role="AXTextField", center=(120, 90))
        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic password ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization((password_field,))), patch.object(
                desktop_intelligence,
                "_execute_step",
            ) as execute:
                result = run_desktop_daemon(Path(tmp), "type hunter2 into password field", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("high-risk", result.summary)
        execute.assert_not_called()

    def test_payment_trade_delete_and_message_goals_block(self) -> None:
        goals = (
            "pay the invoice now",
            "buy 100 shares and confirm the trade",
            "delete all customer records",
            "发消息给客户",
        )
        for goal in goals:
            with self.subTest(goal=goal), tempfile.TemporaryDirectory(prefix="desktop daemon toxic risk ") as tmp:
                with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization()), patch.object(
                    desktop_intelligence,
                    "_execute_step",
                ) as execute:
                    result = run_desktop_daemon(Path(tmp), goal, execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

                self.assertFalse(result.ok)
                self.assertEqual(result.status, "blocked")
                self.assertIn("high-risk", result.summary)
                execute.assert_not_called()

    def test_high_risk_button_or_menu_target_text_blocks_before_action(self) -> None:
        cases = (
            ("click the primary button", self.token("AX0007", "Pay now", role="AXButton", center=(180, 90))),
            ("click the menu item", self.token("AX0008", "Sell position", role="AXMenuItem", center=(220, 130))),
        )
        for goal, token in cases:
            with self.subTest(goal=goal), tempfile.TemporaryDirectory(prefix="desktop daemon toxic target text ") as tmp:
                with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization((token,))), patch.object(
                    desktop_intelligence,
                    "_execute_step",
                ) as execute:
                    result = run_desktop_daemon(Path(tmp), goal, execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "blocked")
            self.assertIn("high-risk", result.summary)
            execute.assert_not_called()

    def test_policy_fence_blocks_mocked_high_risk_click_and_type_decisions(self) -> None:
        cases = (
            self.action_decision("click", {"x": 100, "y": 50, "target_text": "Delete account"}, reason="mocked click"),
            self.action_decision("type", {"text": "temporary seed phrase backup"}, reason="mocked type"),
        )
        for decision in cases:
            with self.subTest(action=decision.action), tempfile.TemporaryDirectory(prefix="desktop daemon toxic policy fence ") as tmp:
                with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization()), patch.object(
                    desktop_intelligence,
                    "decide_desktop_action",
                    return_value=decision,
                ), patch.object(desktop_intelligence, "_execute_step") as execute:
                    result = run_desktop_daemon(Path(tmp), "fill the selected control", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "blocked")
            self.assertIn("high-risk", result.summary)
            execute.assert_not_called()

    def test_cumulative_type_then_submit_sequence_blocks_before_submit(self) -> None:
        field = self.token("AX0010", "Message", role="AXTextField", center=(120, 90))
        pre = self.tokenization((field,), observation_id="obs-seq-pre", screen_hash="screen-seq-pre")
        typed_text = "draft ready"
        type_args = {
            "text": typed_text,
            "target_id": field.token_id,
            "target_hash": desktop_intelligence._token_hash(field),
            "observation_id": pre.observation_id,
        }
        type_decision = self.action_decision("type", type_args, target_id=field.token_id, reason="type draft")
        visible = self.tokenization(
            (self.token("OCR0010", typed_text, role="text", source="ocr", center=(160, 100)),),
            observation_id="obs-seq-visible",
            screen_hash="screen-seq-visible",
        )
        submit_decision = self.action_decision("hotkey", {"keys": ["return"]}, reason="submit current form")

        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic sequence ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[pre, pre, visible, visible, visible]), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                side_effect=[type_decision, submit_decision],
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("type", True, "type ok")) as execute:
                result = run_desktop_daemon(Path(tmp), "fill the current form", execute=True, reviewed=True, allow_actions=True, max_steps=2, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("cumulative desktop action risk", result.summary)
        self.assertEqual(execute.call_count, 1)
        self.assertTrue(any(record.phase == "sequence_policy" for record in result.records))

    def test_cumulative_type_then_send_click_blocks_before_send(self) -> None:
        field = self.token("AX0016", "Message", role="AXTextField", center=(120, 90))
        pre = self.tokenization((field,), observation_id="obs-send-pre", screen_hash="screen-send-pre")
        typed_text = "draft ready"
        type_args = {
            "text": typed_text,
            "target_id": field.token_id,
            "target_hash": desktop_intelligence._token_hash(field),
            "observation_id": pre.observation_id,
        }
        type_decision = self.action_decision("type", type_args, target_id=field.token_id, reason="type draft")
        send = self.token("AX0017", "Send", role="AXButton", center=(260, 90))
        visible = self.tokenization(
            (field, send, self.token("OCR0016", typed_text, role="text", source="ocr", center=(160, 100))),
            observation_id="obs-send-visible",
            screen_hash="screen-send-visible",
        )
        send_decision = self.action_decision(
            "click",
            {
                "x": send.center[0],
                "y": send.center[1],
                "target_id": send.token_id,
                "target_hash": desktop_intelligence._token_hash(send),
                "target_text": "Send",
                "observation_id": visible.observation_id,
            },
            target_id=send.token_id,
            reason="click Send",
        )

        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic send sequence ") as tmp:
            with patch.object(desktop_intelligence, "_decision_policy_block", return_value=""), patch.object(
                desktop_intelligence,
                "build_desktop_tokenization",
                side_effect=[pre, pre, visible, visible],
            ), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                side_effect=[type_decision, send_decision],
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("type", True, "type ok")) as execute:
                result = run_desktop_daemon(Path(tmp), "draft and send the message", execute=True, reviewed=True, allow_actions=True, max_steps=2, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("cumulative desktop action risk", result.summary)
        self.assertEqual(execute.call_count, 1)
        self.assertTrue(any(record.phase == "sequence_policy" for record in result.records))

    def test_textarea_shift_enter_inserts_newline_without_sequence_block(self) -> None:
        area = self.token("AX0011", "Notes", role="AXTextArea", center=(120, 90))
        pre = self.tokenization((area,), observation_id="obs-textarea-pre", screen_hash="screen-textarea-pre")
        typed_text = "line one"
        type_args = {
            "text": typed_text,
            "target_id": area.token_id,
            "target_hash": desktop_intelligence._token_hash(area),
            "observation_id": pre.observation_id,
        }
        type_decision = self.action_decision("type", type_args, target_id=area.token_id, reason="type line")
        visible_area = self.token("AX0011", "Notes", role="AXTextArea", center=(120, 90))
        visible = self.tokenization(
            (visible_area, self.token("OCR0011", typed_text, role="text", source="ocr", center=(160, 100))),
            observation_id="obs-textarea-visible",
            screen_hash="screen-textarea-visible",
        )
        hotkey_args = {
            "keys": ["shift", "return"],
            "target_id": area.token_id,
            "target_hash": desktop_intelligence._token_hash(visible_area),
            "observation_id": visible.observation_id,
        }
        newline_decision = self.action_decision("hotkey", hotkey_args, target_id=area.token_id, reason="insert newline")
        after_area = self.token("AX0011", "Notes", role="AXTextArea", center=(120, 90))
        after_newline = self.tokenization(
            (after_area, self.token("OCR0012", typed_text + "\n", role="text", source="ocr", center=(160, 120))),
            observation_id="obs-textarea-after",
            screen_hash="screen-textarea-after",
        )

        with tempfile.TemporaryDirectory(prefix="desktop daemon textarea sequence ") as tmp:
            with patch.object(
                desktop_intelligence,
                "build_desktop_tokenization",
                side_effect=[pre, pre, visible, visible, visible, visible, after_newline, after_newline],
            ), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                side_effect=[type_decision, newline_decision],
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("action", True, "ok")) as execute:
                result = run_desktop_daemon(Path(tmp), "fill notes", execute=True, reviewed=True, allow_actions=True, max_steps=2, delay=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "step_budget_exhausted")
        self.assertEqual(execute.call_count, 2)
        self.assertFalse(any(record.phase == "sequence_policy" for record in result.records))

    def test_navigation_url_return_does_not_trigger_sequence_block(self) -> None:
        field = self.token("AX0012", "Address", role="AXTextField", center=(120, 90))
        pre = self.tokenization((field,), observation_id="obs-url-pre", screen_hash="screen-url-pre")
        typed_text = "https://www.google.com/search?q=OpenMako"
        type_args = {
            "text": typed_text,
            "target_id": field.token_id,
            "target_hash": desktop_intelligence._token_hash(field),
            "observation_id": pre.observation_id,
        }
        type_decision = self.action_decision("type", type_args, target_id=field.token_id, reason="type deterministic search URL")
        visible_field = self.token("AX0012", "Address", role="AXTextField", center=(120, 90))
        visible = self.tokenization(
            (visible_field, self.token("OCR0013", typed_text, role="text", source="ocr", center=(180, 100))),
            observation_id="obs-url-visible",
            screen_hash="screen-url-visible",
        )
        hotkey_args = {
            "keys": ["return"],
            "target_id": field.token_id,
            "target_hash": desktop_intelligence._token_hash(visible_field),
            "observation_id": visible.observation_id,
        }
        navigate_decision = self.action_decision("hotkey", hotkey_args, target_id=field.token_id, reason="submit search")
        after_navigation = self.tokenization(
            (self.token("AX0013", "Results", role="AXGroup", center=(200, 120)),),
            observation_id="obs-url-after",
            screen_hash="screen-url-after",
        )

        with tempfile.TemporaryDirectory(prefix="desktop daemon url sequence ") as tmp:
            with patch.object(
                desktop_intelligence,
                "build_desktop_tokenization",
                side_effect=[pre, pre, visible, visible, visible, visible, after_navigation, after_navigation],
            ), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                side_effect=[type_decision, navigate_decision],
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("action", True, "ok")) as execute:
                result = run_desktop_daemon(Path(tmp), "search OpenMako", execute=True, reviewed=True, allow_actions=True, max_steps=2, delay=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "step_budget_exhausted")
        self.assertEqual(execute.call_count, 2)
        self.assertFalse(any(record.phase == "sequence_policy" for record in result.records))

    def test_command_palette_app_search_return_does_not_trigger_sequence_block(self) -> None:
        field = self.token("AX0014", "Search apps", role="AXTextField", center=(180, 90))
        pre = self.tokenization((field,), observation_id="obs-command-palette-pre", screen_hash="screen-command-palette-pre")
        typed_text = "Calculator"
        type_args = {
            "text": typed_text,
            "target_id": field.token_id,
            "target_hash": desktop_intelligence._token_hash(field),
            "observation_id": pre.observation_id,
        }
        type_decision = self.action_decision("type", type_args, target_id=field.token_id, reason="type app name into command palette")
        visible_field = self.token("AX0014", "Search apps", role="AXTextField", center=(180, 90))
        visible = self.tokenization(
            (visible_field, self.token("OCR0014", typed_text, role="text", source="ocr", center=(200, 110))),
            observation_id="obs-command-palette-visible",
            screen_hash="screen-command-palette-visible",
        )
        hotkey_args = {
            "keys": ["return"],
            "target_id": field.token_id,
            "target_hash": desktop_intelligence._token_hash(visible_field),
            "observation_id": visible.observation_id,
        }
        confirm_decision = self.action_decision("hotkey", hotkey_args, target_id=field.token_id, reason="confirm app search result")
        after_confirm = self.tokenization(
            (self.token("AX0015", "Calculator", role="AXWindow", center=(240, 140)),),
            observation_id="obs-command-palette-after",
            screen_hash="screen-command-palette-after",
        )

        with tempfile.TemporaryDirectory(prefix="desktop daemon command palette sequence ") as tmp:
            with patch.object(
                desktop_intelligence,
                "build_desktop_tokenization",
                side_effect=[pre, pre, visible, visible, visible, visible, after_confirm, after_confirm],
            ), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                side_effect=[type_decision, confirm_decision],
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("action", True, "ok")) as execute:
                result = run_desktop_daemon(Path(tmp), "open Calculator from app search", execute=True, reviewed=True, allow_actions=True, max_steps=2, delay=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "step_budget_exhausted")
        self.assertEqual(execute.call_count, 2)
        self.assertFalse(any(record.phase == "sequence_policy" for record in result.records))

    @unittest.skipIf(not HAS_NIGHT_DAEMON_API, f"missing night daemon public API: {NIGHT_API_IMPORT_ERROR}")
    def test_night_daemon_watch_timeout_pauses_without_task(self) -> None:
        clock = SimpleNamespace(value=100.0)

        def fake_monotonic() -> float:
            clock.value += 10.0
            return clock.value

        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic night timeout ") as tmp:
            with patch.object(desktop_night_daemon.time, "monotonic", side_effect=fake_monotonic), patch.object(
                desktop_night_daemon.time,
                "sleep",
                return_value=None,
            ):
                result = desktop_night_daemon.run_night_daemon(Path(tmp), watch=True, max_minutes=0.001, idle_sleep=0, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "paused")
        self.assertIn("time budget exhausted", result.summary)

    def test_verify_no_progress_after_click_fails(self) -> None:
        tokenized = self.tokenization()
        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic verify ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=tokenized), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=self.click_decision(tokenized),
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("click", True, "click ok")):
                result = run_desktop_daemon(Path(tmp), "click Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "verify_failed")
        self.assertIn("no visible progress", result.summary)
        self.assertTrue(any(record.phase == "verify" for record in result.records))

    def test_stale_observation_blocks_click_before_execution(self) -> None:
        before = self.tokenization(observation_id="obs-before", screen_hash="screen-before")
        moved = self.tokenization((self.token("AX0001", "Search", center=(90, 35)),), observation_id="obs-after", screen_hash="screen-after")
        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic stale ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[before, moved]), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=self.click_decision(before),
            ), patch.object(desktop_intelligence, "_execute_step") as execute:
                result = run_desktop_daemon(Path(tmp), "click Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("target changed", result.summary)
        self.assertIn("center drift", result.summary)
        execute.assert_not_called()

    def test_observation_id_mismatch_blocks_before_execution(self) -> None:
        current = self.tokenization(observation_id="obs-current", screen_hash="screen-current")
        stale = self.tokenization(observation_id="obs-stale", screen_hash="screen-stale")
        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic obs mismatch ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=current) as tokenize, patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=self.click_decision(stale),
            ), patch.object(desktop_intelligence, "_execute_step") as execute:
                result = run_desktop_daemon(Path(tmp), "click Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("observation fence mismatch", result.summary)
        self.assertEqual(tokenize.call_count, 1)
        execute.assert_not_called()

    def test_type_without_target_fence_blocks_before_execution(self) -> None:
        type_decision = self.action_decision("type", {"text": "hello"}, reason="blind type")
        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic type fence ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization()), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=type_decision,
            ), patch.object(desktop_intelligence, "_execute_step") as execute:
                result = run_desktop_daemon(Path(tmp), "type hello", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("missing observation fence", result.summary)
        execute.assert_not_called()

    def test_hotkey_target_disappeared_blocks_before_execution(self) -> None:
        before = self.tokenization(observation_id="obs-before", screen_hash="screen-before")
        gone = self.tokenization((), observation_id="obs-after", screen_hash="screen-after")
        hotkey_decision = self.fenced_decision("hotkey", before, keys=["return"])
        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic hotkey gone ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[before, gone]), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=hotkey_decision,
            ), patch.object(desktop_intelligence, "_execute_step") as execute:
                result = run_desktop_daemon(Path(tmp), "press return", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("target disappeared", result.summary)
        execute.assert_not_called()

    def test_desktop_action_timeout_is_converted_to_failed_result(self) -> None:
        tokenized = self.tokenization()

        def timeout_action(project: Path, step: DesktopStep) -> DesktopResult:
            raise TimeoutExpired(cmd="osascript", timeout=10)

        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic timeout ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[tokenized, tokenized]), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=self.click_decision(tokenized),
            ), patch.object(desktop_intelligence, "_execute_step", side_effect=timeout_action):
                try:
                    result = run_desktop_daemon(Path(tmp), "click Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)
                except TimeoutExpired as exc:
                    self.fail(f"desktop action timeout escaped daemon instead of failed result: {exc}")

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")
        self.assertIn("timeout", result.summary.lower())

    def test_desktop_action_lock_serializes_concurrent_control_actions(self) -> None:
        tokenized = self.tokenization()
        hotkey = self.fenced_decision("hotkey", tokenized, keys=["tab"])
        active = 0
        max_active = 0
        starts = 0
        state_lock = threading.Lock()
        release = threading.Event()
        ready = threading.Event()

        def fake_execute(project: Path, step: DesktopStep) -> DesktopResult:
            nonlocal active, max_active, starts
            with state_lock:
                active += 1
                starts += 1
                max_active = max(max_active, active)
                if starts == 1:
                    ready.set()
            release.wait(timeout=2)
            with state_lock:
                active -= 1
            return DesktopResult(step.action, True, f"{step.action} ok")

        def run(project: Path) -> None:
            run_desktop_daemon(project, "按 tab", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        with tempfile.TemporaryDirectory(prefix="desktop daemon toxic lock a ") as tmp_a, tempfile.TemporaryDirectory(
            prefix="desktop daemon toxic lock b "
        ) as tmp_b, tempfile.TemporaryDirectory(prefix="desktop daemon toxic lock file ") as lock_tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=tokenized), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=hotkey,
            ), patch.object(desktop_intelligence, "_execute_step", side_effect=fake_execute), patch.object(
                desktop_intelligence,
                "desktop_action_lock_path",
                return_value=Path(lock_tmp) / "session.lock",
            ):
                first = threading.Thread(target=run, args=(Path(tmp_a),), daemon=True)
                second = threading.Thread(target=run, args=(Path(tmp_b),), daemon=True)
                first.start()
                self.assertTrue(ready.wait(timeout=2), "first action did not start")
                second.start()
                time.sleep(0.05)
                with state_lock:
                    observed_while_first_held = max_active
                release.set()
                first.join(timeout=2)
                second.join(timeout=2)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(observed_while_first_held, 1)
        self.assertEqual(max_active, 1)


if __name__ == "__main__":
    unittest.main()
