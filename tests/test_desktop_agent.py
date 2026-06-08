from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent.cli import main
import quantagent.desktop_control as desktop_control
from quantagent.desktop_agent import build_desktop_agent_plan, run_desktop_agent
from quantagent.hook_events import read_query_events


class DesktopAgentTest(unittest.TestCase):
    def test_builds_fast_takeover_plan_without_model(self) -> None:
        plan = build_desktop_agent_plan("打开 Safari 搜索 OpenMako 并截图", browser="Safari")

        actions = [step.action for step in plan.steps]
        self.assertIn("activate", actions)
        self.assertIn("type", actions)
        self.assertIn("screenshot", actions)
        self.assertIn("OpenMako", json.dumps(plan.to_payload(), ensure_ascii=False))
        self.assertIn("Direct screen takeover", plan.safety_note)

    def test_type_text_stops_before_followup_desktop_commands(self) -> None:
        plan = build_desktop_agent_plan("输入 OpenMako 然后按 enter 并截图")
        steps = [(step.action, step.args) for step in plan.steps]
        step_payload = json.dumps([step.args for step in plan.steps], ensure_ascii=False)

        self.assertIn(("type", {"text": "OpenMako"}), steps)
        self.assertIn(("hotkey", {"keys": ["enter"]}), steps)
        self.assertIn(("screenshot", {}), steps)
        self.assertNotIn("然后按 enter", step_payload)
        self.assertNotIn("并截图", step_payload)

        click_plan = build_desktop_agent_plan("输入 hello 然后点击 10,20")
        click_steps = [(step.action, step.args) for step in click_plan.steps]

        self.assertIn(("type", {"text": "hello"}), click_steps)
        self.assertIn(("click", {"x": 10, "y": 20}), click_steps)

        search_plan = build_desktop_agent_plan("输入 hello 然后搜索 OpenMako")
        search_step_payload = json.dumps([step.args for step in search_plan.steps], ensure_ascii=False)

        self.assertIn(("type", {"text": "hello"}), [(step.action, step.args) for step in search_plan.steps])
        self.assertNotIn("然后搜索 OpenMako", search_step_payload)

        open_plan = build_desktop_agent_plan("输入 hello 然后打开 Safari")
        open_step_payload = json.dumps([step.args for step in open_plan.steps], ensure_ascii=False)

        self.assertIn(("type", {"text": "hello"}), [(step.action, step.args) for step in open_plan.steps])
        self.assertNotIn("然后打开 Safari", open_step_payload)

    def test_compound_desktop_actions_follow_instruction_order(self) -> None:
        type_then_click = build_desktop_agent_plan("输入 hello 然后点击 10,20")
        self.assertEqual([step.action for step in type_then_click.steps[:2]], ["type", "click"])

        click_then_type = build_desktop_agent_plan("点击 10,20 然后输入 hello")
        self.assertEqual([step.action for step in click_then_type.steps[:2]], ["click", "type"])

        hotkey_then_type = build_desktop_agent_plan("按 enter 然后输入 hello")
        self.assertEqual([step.action for step in hotkey_then_type.steps[:2]], ["hotkey", "type"])

        search_then_type = build_desktop_agent_plan("搜索 OpenMako 然后输入 hello")
        search_type_args = [step.args.get("text", "") for step in search_then_type.steps if step.action == "type"]

        self.assertEqual(search_type_args[0], "https://www.google.com/search?q=OpenMako")
        self.assertEqual(search_type_args[-1], "hello")
        self.assertFalse(any("然后输入" in item for item in search_type_args))

    def test_preview_writes_query_events_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop agent ") as tmp:
            result = run_desktop_agent(Path(tmp), "点击 10,20", execute=False)
            events = read_query_events(result.query_events_path)

        self.assertTrue(result.ok)
        self.assertEqual(result.run.status, "preview")
        self.assertEqual(events[-1].kind, "stop")

    def test_execute_requires_review_for_direct_takeover(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop agent ") as tmp:
            result = run_desktop_agent(Path(tmp), "点击 10,20", execute=True, reviewed=False)
            autopsy_exists = Path(result.autopsy_path).exists()

        self.assertFalse(result.ok)
        self.assertEqual(result.run.status, "blocked")
        self.assertIn("requires --reviewed", result.run.summary)
        self.assertTrue(autopsy_exists)

    def test_stop_file_aborts_before_any_side_effect(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop agent ") as tmp:
            project = Path(tmp)
            stop_file = project / "STOP"
            stop_file.write_text("stop\n", encoding="utf-8")

            result = run_desktop_agent(project, "点击 10,20", execute=True, reviewed=True, stop_file=stop_file)
            autopsy_exists = Path(result.autopsy_path).exists()

        self.assertFalse(result.ok)
        self.assertEqual(result.run.status, "stopped")
        self.assertEqual(result.run.results, ())
        self.assertTrue(autopsy_exists)

    def test_cli_desktop_agent_json_preview(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop agent ") as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "desktop-agent", "--project", tmp, "--json", "截图"])

            payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "preview")
        self.assertIn("stop_file", payload)
        self.assertEqual(payload["autopsy_path"], "")

    def test_screenshot_retries_once_before_failure(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: object, timeout: int = 20) -> subprocess.CompletedProcess[str]:
            command = [str(item) for item in args]  # type: ignore[union-attr]
            calls.append(command)
            if command[0] == "screencapture":
                shot = Path(command[-1])
                if len([call for call in calls if call[0] == "screencapture"]) == 2:
                    shot.parent.mkdir(parents=True, exist_ok=True)
                    shot.write_bytes(b"png")
                    return subprocess.CompletedProcess(command, 0, "", "")
                return subprocess.CompletedProcess(command, 1, "", "could not create image from display")
            raise AssertionError(f"unexpected command: {command}")

        with tempfile.TemporaryDirectory(prefix="desktop agent ") as tmp:
            with patch.object(desktop_control, "_run", side_effect=fake_run), patch.object(desktop_control.time, "sleep") as sleep:
                result = desktop_control.screenshot(Path(tmp), name="retry.png")

        self.assertTrue(result.ok)
        self.assertEqual(len([call for call in calls if call[0] == "screencapture"]), 2)
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual(len(result.data["attempts"]), 2)

    def test_screenshot_failure_includes_diagnostics_after_fallback(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: object, timeout: int = 20) -> subprocess.CompletedProcess[str]:
            command = [str(item) for item in args]  # type: ignore[union-attr]
            calls.append(command)
            if command[0] == "screencapture":
                return subprocess.CompletedProcess(command, 1, "", "could not create image from display")
            if command[0] == "osascript":
                return subprocess.CompletedProcess(command, 0, "Codex\n", "")
            if command[0] == "stat":
                return subprocess.CompletedProcess(command, 0, "testuser\n", "")
            if command[0] == "system_profiler":
                return subprocess.CompletedProcess(command, 0, "Resolution: 1920 x 1080\n", "")
            raise AssertionError(f"unexpected command: {command}")

        with tempfile.TemporaryDirectory(prefix="desktop agent ") as tmp:
            with patch.object(desktop_control, "_run", side_effect=fake_run), patch.object(desktop_control.time, "sleep"):
                result = desktop_control.screenshot(Path(tmp), name="fail.png")

        self.assertFalse(result.ok)
        self.assertIn("diagnostics:", result.summary)
        self.assertIn("probable_cause=macOS Screen Recording permission is missing", result.summary)
        self.assertEqual(len([call for call in calls if call[0] == "screencapture"]), 3)
        self.assertEqual(result.data["diagnostics"]["console_user"], "testuser")
        self.assertEqual(result.data["diagnostics"]["display_available"], True)
        self.assertIn("permission_hint", result.data["diagnostics"])

    def test_fast_screenshot_diagnostics_skip_display_probe(self) -> None:
        calls: list[list[str]] = []

        def fake_run(args: object, timeout: int = 20) -> subprocess.CompletedProcess[str]:
            command = [str(item) for item in args]  # type: ignore[union-attr]
            calls.append(command)
            if command[0] == "screencapture":
                return subprocess.CompletedProcess(command, 1, "", "could not create image from display")
            if command[0] == "osascript":
                return subprocess.CompletedProcess(command, 0, "Terminal\n", "")
            if command[0] == "stat":
                return subprocess.CompletedProcess(command, 0, "testuser\n", "")
            if command[0] == "system_profiler":
                raise AssertionError("fast diagnostics should not run system_profiler")
            raise AssertionError(f"unexpected command: {command}")

        with tempfile.TemporaryDirectory(prefix="desktop agent fast diag ") as tmp:
            with patch.object(desktop_control, "_run", side_effect=fake_run), patch.object(
                desktop_control.time,
                "sleep",
            ), patch.dict(os.environ, {desktop_control.FAST_SCREENSHOT_DIAGNOSTICS_ENV: "1"}, clear=False):
                result = desktop_control.screenshot(Path(tmp), name="fast-fail.png")

        self.assertFalse(result.ok)
        self.assertEqual(len([call for call in calls if call[0] == "screencapture"]), 3)
        self.assertFalse(any(call[0] == "system_profiler" for call in calls))
        self.assertEqual(result.data["diagnostics"]["display_probe"], "skipped_fast_diagnostics")
        self.assertEqual(result.data["diagnostics"]["display_available"], "skipped")
        self.assertIn("may be missing", result.data["diagnostics"]["permission_hint"]["probable_cause"])


if __name__ == "__main__":
    unittest.main()
