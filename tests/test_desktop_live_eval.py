from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from quantagent.desktop_control import DesktopResult
from quantagent.desktop_eval import SUCCESS, run_desktop_eval
from quantagent.desktop_eval_scenarios import load_desktop_eval_suite
from quantagent.desktop_live_eval import run_live_desktop_eval_scenario
from quantagent.desktop_live import DesktopProbeStatus


class DesktopLiveEvalTest(unittest.TestCase):
    def test_suite_live_dry_run_does_not_invoke_live_runner(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop live eval dry ") as tmp:
            with patch("quantagent.desktop_live_eval.run_live_desktop_eval_scenario") as runner:
                result = run_desktop_eval(tmp, suite="suite_live")

        self.assertTrue(result.ok)
        self.assertEqual(result.metrics["dry_run"], len(load_desktop_eval_suite("suite_live")))
        runner.assert_not_called()

    def test_suite_live_default_runner_scores_expected_live_observations(self) -> None:
        scenarios = [
            {
                "id": "ready",
                "goal": "probe readiness",
                "expected_status": "success",
                "setup": {"kind": "live_readiness_probe", "include_permissions": True},
            },
            {
                "id": "offline",
                "goal": "probe offline",
                "expected_status": "success",
                "setup": {"kind": "live_network_failure_probe", "network_url": "https://example.invalid"},
            },
            {
                "id": "stop",
                "goal": "click Search",
                "expected_status": "stopped",
                "setup": {"kind": "live_stop_file_preempts_daemon"},
            },
            {
                "id": "guard",
                "goal": "click loop",
                "expected_status": "stopped",
                "setup": {"kind": "live_guardian_loop_stop"},
            },
        ]
        ready = [
            DesktopProbeStatus("frontmost_app", True, "ok", "Terminal"),
            DesktopProbeStatus("front_window", True, "ok", "Terminal|Window"),
            DesktopProbeStatus("screenshot_permission", True, "ok", "screenshot ok"),
            DesktopProbeStatus("accessibility_snapshot", True, "ok", "ax ok"),
        ]
        offline = [
            DesktopProbeStatus("frontmost_app", True, "ok", "Terminal"),
            DesktopProbeStatus("front_window", True, "ok", "Terminal|Window"),
            DesktopProbeStatus("network", False, "network_failed", "offline"),
        ]
        daemon = SimpleNamespace(status="stopped", summary="STOP file present", to_payload=lambda: {"status": "stopped"})
        guardian = SimpleNamespace(status="stopped", summary="guardian wrote STOP", to_payload=lambda: {"status": "stopped"})

        with tempfile.TemporaryDirectory(prefix="desktop live eval run ") as tmp:
            with patch("quantagent.desktop_live_eval.build_desktop_readiness_probes", side_effect=[ready, offline]), patch(
                "quantagent.desktop_live_eval.run_desktop_daemon",
                return_value=daemon,
            ), patch("quantagent.desktop_live_eval.inspect_desktop_guardian", return_value=guardian):
                result = run_desktop_eval(
                    Path(tmp),
                    suite="suite_live",
                    scenario=scenarios,
                    execute=True,
                    reviewed=True,
                    allow_actions=True,
                )

        self.assertTrue(result.ok, result.to_json())
        self.assertEqual(result.status, SUCCESS)
        self.assertEqual(result.metrics[SUCCESS], 4)
        self.assertEqual([item.data["observed_status"] for item in result.scenarios], ["success", "success", "stopped", "stopped"])

    def test_suite_live_observation_mismatch_fails_closed(self) -> None:
        scenarios = [
            {
                "id": "ready",
                "goal": "probe readiness",
                "expected_status": "success",
                "setup": {"kind": "live_readiness_probe", "include_permissions": True},
            }
        ]
        blocked = [DesktopProbeStatus("screenshot_permission", False, "permission_required", "Screen Recording permission is missing")]
        with tempfile.TemporaryDirectory(prefix="desktop live eval mismatch ") as tmp:
            with patch("quantagent.desktop_live_eval.build_desktop_readiness_probes", return_value=blocked):
                result = run_desktop_eval(tmp, suite="suite_live", scenario=scenarios, execute=True, reviewed=True, allow_actions=True)

        self.assertFalse(result.ok)
        self.assertEqual(result.scenarios[0].status, "failure")
        self.assertEqual(result.scenarios[0].data["observed_status"], "blocked")

    def test_guardian_clean_ignores_stale_eval_stop_from_previous_cycle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop live eval repeat ") as tmp:
            project = Path(tmp)
            loop = run_live_desktop_eval_scenario(
                project,
                {"id": "loop", "goal": "click loop", "expected_status": "stopped", "setup": {"kind": "live_guardian_loop_stop"}},
                {"run_id": "repeat"},
            )
            clean = run_live_desktop_eval_scenario(
                project,
                {"id": "clean", "goal": "observe", "expected_status": "ok", "setup": {"kind": "live_guardian_clean"}},
                {"run_id": "repeat"},
            )

        self.assertTrue(loop["ok"], loop)
        self.assertTrue(clean["ok"], clean)
        self.assertEqual(clean["data"]["observed_status"], "success")

    def test_task_pool_probe_gates_side_effects_and_blocks_secrets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop live task pool ") as tmp:
            project = Path(tmp)
            gated = run_live_desktop_eval_scenario(
                project,
                {
                    "id": "type-safe",
                    "goal": "type safe local note",
                    "expected_status": "success",
                    "setup": {
                        "kind": "live_task_pool_probe",
                        "action": "type",
                        "args": {"text": "safe local note"},
                        "coverage": ["input", "type"],
                    },
                },
                {"run_id": "task-pool"},
            )
            blocked = run_live_desktop_eval_scenario(
                project,
                {
                    "id": "type-secret",
                    "goal": "type password hunter2",
                    "expected_status": "blocked",
                    "setup": {
                        "kind": "live_task_pool_probe",
                        "action": "type",
                        "args": {"text": "hunter2"},
                        "coverage": ["privacy", "credential"],
                    },
                },
                {"run_id": "task-pool"},
            )

        self.assertTrue(gated["ok"], gated)
        self.assertTrue(gated["data"]["side_effect"])
        self.assertEqual(gated["data"]["policy"]["status"], "needs_review")
        self.assertTrue(blocked["ok"], blocked)
        self.assertEqual(blocked["data"]["observed_status"], "blocked")

    def test_guardian_failure_recovery_probe_writes_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop live recovery ") as tmp:
            result = run_live_desktop_eval_scenario(
                Path(tmp),
                {
                    "id": "permission-stop",
                    "goal": "pause on permission failure",
                    "expected_status": "stopped",
                    "setup": {
                        "kind": "live_guardian_failure_stop",
                        "status": "running",
                        "summary": "Screen Recording permission is missing",
                    },
                },
                {"run_id": "recovery"},
            )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["observed_status"], "stopped")
        self.assertTrue(result["data"]["wrote_stop"])
        self.assertEqual(result["data"]["findings"][0]["code"], "permission_required")

    def test_tokenization_fluctuation_probe_accepts_stable_live_samples(self) -> None:
        samples = [
            _tokenization(ok=True, count=10, screen_hash="a", front_app="Terminal"),
            _tokenization(ok=True, count=11, screen_hash="a", front_app="Terminal"),
            _tokenization(ok=True, count=9, screen_hash="a", front_app="Terminal"),
        ]
        with tempfile.TemporaryDirectory(prefix="desktop live token stable ") as tmp:
            with patch("quantagent.desktop_live_eval.build_desktop_tokenization", side_effect=samples), patch(
                "quantagent.desktop_live_eval.time.sleep"
            ):
                result = run_live_desktop_eval_scenario(
                    Path(tmp),
                    {
                        "id": "token-stable",
                        "goal": "sample live desktop OCR and AX",
                        "expected_status": "success",
                        "setup": {
                            "kind": "live_tokenization_fluctuation_probe",
                            "cycles": 3,
                            "interval": 0.1,
                            "max_token_delta_ratio": 0.5,
                        },
                    },
                    {"run_id": "token-stable"},
                )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["observed_status"], "success")
        self.assertEqual(result["data"]["token_counts"], [10, 11, 9])

    def test_tokenization_fluctuation_probe_classifies_permission_failure(self) -> None:
        blocked = _tokenization(
            ok=False,
            count=0,
            status="failed",
            summary="Screen Recording permission is missing",
            errors=("Screen Recording permission is missing",),
        )
        with tempfile.TemporaryDirectory(prefix="desktop live token blocked ") as tmp:
            with patch("quantagent.desktop_live_eval.build_desktop_tokenization", return_value=blocked):
                result = run_live_desktop_eval_scenario(
                    Path(tmp),
                    {
                        "id": "token-blocked",
                        "goal": "sample live desktop OCR and AX",
                        "expected_status": "blocked",
                        "setup": {"kind": "live_tokenization_fluctuation_probe", "cycles": 2},
                    },
                    {"run_id": "token-blocked"},
                )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["observed_status"], "blocked")

    def test_window_switch_probe_executes_hotkey_and_records_before_after(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop live switch ") as tmp:
            with patch(
                "quantagent.desktop_live_eval.frontmost_app",
                side_effect=[
                    DesktopResult("frontmost", True, "Finder", {"stdout": "Finder"}),
                    DesktopResult("frontmost", True, "Safari", {"stdout": "Safari"}),
                ],
            ), patch(
                "quantagent.desktop_live_eval.front_window",
                side_effect=[
                    DesktopResult("window", True, "Finder|Documents|0,0|800,600"),
                    DesktopResult("window", True, "Safari|Start Page|0,0|800,600"),
                ],
            ), patch("quantagent.desktop_live_eval.activate_app", return_value=DesktopResult("activate", True, "activated Finder")), patch(
                "quantagent.desktop_live_eval.hotkey", return_value=DesktopResult("hotkey", True, "hotkey: cmd+tab")
            ), patch(
                "quantagent.desktop_live_eval.time.sleep"
            ):
                result = run_live_desktop_eval_scenario(
                    Path(tmp),
                    {
                        "id": "switch",
                        "goal": "press cmd+tab",
                        "expected_status": "success",
                        "setup": {
                            "kind": "live_window_switch_probe",
                            "prepare_apps": ["Finder"],
                            "keys": ["cmd", "tab"],
                            "require_change": True,
                            "settle_seconds": 0.1,
                        },
                    },
                    {"run_id": "switch"},
                )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["observed_status"], "success")
        self.assertTrue(result["data"]["changed"])
        self.assertEqual(result["data"]["hotkey"]["summary"], "hotkey: cmd+tab")
        self.assertEqual(result["data"]["prepare_apps"][0]["summary"], "activated Finder")

    def test_window_switch_probe_fails_if_prepare_app_does_not_become_frontmost(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop live switch prep fail ") as tmp:
            with patch(
                "quantagent.desktop_live_eval.frontmost_app",
                return_value=DesktopResult("frontmost", True, "Codex", {"stdout": "Codex"}),
            ), patch(
                "quantagent.desktop_live_eval.front_window",
                return_value=DesktopResult("window", True, "Codex|NO_WINDOW||"),
            ), patch("quantagent.desktop_live_eval.activate_app", return_value=DesktopResult("activate", True, "activated Finder")), patch(
                "quantagent.desktop_live_eval.hotkey"
            ) as hotkey_mock:
                result = run_live_desktop_eval_scenario(
                    Path(tmp),
                    {
                        "id": "switch-prep-fail",
                        "goal": "press cmd+tab",
                        "expected_status": "failure",
                        "setup": {"kind": "live_window_switch_probe", "prepare_apps": ["Finder"], "keys": ["cmd", "tab"], "require_change": True},
                    },
                    {"run_id": "switch-prep-fail"},
                )

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["data"]["prepared_frontmost_match"])
        hotkey_mock.assert_not_called()

    def test_window_switch_probe_can_continue_after_allowed_prepare_mismatch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop live switch prep mismatch ") as tmp:
            with patch(
                "quantagent.desktop_live_eval.frontmost_app",
                side_effect=[
                    DesktopResult("frontmost", True, "Shadowrocket", {"stdout": "Shadowrocket"}),
                    DesktopResult("frontmost", True, "Safari", {"stdout": "Safari"}),
                ],
            ), patch(
                "quantagent.desktop_live_eval.front_window",
                side_effect=[
                    DesktopResult("window", True, "Shadowrocket|NO_WINDOW||"),
                    DesktopResult("window", True, "Safari|Start Page|0,0|800,600"),
                ],
            ), patch("quantagent.desktop_live_eval.activate_app", return_value=DesktopResult("activate", True, "activated Finder")), patch(
                "quantagent.desktop_live_eval.hotkey", return_value=DesktopResult("hotkey", True, "hotkey: cmd+tab")
            ), patch(
                "quantagent.desktop_live_eval.time.sleep"
            ):
                result = run_live_desktop_eval_scenario(
                    Path(tmp),
                    {
                        "id": "switch-prep-mismatch",
                        "goal": "press cmd+tab",
                        "expected_status": "success",
                        "setup": {
                            "kind": "live_window_switch_probe",
                            "prepare_apps": ["Finder"],
                            "keys": ["cmd", "tab"],
                            "require_change": True,
                            "allow_prepare_mismatch": True,
                        },
                    },
                    {"run_id": "switch-prep-mismatch"},
                )

        self.assertTrue(result["ok"], result)
        self.assertFalse(result["data"]["prepared_frontmost_match"])
        self.assertTrue(result["data"]["changed"])

    def test_window_switch_probe_does_not_treat_permission_word_in_window_title_as_tcc_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop live switch permission title ") as tmp:
            with patch(
                "quantagent.desktop_live_eval.frontmost_app",
                side_effect=[
                    DesktopResult("frontmost", True, "Finder", {"stdout": "Finder"}),
                    DesktopResult("frontmost", True, "Terminal", {"stdout": "Terminal"}),
                ],
            ), patch(
                "quantagent.desktop_live_eval.front_window",
                side_effect=[
                    DesktopResult("window", True, "Finder|Documents|0,0|800,600"),
                    DesktopResult("window", True, "Terminal|claude --permission-mode bypassPermissions|0,0|800,600"),
                ],
            ), patch("quantagent.desktop_live_eval.activate_app", return_value=DesktopResult("activate", True, "activated Finder")), patch(
                "quantagent.desktop_live_eval.hotkey", return_value=DesktopResult("hotkey", True, "hotkey: cmd+tab")
            ), patch(
                "quantagent.desktop_live_eval.time.sleep"
            ):
                result = run_live_desktop_eval_scenario(
                    Path(tmp),
                    {
                        "id": "switch-permission-title",
                        "goal": "press cmd+tab",
                        "expected_status": "success",
                        "setup": {"kind": "live_window_switch_probe", "prepare_apps": ["Finder"], "keys": ["cmd", "tab"], "require_change": False},
                    },
                    {"run_id": "switch-permission-title"},
                )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["observed_status"], "success")

    def test_window_switch_probe_retries_transient_frontmost_failure_after_prepare(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop live switch retry ") as tmp:
            with patch(
                "quantagent.desktop_live_eval.frontmost_app",
                side_effect=[
                    DesktopResult("frontmost", False, "exit -15"),
                    DesktopResult("frontmost", True, "Finder", {"stdout": "Finder"}),
                    DesktopResult("frontmost", True, "Safari", {"stdout": "Safari"}),
                ],
            ), patch(
                "quantagent.desktop_live_eval.front_window",
                side_effect=[
                    DesktopResult("window", True, "Finder|Documents|0,0|800,600"),
                    DesktopResult("window", True, "Safari|Start Page|0,0|800,600"),
                ],
            ), patch("quantagent.desktop_live_eval.activate_app", return_value=DesktopResult("activate", True, "activated Finder")), patch(
                "quantagent.desktop_live_eval.hotkey", return_value=DesktopResult("hotkey", True, "hotkey: cmd+tab")
            ), patch(
                "quantagent.desktop_live_eval.time.sleep"
            ):
                result = run_live_desktop_eval_scenario(
                    Path(tmp),
                    {
                        "id": "switch-retry",
                        "goal": "press cmd+tab",
                        "expected_status": "success",
                        "setup": {"kind": "live_window_switch_probe", "prepare_apps": ["Finder"], "keys": ["cmd", "tab"], "require_change": True},
                    },
                    {"run_id": "switch-retry"},
                )

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["before_app"]["summary"], "Finder")
        self.assertTrue(result["data"]["prepared_frontmost_match"])


def _tokenization(
    *,
    ok: bool,
    count: int,
    status: str = "ok",
    summary: str = "tokenization ok",
    screen_hash: str = "hash",
    front_app: str = "Terminal",
    errors: tuple[str, ...] = (),
) -> SimpleNamespace:
    payload = {
        "ok": ok,
        "status": status,
        "summary": summary,
        "tokens": [{"id": f"T{index:04d}", "text": f"token {index}"} for index in range(count)],
        "errors": list(errors),
        "screen_hash": screen_hash,
        "front_app": front_app,
        "path": "/tmp/tokenization.json",
        "sources": {
            "ax": {"ok": ok, "summary": summary},
            "ocr": {"ok": ok, "summary": summary},
        },
    }
    return SimpleNamespace(
        ok=ok,
        status=status,
        summary=summary,
        tokens=tuple(payload["tokens"]),
        errors=errors,
        screen_hash=screen_hash,
        front_app=front_app,
        to_payload=lambda payload=payload: dict(payload),
    )


if __name__ == "__main__":
    unittest.main()
