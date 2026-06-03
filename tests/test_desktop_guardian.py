from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from quantagent.cli import main
from quantagent.desktop_control import desktop_dir
from quantagent.desktop_guardian import inspect_desktop_guardian, run_desktop_guardian
from quantagent.hook_events import append_query_event
from quantagent.trajectory import record_observation


class DesktopGuardianTest(unittest.TestCase):
    def test_idle_without_state_does_not_write_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop guardian idle ") as tmp:
            project = Path(tmp)
            result = inspect_desktop_guardian(project)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "idle")
        self.assertFalse(Path(result.stop_file).exists())

    def test_completed_state_does_not_stop_even_with_records(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop guardian completed ") as tmp:
            project = Path(tmp)
            paths = self.write_state(
                project,
                {"status": "completed", "goal": "click Search", "summary": "done", "records": [self.act_record("click")] * 4},
            )
            result = inspect_desktop_guardian(project)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "ok")
        self.assertFalse(paths["stop"].exists())

    def test_running_state_with_stale_heartbeat_writes_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop guardian stale ") as tmp:
            project = Path(tmp)
            paths = self.write_state(project, {"status": "running", "goal": "click Search", "summary": "working", "records": [self.act_record("click")]})
            self.write_ledgers(paths)
            self.touch_all(paths, mtime=100.0)
            result = inspect_desktop_guardian(project, max_event_age_seconds=60, now=lambda: 200.0)

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "stopped")
            self.assertTrue(paths["stop"].exists())
            self.assertIn("stale_heartbeat", self.codes(result))

    def test_same_action_repeat_writes_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop guardian repeat ") as tmp:
            project = Path(tmp)
            paths = self.write_state(
                project,
                {"status": "running", "goal": "click Search", "summary": "working", "records": [self.act_record("click", x=10, y=20)] * 3},
            )
            self.write_ledgers(paths)
            result = inspect_desktop_guardian(project, same_action_limit=3)

            self.assertFalse(result.ok)
            self.assertTrue(paths["stop"].exists())
            self.assertIn("same_action_repeat", self.codes(result))

    def test_permission_failure_writes_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop guardian permission ") as tmp:
            project = Path(tmp)
            paths = self.write_state(
                project,
                {
                    "status": "running",
                    "goal": "observe",
                    "summary": "could not create image from display; probable_cause=macOS Screen Recording permission is missing",
                    "records": [],
                },
            )
            result = inspect_desktop_guardian(project)

            self.assertFalse(result.ok)
            self.assertTrue(paths["stop"].exists())
            self.assertIn("permission_required", self.codes(result))

    def test_network_failure_writes_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop guardian network ") as tmp:
            project = Path(tmp)
            paths = self.write_state(
                project,
                {"status": "running", "goal": "search web", "summary": "ERR_INTERNET_DISCONNECTED offline", "records": []},
            )
            result = inspect_desktop_guardian(project)

            self.assertFalse(result.ok)
            self.assertTrue(paths["stop"].exists())
            self.assertIn("network_failed", self.codes(result))

    def test_high_risk_goal_writes_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop guardian risk ") as tmp:
            project = Path(tmp)
            paths = self.write_state(project, {"status": "running", "goal": "click Delete account", "summary": "working", "records": []})
            result = inspect_desktop_guardian(project)

            self.assertFalse(result.ok)
            self.assertTrue(paths["stop"].exists())
            self.assertIn("high_risk_detected", self.codes(result))

    def test_missing_ledgers_for_recorded_actions_writes_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop guardian ledger ") as tmp:
            project = Path(tmp)
            paths = self.write_state(project, {"status": "running", "goal": "click Search", "summary": "working", "records": [self.act_record("click")]})
            result = inspect_desktop_guardian(project)

            self.assertFalse(result.ok)
            self.assertTrue(paths["stop"].exists())
            self.assertIn("query_events_missing", self.codes(result))
            self.assertIn("trajectory_missing", self.codes(result))

    def test_existing_stop_is_reported_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop guardian stop present ") as tmp:
            project = Path(tmp)
            paths = self.write_state(project, {"status": "running", "goal": "click Search", "summary": "working", "records": []})
            paths["stop"].parent.mkdir(parents=True, exist_ok=True)
            paths["stop"].write_text("operator stop\n", encoding="utf-8")
            before = paths["stop"].read_text(encoding="utf-8")
            result = inspect_desktop_guardian(project)

            self.assertFalse(result.ok)
            self.assertEqual(result.status, "stopped")
            self.assertFalse(result.wrote_stop)
            self.assertEqual(before, paths["stop"].read_text(encoding="utf-8"))

    def test_cli_guard_json(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop guardian cli ") as tmp:
            project = Path(tmp)
            self.write_state(project, {"status": "running", "goal": "click Delete account", "summary": "working", "records": []})
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(["--no-trust-prompt", "desktop", "--project", tmp, "--json", "guard"])
            payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 1)
        self.assertEqual(payload["status"], "stopped")
        self.assertIn("high_risk_detected", {item["code"] for item in payload["findings"]})

    def test_watch_timeout_returns_without_stop_findings(self) -> None:
        clock = {"now": 100.0}

        def fake_now() -> float:
            clock["now"] += 10.0
            return clock["now"]

        with tempfile.TemporaryDirectory(prefix="desktop guardian watch ") as tmp:
            project = Path(tmp)
            self.write_state(project, {"status": "completed", "goal": "observe", "summary": "done", "records": []})
            result = run_desktop_guardian(project, watch=True, max_minutes=0.01, interval=0.0, now=fake_now, sleep=lambda _: None)

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "watch_timeout")

    def write_state(self, project: Path, payload: dict[str, object]) -> dict[str, Path]:
        run_dir = desktop_dir(project) / "intelligence" / "daemon"
        run_dir.mkdir(parents=True, exist_ok=True)
        stop = desktop_dir(project) / "agent" / "STOP"
        state = run_dir / "latest_state.json"
        data = {"stop_file": str(stop)}
        data.update(payload)
        state.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {"run_dir": run_dir, "state": state, "stop": stop, "query": run_dir / "query_events.jsonl", "trajectory": run_dir / "trajectory.jsonl"}

    def write_ledgers(self, paths: dict[str, Path]) -> None:
        append_query_event(paths["query"], {"kind": "query_start", "query_id": "qa-guardian", "summary": "started"})
        record_observation(paths["trajectory"], "observed", ok=True)

    def touch_all(self, paths: dict[str, Path], *, mtime: float) -> None:
        for key in ("state", "query", "trajectory"):
            os.utime(paths[key], (mtime, mtime))

    def act_record(self, action: str, *, x: int = 1, y: int = 2) -> dict[str, object]:
        return {"step": 1, "phase": "act", "status": "ok", "summary": f"{action} ok", "data": {"action": action, "data": {"x": x, "y": y}}}

    def codes(self, result) -> set[str]:
        return {finding.code for finding in result.findings}


if __name__ == "__main__":
    unittest.main()
