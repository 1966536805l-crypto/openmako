from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from quantagent.cli import main
from quantagent.desktop_control import DesktopResult
from quantagent.desktop_send_confirm import DesktopSendConfirmation, run_desktop_send_confirm


class DesktopSendConfirmTest(unittest.TestCase):
    def fake_sender(self, calls: list[str]):
        def sender(text: str) -> tuple[DesktopResult, DesktopResult]:
            calls.append(text)
            return (
                DesktopResult("type", True, f"typed {len(text)} chars"),
                DesktopResult("hotkey", True, "hotkey: return"),
            )

        return sender

    def fake_confirmer(self, observed_counts: list[int]):
        calls: list[int] = []

        def confirmer(_project: Path, _text: str, expected_count: int, _timeout: float, _poll: float) -> DesktopSendConfirmation:
            calls.append(expected_count)
            observed = observed_counts.pop(0)
            return DesktopSendConfirmation(
                observed >= expected_count,
                "confirmed" if observed >= expected_count else "not_confirmed",
                f"observed {observed}, expected {expected_count}",
                observed_count=observed,
                expected_count=expected_count,
            )

        confirmer.calls = calls  # type: ignore[attr-defined]
        return confirmer

    def test_preview_writes_log_without_side_effects(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory(prefix="desktop send confirm ") as tmp:
            result = run_desktop_send_confirm(Path(tmp), "1", count=10, sender=self.fake_sender(calls))
            log_exists = Path(result.log_path).exists()

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "preview")
        self.assertEqual(calls, [])
        self.assertTrue(log_exists)

    def test_execute_requires_review(self) -> None:
        calls: list[str] = []
        with tempfile.TemporaryDirectory(prefix="desktop send confirm ") as tmp:
            result = run_desktop_send_confirm(Path(tmp), "1", count=1, execute=True, sender=self.fake_sender(calls))

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(calls, [])

    def test_execute_sends_next_message_only_after_confirmation(self) -> None:
        calls: list[str] = []
        confirmer = self.fake_confirmer([3, 4, 5])
        with tempfile.TemporaryDirectory(prefix="desktop send confirm ") as tmp:
            result = run_desktop_send_confirm(
                Path(tmp),
                "1",
                count=2,
                execute=True,
                reviewed=True,
                sender=self.fake_sender(calls),
                confirmer=confirmer,
                interval=0,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(result.confirmed_count, 2)
        self.assertEqual(calls, ["1", "1"])
        self.assertEqual(confirmer.calls, [0, 4, 5])  # type: ignore[attr-defined]

    def test_confirmation_failure_stops_remaining_sends(self) -> None:
        calls: list[str] = []
        confirmer = self.fake_confirmer([10, 11, 11])
        with tempfile.TemporaryDirectory(prefix="desktop send confirm ") as tmp:
            result = run_desktop_send_confirm(
                Path(tmp),
                "1",
                count=3,
                execute=True,
                reviewed=True,
                sender=self.fake_sender(calls),
                confirmer=confirmer,
                interval=0,
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "confirm_failed")
        self.assertEqual(result.confirmed_count, 1)
        self.assertEqual(calls, ["1", "1"])

    def test_cli_preview_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop send confirm cli ") as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "desktop", "--project", tmp, "--json", "send-confirm", "1", "--count", "2"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "preview")
        self.assertEqual(payload["requested_count"], 2)


if __name__ == "__main__":
    unittest.main()
