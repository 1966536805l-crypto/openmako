from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from quantagent import desktop_night_daemon, runtime_store
from quantagent.desktop_intelligence import DesktopDaemonResult


RUNTIME_QUEUE = "desktop_night_daemon"
WORKER_ID_PREFIX = "desktop-night-daemon:"


def _enqueue_runtime_night_item(project: Path, item_id: str, goal: str, **kwargs: Any) -> Any:
    return runtime_store.enqueue_runtime_queue_item(
        project,
        item_id=item_id,
        queue=RUNTIME_QUEUE,
        task_kind="desktop_night_daemon",
        task=goal,
        payload={"goal": goal, "daemon_options": {"max_steps": 1, "delay": 0}},
        priority=10,
        max_attempts=2,
        **kwargs,
    )


def _runtime_items(project: Path) -> list[Any]:
    return runtime_store.list_runtime_queue_items(project, queue=RUNTIME_QUEUE)


def _only_runtime_item(project: Path) -> Any:
    rows = _runtime_items(project)
    if len(rows) != 1:
        raise AssertionError(f"expected exactly one runtime queue item, got {rows!r}")
    return rows[0]


def _payload(item: Any) -> dict[str, Any]:
    raw = getattr(item, "payload_json", "{}") or "{}"
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise AssertionError(f"runtime queue payload must be a dict: {value!r}")
    return value


def _daemon_result(project: Path, goal: str, *, ok: bool = True, status: str = "completed", summary: str = "ok") -> DesktopDaemonResult:
    run_dir = project / ".quantagent" / "desktop" / "intelligence" / "daemon"
    run_dir.mkdir(parents=True, exist_ok=True)
    return DesktopDaemonResult(
        ok=ok,
        status=status,
        summary=summary,
        goal=goal,
        records=(),
        results=(),
        query_events_path=str(run_dir / "query_events.jsonl"),
        trajectory_path=str(run_dir / "trajectory.jsonl"),
        stop_file=str(project / ".quantagent" / "desktop" / "night_daemon" / "STOP"),
        state_path=str(run_dir / "latest_state.json"),
    )


