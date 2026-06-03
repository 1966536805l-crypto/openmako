from __future__ import annotations

import json
import tempfile
import time
import unittest
import contextlib
import io
from pathlib import Path
from typing import Any

from quantagent.cli import main
from quantagent.desktop_l4_soak import DesktopL4SoakConfig, run_desktop_l4_soak


def hanging_l4_soak_hook(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    time.sleep(5)
    return {"ok": True, "status": "success", "summary": "too late"}


class DesktopL4SoakContractTest(unittest.TestCase):
    def paths(self, project: Path) -> dict[str, Path]:
        run_dir = project / ".quantagent" / "desktop" / "l4_soak"
        return {
            "run_dir": run_dir,
            "stop_file": run_dir / "STOP",
            "trajectory_path": run_dir / "trajectory.jsonl",
            "heartbeat_path": run_dir / "heartbeat.json",
            "status_path": run_dir / "status.json",
            "result_path": run_dir / "result.json",
        }

    def config(self, project: Path, **overrides: Any) -> DesktopL4SoakConfig:
        paths = self.paths(project)
        values: dict[str, Any] = {
            "project": project,
            "max_cycles": 1,
            "dry_run": True,
            "execute": False,
            "reviewed": True,
            "allow_actions": True,
            "interval_seconds": 0,
            "stop_file": paths["stop_file"],
            "trajectory_path": paths["trajectory_path"],
            "heartbeat_path": paths["heartbeat_path"],
            "status_path": paths["status_path"],
            "result_path": paths["result_path"],
            "loop_threshold": 3,
            "screenshot": lambda *_args, **_kwargs: self.ok_screenshot(),
            "observe": lambda *_args, **_kwargs: self.ok_observation(),
            "decide": lambda *_args, **_kwargs: self.safe_action(),
            "preflight": lambda *_args, **_kwargs: self.allowed_preflight(),
            "execute_action": lambda *_args, **_kwargs: self.ok_action_result(),
            "verify": lambda *_args, **_kwargs: self.ok_verify_result(),
            "sleep": lambda _seconds: None,
        }
        values.update(overrides)
        return DesktopL4SoakConfig(**values)

    def ok_screenshot(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "success",
            "summary": "screenshot ok",
            "image_path": "screen.png",
        }

    def ok_observation(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "success",
            "summary": "observe ok",
            "observation_id": "obs-1",
            "screen_hash": "screen-1",
        }

    def safe_action(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "action",
            "action": "wait",
            "args": {"seconds": 0},
            "summary": "wait",
            "risk": "low",
        }

    def allowed_preflight(self) -> dict[str, Any]:
        return {
            "ok": True,
            "allowed": True,
            "status": "allowed",
            "summary": "allowed",
        }

    def ok_action_result(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "success",
            "summary": "action ok",
        }

    def ok_verify_result(self) -> dict[str, Any]:
        return {
            "ok": True,
            "status": "success",
            "summary": "verify ok",
        }

    def permission_failure(self, phase: str) -> dict[str, Any]:
        return {
            "ok": False,
            "status": "permission_denied",
            "summary": f"{phase} permission denied",
            "error_type": "PermissionError",
            "permission_failure": True,
        }

    def blocked_preflight(self, summary: str = "high-risk action blocked") -> dict[str, Any]:
        return {
            "ok": False,
            "allowed": False,
            "status": "blocked",
            "summary": summary,
            "risk": "high",
        }

    def result_payload(self, result: Any) -> dict[str, Any]:
        if isinstance(result, dict):
            return result
        if hasattr(result, "to_payload"):
            return dict(result.to_payload())
        if hasattr(result, "to_json"):
            return dict(json.loads(result.to_json()))
        return dict(vars(result))

    def result_status(self, result: Any) -> str:
        payload = self.result_payload(result)
        return str(payload.get("status") or getattr(result, "status", ""))

    def read_json(self, path: Path) -> dict[str, Any]:
        return json.loads(path.read_text(encoding="utf-8"))

    def read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def read_result_json(self, result: Any, fallback: Path) -> dict[str, Any]:
        payload = self.result_payload(result)
        json_path = Path(str(payload.get("json_path") or payload.get("result_path") or fallback))
        self.assertTrue(json_path.exists(), f"missing result json: {json_path}")
        return self.read_json(json_path)

    def test_dry_run_multiple_cycles_writes_trajectory_heartbeat_status(self) -> None:
        calls = {"screenshot": 0, "observe": 0, "execute": 0}

        def screenshot(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            calls["screenshot"] += 1
            return self.ok_screenshot()

        def observe(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            calls["observe"] += 1
            return self.ok_observation()

        def execute_action(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            calls["execute"] += 1
            return self.ok_action_result()

        with tempfile.TemporaryDirectory(prefix="desktop l4 soak dry ") as tmp:
            project = Path(tmp)
            paths = self.paths(project)
            result = run_desktop_l4_soak(
                self.config(
                    project,
                    max_cycles=3,
                    dry_run=True,
                    execute=False,
                    screenshot=screenshot,
                    observe=observe,
                    execute_action=execute_action,
                )
            )
            payload = self.read_result_json(result, paths["result_path"])
            metrics = payload["metrics"]
            trajectory = self.read_jsonl(Path(metrics["trajectory_path"]))
            heartbeat = self.read_json(Path(metrics["heartbeat_path"]))
            status_path = Path(str(payload.get("status_path") or paths["status_path"]))
            status = self.read_json(status_path)

        self.assertEqual(self.result_status(result), "success")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(metrics["cycles"], 3)
        self.assertEqual(metrics["blocked_actions"], 0)
        self.assertEqual(metrics["permission_failures"], 0)
        self.assertEqual(metrics["loop_stops"], 0)
        self.assertEqual(calls, {"screenshot": 3, "observe": 3, "execute": 0})
        self.assertGreaterEqual(len(trajectory), 3)
        self.assertEqual(heartbeat["status"], "success")
        self.assertEqual(status["status"], "success")

    def test_screenshot_or_observe_permission_failure_pauses_or_stops_before_action(self) -> None:
        for failing_phase in ("screenshot", "observe"):
            with self.subTest(failing_phase=failing_phase), tempfile.TemporaryDirectory(prefix="desktop l4 soak perm ") as tmp:
                calls = {"screenshot": 0, "observe": 0, "execute": 0}
                project = Path(tmp)
                paths = self.paths(project)

                def screenshot(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
                    calls["screenshot"] += 1
                    if failing_phase == "screenshot":
                        return self.permission_failure("screenshot")
                    return self.ok_screenshot()

                def observe(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
                    calls["observe"] += 1
                    if failing_phase == "observe":
                        return self.permission_failure("observe")
                    return self.ok_observation()

                def execute_action(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
                    calls["execute"] += 1
                    return self.ok_action_result()

                result = run_desktop_l4_soak(
                    self.config(
                        project,
                        max_cycles=2,
                        dry_run=False,
                        execute=True,
                        screenshot=screenshot,
                        observe=observe,
                        execute_action=execute_action,
                    )
                )
                payload = self.read_result_json(result, paths["result_path"])
                status = self.read_json(Path(str(payload.get("status_path") or paths["status_path"])))

                self.assertIn(self.result_status(result), {"paused", "stopped"})
                self.assertIn(payload["status"], {"paused", "stopped"})
                self.assertIn(status["status"], {"paused", "stopped"})
                self.assertEqual(payload["metrics"]["permission_failures"], 1)
                self.assertEqual(calls["execute"], 0)
                if failing_phase == "screenshot":
                    self.assertEqual(calls["observe"], 0)

    def test_repeated_same_action_loop_stops_or_blocks_run(self) -> None:
        calls = {"execute": 0}

        def same_action(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "ok": True,
                "status": "action",
                "action": "click",
                "args": {"target_text": "Refresh"},
                "summary": "click Refresh",
                "risk": "low",
            }

        def execute_action(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            calls["execute"] += 1
            return self.ok_action_result()

        with tempfile.TemporaryDirectory(prefix="desktop l4 soak loop ") as tmp:
            project = Path(tmp)
            paths = self.paths(project)
            result = run_desktop_l4_soak(
                self.config(
                    project,
                    max_cycles=5,
                    dry_run=False,
                    execute=True,
                    decide=same_action,
                    execute_action=execute_action,
                    loop_threshold=3,
                )
            )
            payload = self.read_result_json(result, paths["result_path"])
            metrics = payload["metrics"]

        self.assertIn(self.result_status(result), {"stopped", "blocked"})
        self.assertIn(payload["status"], {"stopped", "blocked"})
        self.assertEqual(metrics["loop_stops"], 1)
        self.assertLess(metrics["cycles"], 5)
        self.assertLess(calls["execute"], 5)

    def test_high_risk_click_and_type_are_blocked_by_preflight_before_execute(self) -> None:
        cases = (
            ("click", {"target_text": "Pay now"}, "payment click blocked"),
            ("type", {"text": "password=abc123"}, "credential text blocked"),
        )
        for action_name, args, summary in cases:
            with self.subTest(action=action_name), tempfile.TemporaryDirectory(prefix="desktop l4 soak risk ") as tmp:
                calls = {"preflight": 0, "execute": 0}
                project = Path(tmp)
                paths = self.paths(project)

                def risky_action(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
                    return {
                        "ok": True,
                        "status": "action",
                        "action": action_name,
                        "args": args,
                        "summary": summary,
                        "risk": "high",
                    }

                def preflight(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
                    calls["preflight"] += 1
                    return self.blocked_preflight(summary)

                def execute_action(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
                    calls["execute"] += 1
                    return self.ok_action_result()

                result = run_desktop_l4_soak(
                    self.config(
                        project,
                        max_cycles=1,
                        dry_run=False,
                        execute=True,
                        decide=risky_action,
                        preflight=preflight,
                        execute_action=execute_action,
                    )
                )
                payload = self.read_result_json(result, paths["result_path"])

                self.assertEqual(self.result_status(result), "blocked")
                self.assertEqual(payload["status"], "blocked")
                self.assertEqual(payload["metrics"]["blocked_actions"], 1)
                self.assertEqual(calls, {"preflight": 1, "execute": 0})

    def test_post_action_verify_failure_stops_live_soak(self) -> None:
        calls = {"execute": 0, "verify": 0}

        def click_action(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "ok": True,
                "status": "action",
                "action": "click",
                "args": {"target_text": "Refresh"},
                "summary": "click Refresh",
                "risk": "low",
            }

        def execute_action(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            calls["execute"] += 1
            return self.ok_action_result()

        def verify(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            calls["verify"] += 1
            return {"ok": False, "status": "verify_failed", "summary": "no visible desktop progress after click"}

        with tempfile.TemporaryDirectory(prefix="desktop l4 soak verify ") as tmp:
            project = Path(tmp)
            paths = self.paths(project)
            result = run_desktop_l4_soak(
                self.config(
                    project,
                    max_cycles=2,
                    dry_run=False,
                    execute=True,
                    reviewed=True,
                    allow_actions=True,
                    decide=click_action,
                    execute_action=execute_action,
                    verify=verify,
                )
            )
            payload = self.read_result_json(result, paths["result_path"])

        self.assertEqual(self.result_status(result), "verify_failed")
        self.assertEqual(payload["status"], "verify_failed")
        self.assertEqual(payload["metrics"]["actions_executed"], 1)
        self.assertEqual(payload["metrics"]["verification_failures"], 1)
        self.assertEqual(calls, {"execute": 1, "verify": 1})

    def test_live_default_preflight_blocks_unfenced_target_action(self) -> None:
        calls = {"execute": 0}

        def type_action(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {
                "ok": True,
                "status": "action",
                "action": "type",
                "args": {"text": "hello"},
                "summary": "blind type",
                "risk": "low",
            }

        def execute_action(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            calls["execute"] += 1
            return self.ok_action_result()

        with tempfile.TemporaryDirectory(prefix="desktop l4 soak fence ") as tmp:
            project = Path(tmp)
            paths = self.paths(project)
            result = run_desktop_l4_soak(
                self.config(
                    project,
                    max_cycles=1,
                    dry_run=False,
                    execute=True,
                    reviewed=True,
                    allow_actions=True,
                    decide=type_action,
                    preflight=None,
                    execute_action=execute_action,
                )
            )
            payload = self.read_result_json(result, paths["result_path"])

        self.assertEqual(self.result_status(result), "blocked")
        self.assertEqual(payload["metrics"]["blocked_actions"], 1)
        self.assertIn("missing observation fence", payload["summary"])
        self.assertEqual(calls["execute"], 0)

    def test_stop_file_exists_exits_before_observe(self) -> None:
        calls = {"observe": 0, "execute": 0}

        def observe(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            calls["observe"] += 1
            return self.ok_observation()

        def execute_action(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            calls["execute"] += 1
            return self.ok_action_result()

        with tempfile.TemporaryDirectory(prefix="desktop l4 soak stop ") as tmp:
            project = Path(tmp)
            paths = self.paths(project)
            paths["stop_file"].parent.mkdir(parents=True, exist_ok=True)
            paths["stop_file"].write_text("stop\n", encoding="utf-8")

            result = run_desktop_l4_soak(
                self.config(
                    project,
                    max_cycles=3,
                    dry_run=False,
                    execute=True,
                    observe=observe,
                    execute_action=execute_action,
                )
            )
            payload = self.read_result_json(result, paths["result_path"])

        self.assertEqual(self.result_status(result), "stopped")
        self.assertEqual(payload["status"], "stopped")
        self.assertEqual(payload["metrics"]["cycles"], 0)
        self.assertEqual(calls, {"observe": 0, "execute": 0})

    def test_phase_watchdog_times_out_hung_screenshot_and_writes_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop l4 soak phase timeout ") as tmp:
            project = Path(tmp)
            paths = self.paths(project)
            started = time.monotonic()
            result = run_desktop_l4_soak(
                self.config(
                    project,
                    max_cycles=1,
                    dry_run=False,
                    execute=True,
                    reviewed=True,
                    allow_actions=True,
                    screenshot=hanging_l4_soak_hook,
                    phase_timeout_seconds=0.15,
                )
            )
            elapsed = time.monotonic() - started
            payload = self.read_result_json(result, paths["result_path"])
            stop_written = paths["stop_file"].exists()

        self.assertLess(elapsed, 2.0)
        self.assertEqual(self.result_status(result), "timeout")
        self.assertEqual(payload["status"], "timeout")
        self.assertEqual(payload["metrics"]["watchdog_kills"], 1)
        self.assertEqual(payload["metrics"]["watchdog_timeouts"], 1)
        self.assertEqual(payload["metrics"]["phase_timeouts"], 1)
        self.assertTrue(stop_written)

    def test_live_l4_soak_requires_all_execution_gates_before_screenshot(self) -> None:
        calls = {"screenshot": 0}

        def screenshot(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            calls["screenshot"] += 1
            return self.ok_screenshot()

        with tempfile.TemporaryDirectory(prefix="desktop l4 soak live gate ") as tmp:
            project = Path(tmp)
            paths = self.paths(project)
            result = run_desktop_l4_soak(
                self.config(
                    project,
                    dry_run=False,
                    execute=True,
                    reviewed=False,
                    allow_actions=True,
                    screenshot=screenshot,
                )
            )
            payload = self.read_result_json(result, paths["result_path"])

        self.assertEqual(self.result_status(result), "blocked")
        self.assertEqual(payload["status"], "blocked")
        self.assertEqual(calls["screenshot"], 0)
        self.assertIn("--reviewed", payload["summary"])

    def test_cli_l4_soak_no_dry_run_without_gates_is_blocked_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop l4 soak cli blocked ") as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "desktop", "--project", tmp, "l4-soak", "--no-dry-run", "--json"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 1)
        self.assertEqual(payload["status"], "blocked")
        self.assertIn("--execute", payload["summary"])
        self.assertIn("--reviewed", payload["summary"])
        self.assertIn("--allow-actions", payload["summary"])

    def test_cli_l4_soak_dry_run_accepts_goal_paths_and_renders_cycles(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop l4 soak cli paths ") as tmp:
            project = Path(tmp)
            result_path = project / "custom-result.json"
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "desktop",
                        "--project",
                        tmp,
                        "l4-soak",
                        "--cycles",
                        "2",
                        "--goal",
                        "observe desktop",
                        "--result-path",
                        str(result_path),
                    ]
                )
            rendered = stdout.getvalue()
            payload = self.read_json(result_path)

        self.assertEqual(rc, 0)
        self.assertIn("- cycles: 2", rendered)
        self.assertEqual(payload["metrics"]["cycles"], 2)
        self.assertEqual(payload["status"], "success")

    def test_json_result_metrics_include_required_l4_soak_counters_and_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop l4 soak metrics ") as tmp:
            project = Path(tmp)
            paths = self.paths(project)
            result = run_desktop_l4_soak(self.config(project, max_cycles=1))
            payload = self.read_result_json(result, paths["result_path"])
            metrics = payload["metrics"]
            trajectory_exists = Path(metrics["trajectory_path"]).exists()
            heartbeat_exists = Path(metrics["heartbeat_path"]).exists()

            for key in (
                "cycles",
                "blocked_actions",
                "permission_failures",
                "loop_stops",
                "trajectory_path",
                "heartbeat_path",
            ):
                self.assertIn(key, metrics)
            self.assertTrue(trajectory_exists)
            self.assertTrue(heartbeat_exists)


if __name__ == "__main__":
    unittest.main()
