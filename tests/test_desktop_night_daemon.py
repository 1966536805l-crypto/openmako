from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import quantagent.desktop_intelligence as desktop_intelligence
import quantagent.desktop_night_daemon as desktop_night_daemon
from quantagent.desktop_control import DesktopResult
from quantagent.desktop_intelligence import DesktopDecision, DesktopToken, DesktopTokenization, run_desktop_daemon
from quantagent.desktop_workflow import DesktopStep
from quantagent.tool_execution import execute_tool


DESKTOP_EVAL_PACK = (
    {"id": "ND-001", "goal": "enqueue daemon run and report status", "tags": ("enqueue", "status", "state")},
    {"id": "ND-002", "goal": "STOP file exists before first observation", "tags": ("stop", "before_run")},
    {"id": "ND-003", "goal": "missing execute flag skips side effects", "tags": ("execute_flags", "skip")},
    {"id": "ND-004", "goal": "missing reviewed flag pauses side effects", "tags": ("execute_flags", "pause")},
    {"id": "ND-005", "goal": "missing allow-actions flag pauses control action", "tags": ("execute_flags", "pause")},
    {"id": "ND-006", "goal": "screenshot failure pauses run", "tags": ("screenshot_failure", "tokenize_failure", "pause")},
    {"id": "ND-007", "goal": "AX snapshot failure still records token errors", "tags": ("tokenize_failure", "trajectory")},
    {"id": "ND-008", "goal": "OCR failure still records token errors", "tags": ("tokenize_failure", "query_events")},
    {"id": "ND-009", "goal": "desktop click failure pauses run", "tags": ("desktop_action_failure", "pause")},
    {"id": "ND-010", "goal": "desktop hotkey failure pauses run", "tags": ("desktop_action_failure", "pause")},
    {"id": "ND-011", "goal": "semantic verify failure pauses typed text", "tags": ("verify_failure", "pause")},
    {"id": "ND-012", "goal": "semantic verify failure pauses click no-progress", "tags": ("verify_failure", "pause")},
    {"id": "ND-013", "goal": "high-risk payment goal blocks", "tags": ("high_risk", "block")},
    {"id": "ND-014", "goal": "high-risk trading goal blocks", "tags": ("high_risk", "block")},
    {"id": "ND-015", "goal": "high-risk credential goal blocks", "tags": ("high_risk", "block")},
    {"id": "ND-016", "goal": "loop detector blocks repeated action", "tags": ("loop", "block")},
    {"id": "ND-017", "goal": "step budget exhausted returns explicit status", "tags": ("budget_exhausted", "status")},
    {"id": "ND-018", "goal": "resume paused task after operator fix", "tags": ("resume", "pause")},
    {"id": "ND-019", "goal": "state file exists after terminal status", "tags": ("state", "status")},
    {"id": "ND-020", "goal": "trajectory file exists after observation", "tags": ("trajectory", "artifact")},
    {"id": "ND-021", "goal": "query events file exists after run", "tags": ("query_events", "artifact")},
    {"id": "ND-022", "goal": "target stale before action blocks", "tags": ("stale_target", "block")},
    {"id": "ND-023", "goal": "missing observation fence blocks", "tags": ("observation_fence", "block")},
    {"id": "ND-024", "goal": "hold decision completes without action", "tags": ("hold", "status")},
    {"id": "ND-025", "goal": "no deterministic match exits skipped", "tags": ("skip", "status")},
    {"id": "ND-026", "goal": "type action visible text verifies", "tags": ("verify_success", "type")},
    {"id": "ND-027", "goal": "click target disappearance verifies progress", "tags": ("verify_success", "click")},
    {"id": "ND-028", "goal": "search flow advances one action per step", "tags": ("search", "budget_exhausted")},
    {"id": "ND-029", "goal": "STOP file path can be overridden", "tags": ("stop", "state")},
    {"id": "ND-030", "goal": "autopsy is written on paused or failed run", "tags": ("pause", "artifact")},
    {"id": "ND-031", "goal": "queue resume is idempotent", "tags": ("resume", "idempotent", "recovery")},
)