class DesktopNightRuntimeQueueWorkerTest(unittest.TestCase):
    def test_runtime_queue_item_is_claimed_heartbeated_and_done_after_successful_daemon_run(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop night runtime queue ") as tmp:
            project = Path(tmp)
            _enqueue_runtime_night_item(project, "rq-night-success", "observe screen")
            daemon_goals: list[str] = []

            def fake_daemon(project_path: Path, goal: str, **_: Any) -> DesktopDaemonResult:
                daemon_goals.append(goal)
                return _daemon_result(project_path, goal, ok=True, status="completed", summary="daemon completed")

            with patch.object(runtime_store, "claim_runtime_queue_item", wraps=runtime_store.claim_runtime_queue_item) as claim, patch.object(
                runtime_store,
                "heartbeat_runtime_queue_item",
                wraps=runtime_store.heartbeat_runtime_queue_item,
            ) as heartbeat, patch.object(desktop_night_daemon, "run_desktop_daemon", side_effect=fake_daemon):
                result = desktop_night_daemon.run_night_daemon(project, max_tasks=1, max_minutes=None, delay=0)

            item = _only_runtime_item(project)

        self.assertTrue(claim.called, "night worker must claim work through runtime_store.claim_runtime_queue_item")
        self.assertTrue(heartbeat.called, "night worker must heartbeat the claimed runtime_queue item after claim")
        self.assertEqual(result.processed, 1)
        self.assertEqual(daemon_goals, ["observe screen"])
        self.assertEqual(item.status, "done")
        self.assertIsNotNone(item.started_at)
        self.assertIsNotNone(item.ended_at)
        self.assertTrue(str(item.lease_owner or "").startswith(WORKER_ID_PREFIX))
        self.assertIn("daemon completed", json.dumps(_payload(item), ensure_ascii=False))

    def test_blocked_and_failed_daemon_results_finish_runtime_queue_item_with_matching_status(self) -> None:
        cases = (
            ("rq-night-blocked", "blocked", False, "blocked by policy", True),
            ("rq-night-failed", "failed", False, "daemon crashed", False),
        )
        for item_id, daemon_status, ok, summary, failure_pause in cases:
            with self.subTest(daemon_status=daemon_status), tempfile.TemporaryDirectory(prefix="desktop night runtime queue ") as tmp:
                project = Path(tmp)
                _enqueue_runtime_night_item(project, item_id, f"goal {daemon_status}")

                def fake_daemon(project_path: Path, goal: str, **_: Any) -> DesktopDaemonResult:
                    return _daemon_result(project_path, goal, ok=ok, status=daemon_status, summary=summary)

                with patch.object(desktop_night_daemon, "run_desktop_daemon", side_effect=fake_daemon):
                    result = desktop_night_daemon.run_night_daemon(
                        project,
                        max_tasks=1,
                        max_minutes=None,
                        delay=0,
                        failure_pause=failure_pause,
                    )

                item = _only_runtime_item(project)

            self.assertEqual(result.processed, 1)
            self.assertEqual(item.status, daemon_status)
            self.assertIsNotNone(item.ended_at)
            self.assertIn(summary, item.summary or item.error or json.dumps(_payload(item), ensure_ascii=False))

    def test_stop_file_created_after_claim_makes_runtime_queue_heartbeat_stop_item(self) -> None:
        with tempfile.TemporaryDirectory(prefix="desktop night runtime queue ") as tmp:
            project = Path(tmp)
            stop_file = project / "STOP"
            _enqueue_runtime_night_item(project, "rq-night-stop", "wait until stopped", stop_file=str(stop_file))
            heartbeat_statuses: list[str] = []

            def fake_daemon(project_path: Path, goal: str, **_: Any) -> DesktopDaemonResult:
                stop_file.write_text("operator stop\n", encoding="utf-8")
                return _daemon_result(project_path, goal, ok=True, status="completed", summary="should not complete queue item")

            original_heartbeat = runtime_store.heartbeat_runtime_queue_item

            def heartbeat_spy(*args: Any, **kwargs: Any) -> Any:
                item = original_heartbeat(*args, **kwargs)
                heartbeat_statuses.append(item.status)
                return item

            with patch.object(runtime_store, "heartbeat_runtime_queue_item", side_effect=heartbeat_spy), patch.object(
                desktop_night_daemon,
                "run_desktop_daemon",
                side_effect=fake_daemon,
            ):
                result = desktop_night_daemon.run_night_daemon(project, max_tasks=1, max_minutes=None, delay=0)

            item = _only_runtime_item(project)

        self.assertIn("stopped", heartbeat_statuses)
        self.assertEqual(item.status, "stopped")
        self.assertIsNotNone(item.ended_at)
        self.assertEqual(result.status, "stopped")

    def test_runtime_queue_worker_does_not_depend_on_legacy_json_claim_next_task(self) -> None:
        source = inspect.getsource(desktop_night_daemon.run_night_daemon)
        self.assertNotIn("_claim_next_task", source)

        with tempfile.TemporaryDirectory(prefix="desktop night runtime queue ") as tmp:
            project = Path(tmp)
            _enqueue_runtime_night_item(project, "rq-night-no-json-claim", "observe runtime queue")

            def fake_daemon(project_path: Path, goal: str, **_: Any) -> DesktopDaemonResult:
                return _daemon_result(project_path, goal, ok=True, status="completed", summary="runtime queue path")

            with patch.object(desktop_night_daemon, "_claim_next_task", side_effect=AssertionError("legacy JSON queue claim used")), patch.object(
                desktop_night_daemon,
                "run_desktop_daemon",
                side_effect=fake_daemon,
            ):
                result = desktop_night_daemon.run_night_daemon(project, max_tasks=1, max_minutes=None, delay=0)

            item = _only_runtime_item(project)

        self.assertEqual(result.processed, 1)
        self.assertEqual(item.status, "done")


if __name__ == "__main__":
    unittest.main()
