from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quantagent import runtime_store
from quantagent.cli import main
from quantagent.desktop_intelligence import DesktopDaemonResult


class DesktopDaemonCliTest(unittest.TestCase):
    def test_run_goal_enqueues_and_processes_one_task(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop daemon cli ") as tmp:
            project = Path(tmp)

            def fake_daemon(project_path: Path, goal: str, **_: object) -> DesktopDaemonResult:
                run_dir = project_path / ".quantagent" / "desktop" / "intelligence" / "daemon"
                run_dir.mkdir(parents=True, exist_ok=True)
                return DesktopDaemonResult(
                    True,
                    "completed",
                    f"fake daemon completed: {goal}",
                    goal,
                    (),
                    (),
                    str(run_dir / "query_events.jsonl"),
                    str(run_dir / "trajectory.jsonl"),
                    str(project_path / ".quantagent" / "desktop" / "night_daemon" / "STOP"),
                    str(run_dir / "latest_state.json"),
                )

            stdout = io.StringIO()
            with patch("quantagent.desktop_night_daemon.run_desktop_daemon", side_effect=fake_daemon), contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "desktop-daemon",
                        "--project",
                        tmp,
                        "--json",
                        "run",
                        "观察屏幕",
                        "--max-steps",
                        "1",
                        "--delay",
                        "0",
                    ]
                )
            payload = json.loads(stdout.getvalue())

        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["processed"], 1)
        self.assertEqual(payload["tasks"][0]["goal"], "观察屏幕")
        self.assertEqual(payload["tasks"][0]["status"], "done")

    def test_enqueue_status_and_stop_are_available(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop daemon cli ") as tmp:
            enqueue_out = io.StringIO()
            with contextlib.redirect_stdout(enqueue_out):
                enqueue_rc = main(
                    [
                        "--no-trust-prompt",
                        "desktop-daemon",
                        "--project",
                        tmp,
                        "--json",
                        "enqueue",
                        "截图",
                        "--max-steps",
                        "2",
                    ]
                )
            enqueued = json.loads(enqueue_out.getvalue())

            status_out = io.StringIO()
            with contextlib.redirect_stdout(status_out):
                status_rc = main(["--no-trust-prompt", "desktop-daemon", "--project", tmp, "--json", "status"])
            status = json.loads(status_out.getvalue())

            stop_out = io.StringIO()
            with contextlib.redirect_stdout(stop_out):
                stop_rc = main(["--no-trust-prompt", "desktop-daemon", "--project", tmp, "--json", "stop", "--all"])
            stopped = json.loads(stop_out.getvalue())

        self.assertEqual(enqueue_rc, 0)
        self.assertEqual(status_rc, 0)
        self.assertEqual(stop_rc, 0)
        self.assertEqual(enqueued["goal"], "截图")
        self.assertEqual(status["tasks"][0]["status"], "queued")
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["tasks"][0]["status"], "stopped")

    def test_run_can_claim_runtime_queue_item(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop daemon cli runtime queue ") as tmp:
            project = Path(tmp)
            runtime_store.enqueue_runtime_queue_item(
                project,
                item_id="rq-cli-night",
                queue="desktop_night_daemon",
                task_kind="desktop_night_daemon",
                task="观察 runtime queue",
                payload={"goal": "观察 runtime queue", "daemon_options": {"max_steps": 1, "delay": 0}},
            )

            def fake_daemon(project_path: Path, goal: str, **_: object) -> DesktopDaemonResult:
                run_dir = project_path / ".quantagent" / "desktop" / "intelligence" / "daemon"
                run_dir.mkdir(parents=True, exist_ok=True)
                return DesktopDaemonResult(
                    True,
                    "completed",
                    f"runtime queue completed: {goal}",
                    goal,
                    (),
                    (),
                    str(run_dir / "query_events.jsonl"),
                    str(run_dir / "trajectory.jsonl"),
                    str(project_path / ".quantagent" / "desktop" / "night_daemon" / "STOP"),
                    str(run_dir / "latest_state.json"),
                )

            stdout = io.StringIO()
            with patch("quantagent.desktop_night_daemon.run_desktop_daemon", side_effect=fake_daemon), contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "desktop-daemon",
                        "--project",
                        tmp,
                        "--json",
                        "run",
                        "--runtime-queue",
                        "desktop_night_daemon",
                        "--worker-id",
                        "worker-cli",
                        "--max-tasks",
                        "1",
                        "--delay",
                        "0",
                    ]
                )
            payload = json.loads(stdout.getvalue())
            item = runtime_store.list_runtime_queue_items(project, queue="desktop_night_daemon")[0]

        self.assertEqual(rc, 0)
        self.assertEqual(payload["status"], "done")
        self.assertEqual(payload["processed"], 1)
        self.assertIn("#runtime_queue:desktop_night_daemon", payload["queue_path"])
        self.assertEqual(payload["tasks"][0]["id"], "rq-cli-night")
        self.assertEqual(payload["tasks"][0]["status"], "done")
        self.assertEqual(item.status, "done")
        self.assertEqual(item.lease_owner, "worker-cli")

    def test_runtime_queue_run_requires_worker_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop daemon cli runtime queue ") as tmp:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = main(
                    [
                        "--no-trust-prompt",
                        "desktop-daemon",
                        "--project",
                        tmp,
                        "run",
                        "--runtime-queue",
                        "desktop_night_daemon",
                    ]
                )

        self.assertEqual(rc, 2)
        self.assertIn("--worker-id is required", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