class DesktopNightDaemonEvalPackTest(unittest.TestCase):
    def tokenization(
        self,
        tokens: tuple[DesktopToken, ...] | None = None,
        *,
        ok: bool = True,
        status: str = "ok",
        summary: str = "1 token(s)",
        observation_id: str = "obs-night",
        screen_hash: str = "screen-night",
    ) -> DesktopTokenization:
        if tokens is None:
            tokens = (
                DesktopToken(
                    "AX0001",
                    "Search",
                    "AXButton",
                    "ax",
                    bbox=(10, 20, 110, 50),
                    center=(60, 35),
                    clickable=True,
                    confidence=0.9,
                ),
            )
        return DesktopTokenization(
            ok,
            status,
            summary,
            "shot.png",
            800,
            600,
            tokens,
            errors=() if ok else (summary,),
            path="tokens.json",
            observation_id=observation_id,
            screen_hash=screen_hash,
        )

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
        return DesktopDecision(
            True,
            "action",
            "click",
            args,
            token.token_id,
            "click matched Search",
            True,
            (),
            0.9,
            DesktopStep("click", args, "click matched Search"),
        )

    def hold_decision(self, reason: str = "night daemon reached hold") -> DesktopDecision:
        return DesktopDecision(True, "hold", "", {}, "", reason, False, (), 0.0, None)

    def wait_decision(self) -> DesktopDecision:
        return DesktopDecision(
            True,
            "action",
            "wait",
            {"seconds": 0},
            "",
            "wait and continue",
            False,
            (),
            0.5,
            DesktopStep("wait", {"seconds": 0}, "wait and continue", requires_review=False),
        )

    def assertPausedOrFailed(self, status: str) -> None:
        self.assertIn(status, {"paused", "failed", "verify_failed", "blocked"})

    def assert_daemon_files_exist(self, payload: dict[str, str]) -> None:
        for key in ("state_path", "trajectory_path", "query_events_path"):
            path = Path(payload[key])
            self.assertTrue(path.exists(), key)
            self.assertGreater(path.stat().st_size, 0, key)

    def test_eval_pack_has_30_cases_and_required_behavior_tags(self) -> None:
        required = {
            "enqueue",
            "status",
            "stop",
            "execute_flags",
            "skip",
            "pause",
            "screenshot_failure",
            "tokenize_failure",
            "desktop_action_failure",
            "verify_failure",
            "high_risk",
            "block",
            "loop",
            "budget_exhausted",
            "resume",
            "trajectory",
            "state",
            "query_events",
        }
        tags = {tag for case in DESKTOP_EVAL_PACK for tag in case["tags"]}

        self.assertGreaterEqual(len(DESKTOP_EVAL_PACK), 30)
        self.assertTrue(required.issubset(tags), sorted(required - tags))
        self.assertEqual(len({case["id"] for case in DESKTOP_EVAL_PACK}), len(DESKTOP_EVAL_PACK))

    def test_enqueue_like_tool_status_writes_state_trajectory_and_query_events(self) -> None:
        with tempfile.TemporaryDirectory(prefix="night daemon status ") as tmp:
            project = Path(tmp)
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization()), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=self.hold_decision("status ready"),
            ):
                result = execute_tool(
                    project,
                    "desktop.daemon",
                    {"goal": "observe current state", "execute": False, "max_steps": 1, "delay": 0},
                    owner_approved=True,
                )
            state = json.loads(Path(result.data["state_path"]).read_text(encoding="utf-8"))
            self.assert_daemon_files_exist(result.data)

        self.assertTrue(result.ok)
        self.assertEqual(result.name, "desktop.daemon")
        self.assertEqual(result.data["status"], "completed")
        self.assertEqual(state["status"], "completed")

    def test_stop_file_before_run_aborts_without_tokenizing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="night daemon stop ") as tmp:
            project = Path(tmp)
            stop = project / "STOP"
            stop.write_text("stop\n", encoding="utf-8")
            with patch.object(desktop_intelligence, "build_desktop_tokenization") as tokenize:
                result = run_desktop_daemon(project, "点击 Search", execute=True, reviewed=True, allow_actions=True, stop_file=stop, delay=0)
            state_exists = Path(result.state_path).exists()

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "stopped")
        self.assertTrue(state_exists)
        tokenize.assert_not_called()

    def test_missing_execute_flags_skip_or_pause_before_desktop_side_effect(self) -> None:
        tokenized = self.tokenization()
        click = self.click_decision(tokenized)
        with tempfile.TemporaryDirectory(prefix="night daemon flags ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=tokenized), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=click,
            ), patch.object(desktop_intelligence, "_execute_step") as execute:
                result = run_desktop_daemon(Path(tmp), "点击 Search", execute=False, max_steps=1, delay=0)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "skipped")
        self.assertIn("--execute", result.summary)
        self.assertIn("--reviewed", result.summary)
        self.assertIn("--allow-actions", result.summary)
        execute.assert_not_called()

    def test_task_daemon_options_cannot_escalate_outer_execute_gates(self) -> None:
        tokenized = self.tokenization()
        click = self.click_decision(tokenized)
        with tempfile.TemporaryDirectory(prefix="night daemon task gate ") as tmp:
            project = Path(tmp)
            desktop_night_daemon.enqueue_night_daemon(
                project,
                "点击 Search",
                execute=True,
                reviewed=True,
                allow_actions=True,
                max_steps=1,
                delay=0,
            )
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=tokenized), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=click,
            ), patch.object(desktop_intelligence, "_execute_step") as execute:
                result = desktop_night_daemon.run_night_daemon(
                    project,
                    execute=False,
                    reviewed=False,
                    allow_actions=False,
                    max_tasks=1,
                    max_minutes=None,
                    delay=0,
                )
            tasks = desktop_night_daemon.load_night_tasks(project)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "done")
        self.assertEqual(tasks[0].status, "done")
        self.assertEqual(tasks[0].result_status, "skipped")
        self.assertIn("--execute", tasks[0].summary)
        self.assertIn("--reviewed", tasks[0].summary)
        self.assertIn("--allow-actions", tasks[0].summary)
        execute.assert_not_called()

    def test_screenshot_or_tokenize_failure_pauses_with_autopsy(self) -> None:
        failed_tokens = self.tokenization((), ok=False, status="failed", summary="screenshot failed")
        with tempfile.TemporaryDirectory(prefix="night daemon tokenize fail ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=failed_tokens):
                result = run_desktop_daemon(Path(tmp), "点击 Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)
            autopsy_exists = Path(result.autopsy_path).exists()
            self.assert_daemon_files_exist(result.to_payload())

        self.assertFalse(result.ok)
        self.assertPausedOrFailed(result.status)
        self.assertIn("tokenize failed", result.summary)
        self.assertTrue(autopsy_exists)

    def test_desktop_action_failure_pauses_after_preflight(self) -> None:
        tokenized = self.tokenization()
        click = self.click_decision(tokenized)
        with tempfile.TemporaryDirectory(prefix="night daemon action fail ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[tokenized, tokenized]), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=click,
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("click", False, "click failed")):
                result = run_desktop_daemon(Path(tmp), "点击 Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)
            autopsy_exists = Path(result.autopsy_path).exists()

        self.assertFalse(result.ok)
        self.assertPausedOrFailed(result.status)
        self.assertIn("action failed", result.summary)
        self.assertEqual(result.results[0].action, "click")
        self.assertTrue(autopsy_exists)

    def test_verify_failure_pauses_when_action_has_no_visible_progress(self) -> None:
        tokenized = self.tokenization()
        click = self.click_decision(tokenized)
        with tempfile.TemporaryDirectory(prefix="night daemon verify fail ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[tokenized, tokenized, tokenized]), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=click,
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("click", True, "click ok")):
                result = run_desktop_daemon(Path(tmp), "点击 Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)
            autopsy_exists = Path(result.autopsy_path).exists()

        self.assertFalse(result.ok)
        self.assertPausedOrFailed(result.status)
        self.assertIn("semantic verify failed", result.summary)
        self.assertTrue(any(record.phase == "verify" for record in result.records))
        self.assertTrue(autopsy_exists)

    def test_high_risk_goal_blocks_before_desktop_action(self) -> None:
        with tempfile.TemporaryDirectory(prefix="night daemon high risk ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization()), patch.object(
                desktop_intelligence,
                "_execute_step",
            ) as execute:
                result = run_desktop_daemon(Path(tmp), "一整晚帮我买入股票并确认交易", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(result.ok)
        self.assertEqual(result.status, "blocked")
        self.assertIn("high-risk", result.summary)
        execute.assert_not_called()

    def test_loop_detection_and_step_budget_exhaustion_are_explicit(self) -> None:
        hotkey = DesktopDecision(
            True,
            "action",
            "hotkey",
            {"keys": ["tab"]},
            "",
            "press tab",
            True,
            (),
            0.8,
            DesktopStep("hotkey", {"keys": ["tab"]}, "press tab"),
        )
        with tempfile.TemporaryDirectory(prefix="night daemon loop ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization()), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=hotkey,
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("hotkey", True, "hotkey ok")) as execute:
                looped = run_desktop_daemon(Path(tmp), "按 tab", execute=True, reviewed=True, allow_actions=True, max_steps=3, delay=0)

        with tempfile.TemporaryDirectory(prefix="night daemon budget ") as tmp:
            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=self.tokenization()), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=self.wait_decision(),
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("wait", True, "wait ok")):
                exhausted = run_desktop_daemon(Path(tmp), "等待", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

        self.assertFalse(looped.ok)
        self.assertEqual(looped.status, "blocked")
        self.assertIn("loop detected", looped.summary)
        self.assertEqual(execute.call_count, 2)
        self.assertTrue(exhausted.ok)
        self.assertEqual(exhausted.status, "step_budget_exhausted")

    def test_resume_paused_task_reuses_daemon_state_path_and_completes(self) -> None:
        tokenized = self.tokenization()
        click = self.click_decision(tokenized)
        with tempfile.TemporaryDirectory(prefix="night daemon resume ") as tmp:
            project = Path(tmp)
            with patch.object(desktop_intelligence, "build_desktop_tokenization", side_effect=[tokenized, tokenized]), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=click,
            ), patch.object(desktop_intelligence, "_execute_step", return_value=DesktopResult("click", False, "operator intervention needed")):
                paused = run_desktop_daemon(project, "点击 Search", execute=True, reviewed=True, allow_actions=True, max_steps=1, delay=0)

            with patch.object(desktop_intelligence, "build_desktop_tokenization", return_value=tokenized), patch.object(
                desktop_intelligence,
                "decide_desktop_action",
                return_value=self.hold_decision("resumed task complete"),
            ):
                resumed = run_desktop_daemon(project, "点击 Search", execute=False, max_steps=1, delay=0)
            state = json.loads(Path(resumed.state_path).read_text(encoding="utf-8"))

        self.assertFalse(paused.ok)
        self.assertPausedOrFailed(paused.status)
        self.assertTrue(resumed.ok)
        self.assertEqual(resumed.status, "completed")
        self.assertEqual(paused.state_path, resumed.state_path)
        self.assertEqual(state["summary"], "resumed task complete")

    def test_queue_resume_is_idempotent_and_does_not_duplicate_tasks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="night daemon resume idempotent ") as tmp:
            project = Path(tmp)
            task = desktop_night_daemon.enqueue_night_daemon(project, "点击 Search", task_id="night-toxic-resume")
            desktop_night_daemon.update_night_task(
                project,
                task.id,
                status="paused",
                attempts=1,
                summary="operator fix required",
                paused_reason="operator fix required",
            )
            stop = desktop_night_daemon.night_stop_file(project)
            stop.write_text("stale stop\n", encoding="utf-8")

            first = desktop_night_daemon.resume_night_daemon(project, task_id=task.id)
            second = desktop_night_daemon.resume_night_daemon(project, task_id=task.id)
            tasks = desktop_night_daemon.load_night_tasks(project)

        self.assertFalse(stop.exists())
        self.assertEqual(first["counts"]["queued"], 1)
        self.assertEqual(second["counts"]["queued"], 1)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].id, task.id)
        self.assertEqual(tasks[0].status, "queued")
        self.assertEqual(tasks[0].attempts, 1)
        self.assertEqual(tasks[0].paused_reason, "")


if __name__ == "__main__":
    unittest.main()
