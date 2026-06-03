from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from quantagent.runtime_store import get_task_run
from quantagent.task_runtime import reconcile_runtime_tasks
from quantagent.task_state import (
    DELIVERY_PENDING,
    LOST,
    NOTIFY_STATE_CHANGES,
    PASSED,
    RUNNING,
    SCOPE_SESSION,
    TERMINAL_BLOCKED,
    TERMINAL_SUCCEEDED,
    ResearchTask,
    add_task,
    load_tasks,
    save_tasks,
    task_file,
    update_task,
)


class TaskRegistryContractTest(unittest.TestCase):
    def make_project(self) -> tempfile.TemporaryDirectory[str]:
        return tempfile.TemporaryDirectory(prefix="quantagent task registry ")

    def test_research_task_round_trips_registry_metadata_and_sqlite_mirror(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            task = add_task(
                project,
                "child registry task",
                detail="inspect contract",
                owner_key="agent/audit",
                scope_kind=SCOPE_SESSION,
                child_session_key="session-child",
                parent_task_id="qa-parent",
                notify_policy=NOTIFY_STATE_CHANGES,
                cleanup_after=1234567890,
            )
            update_task(project, task.id, status=PASSED, note="done", terminal_summary="finished cleanly")

            loaded = load_tasks(project)[0]
            record = get_task_run(project, task.id)

            self.assertEqual(loaded.owner_key, "agent/audit")
            self.assertEqual(loaded.scope_kind, SCOPE_SESSION)
            self.assertEqual(loaded.child_session_key, "session-child")
            self.assertEqual(loaded.parent_task_id, "qa-parent")
            self.assertEqual(loaded.notify_policy, NOTIFY_STATE_CHANGES)
            self.assertEqual(loaded.delivery_status, DELIVERY_PENDING)
            self.assertEqual(loaded.terminal_outcome, TERMINAL_SUCCEEDED)
            self.assertEqual(loaded.terminal_summary, "finished cleanly")
            self.assertEqual(loaded.cleanup_after, 1234567890)
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.owner_key, "agent/audit")
            self.assertEqual(record.scope_kind, SCOPE_SESSION)
            self.assertEqual(record.child_session_key, "session-child")
            self.assertEqual(record.parent_task_id, "qa-parent")
            self.assertEqual(record.notify_policy, NOTIFY_STATE_CHANGES)
            self.assertEqual(record.cleanup_after, 1234567890)
            self.assertEqual(record.terminal_summary, "finished cleanly")

    def test_reconcile_marks_missing_runtime_status_as_lost(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            save_tasks(
                project,
                [
                    ResearchTask(
                        id="qrt-0001",
                        title="lost child",
                        status=RUNNING,
                        kind="shell",
                        pid=987654321,
                        status_path=str(project / "missing-status.json"),
                        scope_kind=SCOPE_SESSION,
                        child_session_key="session-child",
                    )
                ],
            )

            tasks = reconcile_runtime_tasks(project)
            record = get_task_run(project, "qrt-0001")

            self.assertEqual(tasks[0].status, LOST)
            self.assertEqual(tasks[0].terminal_outcome, TERMINAL_BLOCKED)
            self.assertIn("without status file", tasks[0].terminal_summary)
            self.assertEqual(tasks[0].delivery_status, DELIVERY_PENDING)
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record.status, LOST)

    def test_load_tasks_accepts_camel_case_registry_snapshot_fields(self) -> None:
        with self.make_project() as tmp:
            project = Path(tmp)
            path = task_file(project)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "tasks": [
                            {
                                "taskId": "qrt-0002",
                                "task": "loaded from registry shape",
                                "status": "queued",
                                "ownerKey": "system",
                                "scopeKind": "session",
                                "childSessionKey": "session-loaded",
                                "deliveryStatus": "session_queued",
                                "notifyPolicy": "state_changes",
                                "terminalSummary": "",
                                "terminalOutcome": "",
                                "cleanupAfter": 42,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            task = load_tasks(project)[0]

            self.assertEqual(task.id, "qrt-0002")
            self.assertEqual(task.title, "loaded from registry shape")
            self.assertEqual(task.owner_key, "system")
            self.assertEqual(task.scope_kind, SCOPE_SESSION)
            self.assertEqual(task.child_session_key, "session-loaded")
            self.assertEqual(task.delivery_status, "session_queued")
            self.assertEqual(task.cleanup_after, 42)


if __name__ == "__main__":
    unittest.main()
