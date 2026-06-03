from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent.approvals import approve, list_approvals
from quantagent.cli import main
from quantagent.desktop_control import DesktopResult
import quantagent.desktop_overnight as desktop_overnight
from quantagent.desktop_overnight import build_desktop_overnight_plan, run_desktop_overnight


class DesktopOvernightTest(unittest.TestCase):
    def test_builds_observe_first_plan(self) -> None:
        plan = build_desktop_overnight_plan("打开 Safari 搜索 OpenMako 并截图")

        self.assertEqual(plan.steps[0].action, "screenshot")
        self.assertIn("Long-running desktop control", plan.safety_note)
        self.assertIn("activate", [step.action for step in plan.steps])

    def test_preview_writes_state_without_side_effects(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop overnight ") as tmp:
            result = run_desktop_overnight(Path(tmp), "截图", execute=False, max_rounds=3)
            state = json.loads(Path(result.state_path).read_text(encoding="utf-8"))

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "preview")
        self.assertEqual(state["status"], "preview")
        self.assertEqual(result.results, ())

    def test_blocks_high_risk_overnight_goal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop overnight ") as tmp:
            result = run_desktop_overnight(Path(tmp), "一整晚帮我买入股票", execute=True, reviewed=True, allow_actions=True)
            state_exists = Path(result.state_path).exists()

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("high-risk goal", result.summary)
        self.assertTrue(state_exists)

    def test_execute_requires_review_and_explicit_action_allowance(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop overnight ") as tmp:
            unreviewed = run_desktop_overnight(Path(tmp), "打开 Safari", execute=True, reviewed=False)
            blocked = run_desktop_overnight(Path(tmp), "打开 Safari", execute=True, reviewed=True, allow_actions=False)

        self.assertFalse(unreviewed.ok)
        self.assertIn("--reviewed", unreviewed.summary)
        self.assertFalse(blocked.ok)
        self.assertIn("--allow-actions", blocked.summary)

    def test_execute_runs_observe_act_verify_loop(self) -> None:
        calls: list[str] = []

        def fake_execute(project: Path, step: object) -> DesktopResult:
            action = getattr(step, "action")
            calls.append(action)
            return DesktopResult(action, True, f"{action} ok", {"action": action})

        with tempfile.TemporaryDirectory(prefix="desktop overnight ") as tmp:
            with patch.object(desktop_overnight, "_execute_step", side_effect=fake_execute):
                result = run_desktop_overnight(
                    Path(tmp),
                    "打开 Safari",
                    execute=True,
                    reviewed=True,
                    allow_actions=True,
                    max_rounds=1,
                    delay=0,
                )

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "completed")
        self.assertEqual(calls, ["screenshot", "open", "screenshot"])
        self.assertEqual([decision.phase for decision in result.decisions], ["observe", "act", "verify"])

    def test_action_approval_blocks_before_side_effect_and_creates_request(self) -> None:
        calls: list[str] = []

        def fake_execute(project: Path, step: object) -> DesktopResult:
            action = getattr(step, "action")
            calls.append(action)
            return DesktopResult(action, True, f"{action} ok", {"action": action})

        with tempfile.TemporaryDirectory(prefix="desktop overnight approval ") as tmp:
            project = Path(tmp)
            with patch.object(desktop_overnight, "_execute_step", side_effect=fake_execute):
                result = run_desktop_overnight(
                    project,
                    "打开 Safari",
                    execute=True,
                    reviewed=True,
                    allow_actions=True,
                    require_action_approval=True,
                    max_rounds=1,
                    delay=0,
                )
            approvals = list_approvals(project)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("approval required", result.summary)
        self.assertEqual(calls, ["screenshot"])
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0].tool, "desktop.step")
        self.assertEqual(approvals[0].status, "pending")

    def test_approved_action_approval_allows_matching_side_effect_once(self) -> None:
        calls: list[str] = []

        def fake_execute(project: Path, step: object) -> DesktopResult:
            action = getattr(step, "action")
            calls.append(action)
            return DesktopResult(action, True, f"{action} ok", {"action": action})

        with tempfile.TemporaryDirectory(prefix="desktop overnight approval ") as tmp:
            project = Path(tmp)
            with patch.object(desktop_overnight, "_execute_step", side_effect=fake_execute):
                blocked = run_desktop_overnight(
                    project,
                    "打开 Safari",
                    execute=True,
                    reviewed=True,
                    allow_actions=True,
                    require_action_approval=True,
                    max_rounds=1,
                    delay=0,
                )
                approval_id = blocked.results[-1].data["approval_id"]
                approve(project, str(approval_id))
                resumed = run_desktop_overnight(
                    project,
                    "打开 Safari",
                    execute=True,
                    reviewed=True,
                    allow_actions=True,
                    require_action_approval=True,
                    approval_id=str(approval_id),
                    max_rounds=1,
                    delay=0,
                )

        self.assertFalse(blocked.ok)
        self.assertTrue(resumed.ok, resumed.summary)
        self.assertEqual(resumed.status, "completed")
        self.assertEqual(calls, ["screenshot", "screenshot", "open", "screenshot"])

    def test_action_approval_rejects_mismatched_step(self) -> None:
        def fake_execute(project: Path, step: object) -> DesktopResult:
            action = getattr(step, "action")
            return DesktopResult(action, True, f"{action} ok", {"action": action})

        with tempfile.TemporaryDirectory(prefix="desktop overnight approval ") as tmp:
            project = Path(tmp)
            with patch.object(desktop_overnight, "_execute_step", side_effect=fake_execute):
                blocked = run_desktop_overnight(
                    project,
                    "打开 Safari",
                    execute=True,
                    reviewed=True,
                    allow_actions=True,
                    require_action_approval=True,
                    max_rounds=1,
                    delay=0,
                )
                approval_id = str(blocked.results[-1].data["approval_id"])
                approve(project, approval_id)
                resumed = run_desktop_overnight(
                    project,
                    "打开 Terminal",
                    execute=True,
                    reviewed=True,
                    allow_actions=True,
                    require_action_approval=True,
                    approval_id=approval_id,
                    max_rounds=1,
                    delay=0,
                )

        self.assertFalse(resumed.ok)
        self.assertEqual(resumed.status, "blocked")
        self.assertIn("fingerprint", resumed.summary)

    def test_stop_file_aborts_before_round(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop overnight ") as tmp:
            project = Path(tmp)
            stop = project / "STOP"
            stop.write_text("stop\n", encoding="utf-8")
            result = run_desktop_overnight(project, "截图", execute=True, reviewed=True, stop_file=stop)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "stopped")
        self.assertEqual(result.results, ())

    def test_cli_desktop_overnight_json_preview(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop overnight ") as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "desktop-overnight", "--project", tmp, "--json", "--max-rounds", "2", "截图"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "preview")
        self.assertIn("state_path", payload)

    def test_cli_desktop_overnight_action_approval_json(self) -> None:
        def fake_execute(project: Path, step: object) -> DesktopResult:
            action = getattr(step, "action")
            return DesktopResult(action, True, f"{action} ok", {"action": action})

        with tempfile.TemporaryDirectory(prefix="desktop overnight ") as tmp:
            stdout = io.StringIO()
            with patch.object(desktop_overnight, "_execute_step", side_effect=fake_execute), contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "desktop-overnight",
                        "--project",
                        tmp,
                        "--json",
                        "--execute",
                        "--reviewed",
                        "--allow-actions",
                        "--require-action-approval",
                        "--max-rounds",
                        "1",
                        "--delay",
                        "0",
                        "打开 Safari",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 1)
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("approval required", payload["summary"])


if __name__ == "__main__":
    unittest.main()
