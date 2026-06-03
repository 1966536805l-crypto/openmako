from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess, TimeoutExpired
from unittest.mock import patch

import quantagent.desktop_control as desktop_control
import quantagent.desktop_intelligence as desktop_intelligence
from quantagent.desktop_control import screenshot
from quantagent.desktop_daemon_core import run_desktop_daemon_core
from quantagent.desktop_daemon_policy import authorize_daemon_action
from quantagent.desktop_intelligence import DesktopDecision, DesktopToken, DesktopTokenization, run_desktop_daemon
from quantagent.desktop_workflow import DesktopStep


try:
    import quantagent.desktop_peekaboo as desktop_peekaboo
except Exception as exc:  # pragma: no cover - contract marker for absent optional driver.
    desktop_peekaboo = None
    PEEKABOO_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
else:
    PEEKABOO_IMPORT_ERROR = ""


HAS_PEEKABOO_DRIVER = desktop_peekaboo is not None and all(
    hasattr(desktop_peekaboo, name)
    for name in ("capture", "click", "parse_json_output")
)


class DesktopDriverSafetyTest(unittest.TestCase):
    def tokenization(self, text: str = "Search", *, token_id: str = "AX0001") -> DesktopTokenization:
        token = DesktopToken(
            token_id,
            text,
            "AXButton",
            "ax",
            bbox=(10, 20, 110, 50),
            center=(60, 35),
            clickable=True,
            confidence=0.95,
        )
        return DesktopTokenization(
            True,
            "ok",
            "1 token(s)",
            "shot.png",
            800,
            600,
            (token,),
            path="tokens.json",
            observation_id="obs-safe",
            screen_hash="screen-safe",
        )

    def test_missing_screen_recording_permission_returns_hint_without_throwing(self) -> None:
        def fake_run(args, timeout=20):
            command = [str(item) for item in args]
            if command[0] == "screencapture":
                return CompletedProcess(command, 1, "", "could not create image from display")
            if command[0] == "osascript" and "frontmost" in command[-1]:
                return CompletedProcess(command, 0, "Terminal\n", "")
            if command[0] == "osascript":
                return CompletedProcess(command, 0, "Terminal|Shell|0,0|800,600\n", "")
            if command[0] == "stat":
                return CompletedProcess(command, 0, "runner\n", "")
            if command[0] == "system_profiler":
                return CompletedProcess(command, 0, "Resolution: 800 x 600\n", "")
            return CompletedProcess(command, 127, "", "command not found")

        with tempfile.TemporaryDirectory(prefix="desktop driver permission ") as tmp, patch.object(desktop_control, "_run", side_effect=fake_run):
            result = screenshot(Path(tmp), name="denied.png")

        self.assertFalse(result.ok)
        self.assertIn("Screen Recording permission", result.summary)
        self.assertEqual(result.data["diagnostics"]["permission_hint"]["probable_cause"].split()[0], "macOS")

    def test_missing_desktop_command_is_converted_to_failed_result(self) -> None:
        step = DesktopStep("click", {"x": 10, "y": 10}, "raw click")
        with patch.object(desktop_intelligence, "_execute_step", side_effect=FileNotFoundError("peekaboo")):
            result = desktop_intelligence._safe_execute_step(Path("/tmp"), step)

        self.assertFalse(result.ok)
        self.assertEqual(result.data["error_type"], "FileNotFoundError")
        self.assertIn("desktop action exception", result.summary)

    def test_timeout_expired_is_converted_to_failed_result_with_budget_metadata(self) -> None:
        step = DesktopStep("click", {"x": 10, "y": 10}, "raw click")
        expired = TimeoutExpired(cmd=["peekaboo", "click", "10", "10"], timeout=0.05)
        with patch.object(desktop_intelligence, "_execute_step", side_effect=expired):
            result = desktop_intelligence._safe_execute_step(Path("/tmp"), step)

        self.assertFalse(result.ok)
        self.assertEqual(result.data["error_type"], "TimeoutExpired")
        self.assertEqual(result.data["timeout"], 0.05)

    def test_non_json_tokenizer_output_fails_closed_before_action(self) -> None:
        def bad_tokenizer(*_args, **_kwargs):
            raise json.JSONDecodeError("Expecting value", "not-json", 0)

        click = DesktopDecision(
            True,
            "action",
            "click",
            {"x": 60, "y": 35},
            "",
            "raw coordinate click",
            True,
            (),
            0.7,
            DesktopStep("click", {"x": 60, "y": 35}, "raw coordinate click"),
        )
        with tempfile.TemporaryDirectory(prefix="desktop driver nonjson ") as tmp, patch.object(
            desktop_intelligence,
            "build_desktop_tokenization",
            side_effect=bad_tokenizer,
        ), patch.object(desktop_intelligence, "decide_desktop_action", return_value=click), patch.object(
            desktop_intelligence,
            "_execute_step",
        ) as execute:
            result = run_desktop_daemon(Path(tmp), "click 60,35", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "failed")
        self.assertIn("JSONDecodeError", result.summary)
        execute.assert_not_called()

    def test_raw_coordinate_click_is_blocked_by_observation_fence_even_with_gates(self) -> None:
        tokenized = self.tokenization()
        raw_click = DesktopDecision(
            True,
            "action",
            "click",
            {"x": 60, "y": 35},
            "",
            "raw coordinate click",
            True,
            (),
            0.7,
            DesktopStep("click", {"x": 60, "y": 35}, "raw coordinate click"),
        )
        with tempfile.TemporaryDirectory(prefix="desktop driver coord ") as tmp, patch.object(
            desktop_intelligence,
            "build_desktop_tokenization",
            return_value=tokenized,
        ), patch.object(desktop_intelligence, "decide_desktop_action", return_value=raw_click), patch.object(
            desktop_intelligence,
            "_execute_step",
        ) as execute:
            result = run_desktop_daemon(Path(tmp), "click 60,35", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("missing observation fence", result.summary)
        execute.assert_not_called()

    def test_payment_trading_and_credential_text_are_denied_even_with_action_gates(self) -> None:
        cases = {
            "type password=abc123": ("type", {"text": "password=abc123"}, "credential"),
            "click Pay now": ("click", {"target_text": "Pay now"}, "payment"),
            "click Buy stock": ("click", {"target_text": "Buy stock"}, "trading"),
        }
        for label, (action, args, category) in cases.items():
            with self.subTest(label=label):
                decision = authorize_daemon_action({"action": action, "args": args}, goal="low risk wrapper", execute=True, reviewed=True, allow_actions=True)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.status, "blocked")
                self.assertEqual(decision.risk.category, category)

    def test_long_running_budget_prevents_second_step_without_sleeping(self) -> None:
        calls: list[str] = []
        ticks = iter([100.0, 100.0, 160.1])

        def monotonic() -> float:
            return next(ticks, 160.1)

        def decide(_tokens, context):
            return {"ok": True, "status": "action", "action": "wait", "summary": f"wait {context.step}", "side_effect": False}

        def act(_decision, context):
            calls.append(f"act-{context.step}")
            return {"ok": True, "status": "ok", "summary": "waited"}

        with tempfile.TemporaryDirectory(prefix="desktop driver budget ") as tmp:
            result = run_desktop_daemon_core(
                tmp,
                "wait until budget expires",
                decide=decide,
                act=act,
                max_steps=5,
                max_minutes=1,
                delay=0,
                monotonic=monotonic,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "time_budget_exhausted")
        self.assertEqual(calls, ["act-1"])
        self.assertIn("before step 2", result.summary)


@unittest.skipIf(not HAS_PEEKABOO_DRIVER, f"missing optional Peekaboo desktop driver API: {PEEKABOO_IMPORT_ERROR or 'contract not implemented'}")
class PeekabooDriverSafetyContractTest(unittest.TestCase):
    def test_non_json_output_is_rejected_not_treated_as_success(self) -> None:
        result = desktop_peekaboo.parse_json_output("peekaboo", "permission denied")
        self.assertFalse(result.ok)
        self.assertIn("non-json", result.summary.lower())

    def test_missing_binary_and_permission_denial_fail_closed(self) -> None:
        missing = desktop_peekaboo.capture(binary="/definitely/missing/peekaboo")
        self.assertFalse(missing.ok)
        self.assertRegex(missing.summary.lower(), r"missing|not found|permission|denied")

    def test_click_requires_low_risk_target_and_timeout_budget(self) -> None:
        denied = desktop_peekaboo.click(x=1, y=1, target_text="Pay invoice", timeout=0.05)
        self.assertFalse(denied.ok)
        self.assertRegex(denied.summary.lower(), r"blocked|deny|risk|payment")


if __name__ == "__main__":
    unittest.main()
